// Codex Auto Resume - the popup's messages: everything Windows says to it and what each one decides, its opening, a
// button's face and the calls it makes (v0.6.27, S6.3d).
//
// ui/popup/messages.py's PopupMessages, ported call for call as the other half of PopupWindow (gui/PopupWindow.cs). Each
// handler reads and changes the window's own state and calls the window's own methods. A call runs on a worker thread and
// comes back as WM_POPUP_RESULT; the popup's reads are the core's (each `snapshot` carries the view), so a read asked
// here asks nothing.
using System;
using System.Collections.Generic;

namespace CodexAutoResume
{
    internal sealed partial class PopupWindow
    {
        /// Re-read the list every third one-second tick while visible (REFRESH_TICKS): the core reads, so only counted.
        internal const int RefreshTicks = 3;

        /// The window procedure, for the probe to send a message to (as Windows would).
        internal IntPtr Message(int message, long wParam, long lParam, IntPtr? hwnd = null)
        {
            return WindowProc(hwnd ?? Hwnd, (uint)message, new IntPtr(wParam), new IntPtr(lParam));
        }

        private IntPtr WindowProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam)
        {
            CardLayers layers = Layers;
            if (layers != null && hwnd == layers.ShadowHwnd) return SurfaceScreen.DefWindowProc(hwnd, message, wParam, lParam);
            try
            {
                IntPtr? handled = Handle(hwnd, (int)message, wParam.ToInt64(), lParam.ToInt64());
                if (handled != null) return handled.Value;
            }
            catch (Exception exc)
            {
                Log("tray popup message failed (" + TipCard.PythonName(exc) + ")");
            }
            return SurfaceScreen.DefWindowProc(hwnd, message, wParam, lParam);
        }

        private IntPtr? Handle(IntPtr hwnd, int message, long wparam, long lparam)
        {
            IntPtr zero = IntPtr.Zero;
            if (message == SurfaceNative.WM_PAINT)
            {
                Paint(hwnd);
                return zero;
            }
            if (message == SurfaceNative.WM_ERASEBKGND) return new IntPtr(1);
            if (message == SurfaceNative.WM_TIMER)
            {
                if (wparam == TimerFrame)
                {
                    if (Opening != null) OpeningStep();
                    SyncFrames();
                    if (Card) Push();
                    else SurfaceScreen.InvalidateRect(hwnd);
                }
                else if (wparam == TimerTick)
                {
                    Ticks += 1;
                    Still = AskStillNow();
                    if (Ticks % RefreshTicks == 0) RequestRead();
                    Update();
                }
                else if (wparam == TimerFirst && PendingShow != null) Present((bool)PendingShow[0], (int[])PendingShow[1]);
                return zero;
            }
            if (message == SurfaceNative.WM_POPUP_RESULT)
            {
                Finished(wparam);
                return zero;
            }
            if (message == WM_POPUP_PAINT)
            {
                if (Owed) Push();
                return zero;
            }
            if (message == SurfaceNative.WM_GETOBJECT)
            {
                IntPtr? answered = Accessible != null ? Accessible(this, new IntPtr(wparam), new IntPtr(lparam)) : null;
                return answered;
            }
            if (message == SurfaceNative.WM_POPUP_STRINGS)
            {
                // The core hands the view in the new words in the snapshot it sends right after the `strings` event; one
                // that came first has taken the strings up already, and the window is brought up to date once, as the
                // reference's one message does.
                bool pending;
                lock (guard) pending = pendingStrings != null;
                if (Visible && pending) Update();
                return zero;
            }
            if (message == SurfaceNative.WM_ACTIVATE)
            {
                if ((wparam & 0xFFFF) == SurfaceNative.WA_INACTIVE)
                {
                    if (Visible && !MenuHas(new IntPtr(lparam))) Hide();
                    return zero;
                }
                return null;
            }
            if (message == SurfaceNative.WM_CLOSE)
            {
                Hide();
                return zero;
            }
            if (message == SurfaceNative.WM_KEYDOWN) return Key((int)wparam, lparam);
            if (message == SurfaceNative.WM_MOUSEMOVE)
            {
                MouseMove(hwnd, lparam);
                return zero;
            }
            if (message == SurfaceNative.WM_MOUSELEAVE)
            {
                tracking = false;
                if (Hover != null)
                {
                    Hover = null;
                    Invalidate();
                }
                return zero;
            }
            if (message == SurfaceNative.WM_LBUTTONDOWN)
            {
                Keyboard = false;
                Pressed = Hit(lparam);
                TitlePressed(lparam, Monotonic() * 1000.0);
                Invalidate();
                return zero;
            }
            if (message == SurfaceNative.WM_LBUTTONUP)
            {
                object target = Hit(lparam), pressed = Pressed;
                Pressed = null;
                if (target != null && Equals(target, pressed)) Activate(target);
                Invalidate();
                return zero;
            }
            if (message == SurfaceNative.WM_CONTEXTMENU)
            {
                ContextMenu(lparam);
                return zero;
            }
            if (message == SurfaceNative.WM_DPICHANGED)
            {
                int dpi = (int)(wparam & 0xFFFF);
                if (dpi != 0 && dpi != Dpi)
                {
                    Dpi = dpi;
                    Fit = null;
                    if (Visible)
                    {
                        Screen = ScreenReader(this);
                        Screen.Dpi = dpi;
                        Move(Rebuild(Now()), Origin);
                        Invalidate();
                    }
                }
                return zero;
            }
            if (message == SurfaceNative.WM_SETTINGCHANGE || message == SurfaceNative.WM_SYSCOLORCHANGE)
            {
                bool contrast = Contrast;
                string theme = Theme, design = Design;
                ReadLook();
                if (Contrast != contrast || Theme != theme || Design != design || message == SurfaceNative.WM_SYSCOLORCHANGE)
                    Invalidate();
                if (Visible) FrameTheme();
                SyncFrames();
                return null;
            }
            return null;
        }

        private bool AskStillNow()
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

        private void Paint(IntPtr hwnd)
        {
            SurfaceNative.PAINTSTRUCT paint;
            IntPtr dc = SurfaceNative.BeginPaint(hwnd, out paint);
            try
            {
                if (Card) Redraw();
                else if (dc != IntPtr.Zero && renderer != null && (Plan != null || Visible))
                {
                    SurfaceCanvas canvas = Render();
                    SurfaceCanvasBlit.ToDevice(dc, canvas);
                    PaintedPlan = Plan;
                }
            }
            finally
            {
                SurfaceNative.EndPaint(hwnd, ref paint);
            }
        }

        /// Against the layout on screen: a click queued before Windows painted a new plan was aimed at what was seen.
        private object Hit(long lparam)
        {
            SurfacePlan plan = PaintedPlan;
            if (plan == null) return null;
            int[] point = ClientPoint(lparam);
            return PopupPlace.HitTest(plan.Targets, point[0], point[1]);
        }

        private void MouseMove(IntPtr hwnd, long lparam)
        {
            object target = Hit(lparam);
            if (!Equals(target, Hover))
            {
                Hover = target;
                Invalidate();
            }
            if (!tracking) tracking = SurfaceScreen.TrackMouseLeave(hwnd);
        }

        private IntPtr? Key(int key, long lparam = 0)
        {
            if ((key == SurfaceNative.VK_SPACE || key == SurfaceNative.VK_RETURN) && (lparam & SurfaceNative.KEY_WAS_DOWN) != 0)
                return IntPtr.Zero;
            if (key == SurfaceNative.VK_ESCAPE)
            {
                Hide();
                return IntPtr.Zero;
            }
            if ((key == SurfaceNative.VK_TAB || key == SurfaceNative.VK_UP || key == SurfaceNative.VK_DOWN) && Plan != null)
            {
                bool backwards = key == SurfaceNative.VK_UP
                                 || (key == SurfaceNative.VK_TAB && SurfaceScreen.KeyState(SurfaceNative.VK_SHIFT) < 0);
                Keyboard = true;
                Focus = PopupPlace.NextFocus(PopupPlace.FocusOrder(Plan.Targets), Focus, backwards);
                Invalidate();
                Speak();
                return IntPtr.Zero;
            }
            if ((key == SurfaceNative.VK_SPACE || key == SurfaceNative.VK_RETURN) && Focus != null)
            {
                Activate(Focus);
                return IntPtr.Zero;
            }
            return null;
        }

        // ------------------------------------------------------------------- the opening (v0.6.23)
        /// _start_opening: it fades in and rises into place from SPACING xs below it; simply there while held.
        private void StartOpening()
        {
            EndOpening();
            if (Holds() || Hwnd == IntPtr.Zero || Home == null) return;
            if (Card)
            {
                Alpha = 0;
                Opening = new[] { double.NaN, Math.Max(1, SurfaceMath.Round(SpacingXs * Dpi / 96.0)) };
                Below = (int)Opening[1];
                return;
            }
            try
            {
                SurfaceScreen.SetExStyle(Hwnd, SurfaceScreen.GetExStyle(Hwnd) | (int)SurfaceNative.WS_EX_LAYERED);
                layered = true;
                if (!SurfaceScreen.SetLayeredAlpha(Hwnd, 0)) throw new InvalidOperationException("SetLayeredWindowAttributes");
            }
            catch (Exception exc)
            {
                Log("tray popup opening motion unavailable (" + TipCard.PythonName(exc) + ")");
                EndOpening();
                return;
            }
            int rise = Math.Max(1, SurfaceMath.Round(SpacingXs * Dpi / 96.0));
            Opening = new[] { double.NaN, rise };
            Stand(rise);
        }

        private void OpeningStep()
        {
            double started = Opening[0];
            int rise = (int)Opening[1];
            if (double.IsNaN(started))
            {
                started = Monotonic() * 1000.0;
                Opening = new[] { started, rise };
            }
            int[] step = PopupMotion.Opening(Monotonic() * 1000.0 - started, rise);
            if (step[2] != 0)
            {
                EndOpening();
                return;
            }
            if (Card)
            {
                Alpha = step[0];
                Below = step[1];
                return;
            }
            SurfaceScreen.SetLayeredAlpha(Hwnd, step[0]);
            Stand(step[1]);
        }

        private void EndOpening()
        {
            Opening = null;
            if (Card)
            {
                bool faded = Alpha != 255;
                Alpha = 255;
                if (Below != 0 || faded) Stand(0);
                return;
            }
            if (Below != 0) Stand(0);
            if (layered && Hwnd != IntPtr.Zero)
            {
                SurfaceScreen.SetExStyle(Hwnd, SurfaceScreen.GetExStyle(Hwnd) & ~(int)SurfaceNative.WS_EX_LAYERED);
                SurfaceScreen.InvalidateRect(Hwnd);
                SurfaceScreen.UpdateWindow(Hwnd);
            }
            layered = false;
        }

        private void Stand(int below)
        {
            Below = below;
            if (Card)
            {
                if (Home != null && Hwnd != IntPtr.Zero && Visible)
                    Layers.Stand(Hwnd, new double[] { Home[0], Home[1] + below }, Alpha);
                return;
            }
            if (Home != null && Hwnd != IntPtr.Zero)
                SurfaceScreen.SetWindowPos(Hwnd, IntPtr.Zero, Home[0], Home[1] + below, 0, 0,
                                           SurfaceNative.SWP_NOSIZE | SurfaceNative.SWP_NOZORDER | SurfaceNative.SWP_NOACTIVATE);
        }

        // ------------------------------------------------------------------- a button's face (v0.6.23)
        /// _face_glides: {target: ((fill, edge) it left from, how far on)} for the buttons part way to a new face.
        private Dictionary<object, ButtonFace> FaceGlides()
        {
            double now = Monotonic() * 1000.0;
            Dictionary<object, Face> faces = Faces;
            var states = new List<KeyValuePair<object, object[]>>();
            var known = new HashSet<object>();
            foreach (PlanItem item in Plan.Items)
                if (item.Kind == "button")
                {
                    object target = item["target"];
                    var entry = new object[] { item, PopupMotion.FaceState(item, Hover, Pressed) };
                    int at = states.FindIndex(pair => Equals(pair.Key, target));
                    if (at >= 0) states[at] = new KeyValuePair<object, object[]>(states[at].Key, entry);
                    else states.Add(new KeyValuePair<object, object[]>(target, entry));
                    known.Add(target);
                }
            Dictionary<object, string> before = Visible ? (faceStates ?? new Dictionary<object, string>()) : new Dictionary<object, string>();
            if (Visible)
            {
                faceStates = new Dictionary<object, string>();
                foreach (KeyValuePair<object, object[]> pair in states) faceStates[pair.Key] = (string)pair.Value[1];
            }
            else faceStates = null;
            var shown = new Dictionary<object, ButtonFace>();
            bool started = false;
            foreach (KeyValuePair<object, object[]> pair in states)
            {
                var item = (PlanItem)pair.Value[0];
                string now_state = (string)pair.Value[1];
                Face face;
                faces.TryGetValue(pair.Key, out face);
                string was;
                if (!before.TryGetValue(pair.Key, out was)) was = now_state;
                if (was != now_state)
                {
                    face = Holds() ? null : new Face { Started = now, From = Showing(item, was, face, now),
                                                       Length = PopupMotion.FaceLength(was, now_state) };
                    started = started || face != null;
                }
                double[] amount = face != null ? PopupMotion.FaceAmount(face.Started, face.Length, now) : new[] { 1.0, 1.0 };
                if (amount[1] != 0.0) faces.Remove(pair.Key);
                else
                {
                    faces[pair.Key] = face;
                    shown[pair.Key] = new ButtonFace(face.From[0], face.From[1], amount[0]);
                }
            }
            foreach (object gone in new List<object>(faces.Keys))
                if (!known.Contains(gone)) faces.Remove(gone);
            Faces = faces;
            if (started) SyncFrames();
            return shown;
        }

        /// _showing: the (fill, edge) a button shows this instant.
        private int[][] Showing(PlanItem item, string state, Face face, double now)
        {
            int[][] colours = renderer.FaceColours(item, state);
            if (face == null) return colours;
            double amount = PopupMotion.FaceAmount(face.Started, face.Length, now)[0];
            return new[] { PopupMotion.Mixed(face.From[0], colours[0], amount), PopupMotion.Mixed(face.From[1], colours[1], amount) };
        }

        // ---------------------------------------------------------------------- work
        /// _request_read: the core reads, once per tick, and every snapshot carries what it read; nothing is asked here.
        private void RequestRead()
        {
        }

        /// _run: one action posted to the core on a worker thread, its answer back on the UI thread as WM_POPUP_RESULT.
        internal void Run(List<object> action)
        {
            long number;
            lock (guard) number = ++sequence;
            IHostActions actions = Actions;
            string kind = action[0] as string;
            string actionName;
            Dictionary<string, object> fields = Fields(action, out actionName);
            Worker(() =>
            {
                string answer;
                try
                {
                    answer = actions == null || actionName == null
                        ? "{\"ok\": false, \"error\": \"" + (actionName == null ? "unknown_action" : "not_started") + "\"}"
                        : actions.Post(actionName, fields);
                }
                catch (Exception exc)
                {
                    answer = "{\"ok\": false, \"error\": \"" + TipCard.PythonName(exc) + "\"}";
                }
                lock (guard) results[number] = new object[] { action, answer };
                IntPtr hwnd = Hwnd;
                if (hwnd != IntPtr.Zero) SurfaceScreen.Post(hwnd, SurfaceNative.WM_POPUP_RESULT, number, 0);
            });
        }

        /// The action on the wire: `popup {call, args}` for a control call (its fields after its kind), `open_dashboard` for
        /// the Dashboard's two; null (with no name) for one that is neither, as perform answers "unknown_action".
        internal static Dictionary<string, object> Fields(List<object> action, out string name)
        {
            string kind = action.Count > 0 ? action[0] as string : null;
            string call;
            if (kind == "dashboard")
            {
                name = HostActions.OpenDashboard;
                return new Dictionary<string, object> { { "page", "pending" }, { "row", null } };
            }
            if (kind == "dashboard_row" && action.Count == 4 && Array.IndexOf(RowDialogs, action[1] as string) >= 0)
            {
                name = HostActions.OpenDashboard;
                return new Dictionary<string, object> { { "page", "pending" },
                                                        { "row", new List<object> { action[1], action[2], action[3] } } };
            }
            if (kind != null && Calls.TryGetValue(kind, out call) && call != null)
            {
                name = HostActions.Popup;
                return new Dictionary<string, object> { { "call", call }, { "args", action.GetRange(1, action.Count - 1) } };
            }
            name = null;
            return null;
        }

        /// _finished: an action's answer is back. Until the snapshot after it the window shows it as under way, as the
        /// reference's model does until its outcome; a refusal or failure is logged as the reference logs it.
        private void Finished(long number)
        {
            object[] result;
            lock (guard)
            {
                if (!results.TryGetValue(number, out result)) return;
                results.Remove(number);
            }
            var action = (List<object>)result[0];
            var answer = Json.Parse((string)result[1]) as Dictionary<string, object>;
            if (answer != null && Equals(SurfaceRender.Field(answer, "ok"), false))
                Log("tray popup " + action[0] + " failed (" + PopupWords.Str(SurfaceRender.Field(answer, "error")) + ")");
            List<object> key = BusyKey(action);
            if (key != null && Contains(begun, key) && !Contains(answered, key)) answered.Add(key);
            if (Visible) Update();
        }
    }

    /// A canvas drawn onto a window's device context, as WM_PAINT does it for the plain window (SetDIBitsToDevice, with the
    /// canvas's own top-down header).
    internal static class SurfaceCanvasBlit
    {
        [System.Runtime.InteropServices.DllImport("gdi32.dll")]
        private static extern int SetDIBitsToDevice(IntPtr dc, int x, int y, uint width, uint height, int sx, int sy, uint start,
                                                    uint lines, IntPtr bits, ref SurfaceNative.BITMAPINFO info, uint usage);

        internal static void ToDevice(IntPtr dc, SurfaceCanvas canvas)
        {
            SurfaceNative.BITMAPINFO info = SurfaceNative.BitmapInfo(canvas.Width, canvas.Height);
            SetDIBitsToDevice(dc, 0, 0, (uint)canvas.Width, (uint)canvas.Height, 0, 0, 0, (uint)canvas.Height, canvas.Bits, ref info, 0);
        }
    }
}

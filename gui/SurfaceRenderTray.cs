// Codex Auto Resume - the probe mode's case for the notification-area icon (v0.6.27, S6.3e).
//
// `tray_icon`: a TrayIcon over a window made and never shown (SurfaceScreen.Probe set: no icon reaches the notification
// area, no menu is tracked, no session is watched), its popup, tip, drawn menu and cards stood in by recorders, driven by
// the script tests/test_surface_windows.py drives the reference's Tray with; after each step the icon's state, the calls,
// what the stand-ins were asked, what was posted to the core and the log.
using System;
using System.Collections.Generic;
using System.IO;

namespace CodexAutoResume
{
    internal static partial class SurfaceRender
    {
        private sealed class TrayProbeActions : IHostActions
        {
            internal readonly List<object> Posts = new List<object>();

            public string Post(string action, IDictionary<string, object> fields)
            {
                Posts.Add(new List<object> { action, new Dictionary<string, object>(fields) });
                return "{\"ok\": true}";
            }
        }

        private sealed class ProbePopup : ITrayPopup
        {
            internal List<object> Asked;
            internal bool[] State = new bool[3];
            public bool Visible { get { return State[0]; } }
            public bool Attention() { return State[1]; }
            public void OnSelect(bool keyboard)
            {
                Asked.Add(new List<object> { "popup.on_select", keyboard });
                if (State[2]) throw new InvalidOperationException("broken");
            }
            public void OnDoubleClick() { Asked.Add(new List<object> { "popup.on_double_click" }); }
            public void Show() { Asked.Add(new List<object> { "popup.show" }); }
            public void Hide() { Asked.Add(new List<object> { "popup.hide" }); }
            public void Destroy() { Asked.Add(new List<object> { "popup.destroy" }); }
            public void SetStrings(Dictionary<string, object> strings, string locale, string letters)
            {
                Asked.Add(new List<object> { "popup.set_strings", locale });
            }
            public void Snapshot(Dictionary<string, object> popup) { }
            public void FollowSettings(Dictionary<string, object> values) { }
        }

        private sealed class ProbeTip : ITrayTip
        {
            internal List<object> Asked;
            public void Show(Func<int[]> icon, int[] point)
            {
                int[] rect = icon();
                Asked.Add(new List<object> { "tip.show", new List<object> { point[0], point[1] }, rect });
            }
            public void Hide(bool atOnce) { Asked.Add(new List<object> { "tip.hide", atOnce }); }
            public void Destroy() { Asked.Add(new List<object> { "tip.destroy" }); }
        }

        private sealed class TrayProbeMenu : ITrayMenu
        {
            internal List<object> Asked;
            internal bool Answer = true;
            internal Action<object> Chosen;
            public bool Visible { get { return false; } }
            public bool Open(List<object> items, Dictionary<string, object> strings, string locale, string letters, Action<object> chosen)
            {
                Asked.Add(new List<object> { "menu.open", items, locale });
                Chosen = chosen;
                return Answer;
            }
            public void Destroy() { Asked.Add(new List<object> { "menu.destroy" }); }
        }

        private sealed class ProbeCards : ITrayCards
        {
            internal List<object> Asked;
            public void Show(Dictionary<string, object> notice) { }
            public void Destroy() { Asked.Add(new List<object> { "cards.destroy" }); }
        }

        private static object TrayIconCase(Dictionary<string, object> task)
        {
            var calls = new List<string>();
            var asked = new List<object>();
            var logged = new List<object>();
            var actions = new TrayProbeActions();
            var work = new List<Action>();
            double clock = (double)task["clock"], now = (double)task["now"];
            var rect = new int[][] { new[] { 1880, 1040, 1904, 1064 } };
            bool contrast = false, reduced = false, battery = false, overflowed = false, demo = false;
            bool unseen = false, unconfirmed = false;
            object armed = null;
            var refuse = new HashSet<int>();
            foreach (object value in (List<object>)task["refuse"]) refuse.Add((int)(double)value);
            int small = (int)(double)task["small"];
            bool prefer = (bool)task["prefer"];
            string theme = (string)task["theme"];
            var popup = new ProbePopup { Asked = asked };
            var menu = new TrayProbeMenu { Asked = asked };
            var steps = new List<object>();
            var known = new Dictionary<long, string>();
            SurfaceScreen.Probe = calls;
            SurfaceScreen.Posted.Clear();
            SurfaceScreen.Foreground = IntPtr.Zero;
            SurfaceScreen.Grant = true;
            SurfaceTheme.SetTheme(theme);
            IntPtr window = IntPtr.Zero;
            var tray = new TrayIcon
            {
                IconPath = (string)task["icon"], Days = true, Edition = (string)task["edition"], DemoName = "demo-state",
                Strings = (Dictionary<string, object>)task["strings"], Locale = (string)task["locale"],
                Letters = Field(task, "letters") as string ?? "", Inbox = (bool)task["inbox"], Actions = actions,
            };
            try
            {
                tray.OnDemo = () => asked.Add(new List<object> { "demo.shown" });
                tray.DemoTaken = () =>
                {
                    bool taken = demo;
                    demo = false;
                    return taken;
                };
                tray.Log = line => logged.Add(line);
                tray.Worker = job => work.Add(job);
                tray.Ended = () => calls.Add("PostQuitMessage 0");
                tray.Monotonic = () => clock;
                tray.Now = () => now;
                tray.PerfCounter = () => 0.0;
                tray.Epoch = tray.StateSince = clock;
                tray.FailureUnseen = unused => unseen;
                tray.UnconfirmedUnseen = unused => unconfirmed;
                tray.PowerArmed = () => TrayIcon.PowerWord(armed);
                tray.IconRectReader = () => rect[0] == null ? null : (int[])rect[0].Clone();
                tray.Cursor = () => new[] { 1890, 1050 };
                tray.AskContrast = () => contrast;
                tray.AskReduced = () => reduced;
                tray.AskBatterySaver = () => battery;
                tray.AskPlacement = () => overflowed;
                tray.AskOverflowOpen = () => false;
                tray.AskAppsLight = () => theme == "light";
                tray.PreferAppModeCall = unused => prefer;
                tray.Metric = unused => small;
                tray.ShellAnswer = action => !refuse.Contains(action);
                tray.MakePopup = () =>
                {
                    asked.Add(new List<object> { "popup.make" });
                    return popup;
                };
                tray.MakeTip = () =>
                {
                    asked.Add(new List<object> { "tip.make" });
                    return new ProbeTip { Asked = asked };
                };
                tray.MakeMenu = () =>
                {
                    if ((bool)task["broken_menu"]) throw new InvalidOperationException("no menu");
                    asked.Add(new List<object> { "menu.make" });
                    return menu;
                };
                tray.MakeCards = () =>
                {
                    asked.Add(new List<object> { "cards.create" });
                    return new ProbeCards { Asked = asked };
                };
                SurfaceScreen.Name = hwnd =>
                {
                    if (tray.Hwnd != IntPtr.Zero) known[tray.Hwnd.ToInt64()] = "tray";
                    string name;
                    return known.TryGetValue(hwnd.ToInt64(), out name) ? name : "0x" + hwnd.ToInt64().ToString("x");
                };
                foreach (object entry in (List<object>)task["script"])
                {
                    var described_ = (Dictionary<string, object>)entry;
                    string op = (string)described_["op"];
                    var step = (List<object>)described_["do"];
                    calls.Clear();
                    asked.Clear();
                    logged.Clear();
                    actions.Posts.Clear();
                    IntPtr hwnd = tray.Hwnd != IntPtr.Zero ? tray.Hwnd : window;
                    if (op == "create")
                    {
                        tray.Create();
                        window = tray.Hwnd;
                    }
                    else if (op == "update")
                    {
                        tray.Update((Dictionary<string, object>)step[1]);
                        unseen = (bool)step[2];
                        unconfirmed = (bool)step[3];
                        armed = step[4];
                    }
                    else if (op == "clock")
                    {
                        clock += (double)step[1];
                        now += (double)step[1];
                    }
                    else if (op == "timer") tray.Message(hwnd, TrayIcon.WM_TIMER, (long)(double)step[1], 0);
                    else if (op == "work")
                    {
                        List<Action> jobs = new List<Action>(work);
                        work.Clear();
                        foreach (Action job in jobs) job();
                    }
                    else if (op == "posted")
                    {
                        var posted = new List<long[]>(SurfaceScreen.Posted);
                        SurfaceScreen.Posted.Clear();
                        foreach (long[] message in posted) tray.Message(hwnd, (int)message[1], message[2], message[3]);
                    }
                    else if (op == "callback") tray.Message(hwnd, TrayIcon.CALLBACK, (long)(double)step[1], (long)(double)step[2]);
                    else if (op == "session") tray.Message(hwnd, TrayIcon.WM_WTSSESSION_CHANGE, (long)(double)step[1], 0);
                    else if (op == "taskbar") tray.Message(hwnd, (int)tray.TaskbarCreated, 0, 0);
                    else if (op == "message") tray.Message(hwnd, (int)(double)step[1], 0, 0);
                    else if (op == "popup")
                        popup.State = new[] { (bool)step[1], (bool)step[2], (bool)step[3] };
                    else if (op == "drawn") menu.Answer = (bool)step[1];
                    else if (op == "native") tray.NativeChoice = (int)(double)step[1];
                    else if (op == "choose") menu.Chosen(step[1]);
                    else if (op == "look")
                    {
                        contrast = (bool)step[1];
                        reduced = (bool)step[2];
                        battery = (bool)step[3];
                        overflowed = (bool)step[4];
                        rect[0] = step[5] == null ? null : Ints(step[5]);
                    }
                    else if (op == "demo") demo = (bool)step[1];
                    else if (op == "strings") tray.SetStrings((Dictionary<string, object>)step[1], (string)step[2], (string)step[3]);
                    FlushPosts(work);
                    steps.Add(new Dictionary<string, object>
                    {
                        { "op", op }, { "state", TrayState(tray) }, { "calls", new List<string>(calls) },
                        { "asked", new List<object>(asked) }, { "posts", new List<object>(actions.Posts) },
                        { "log", new List<object>(logged) },
                    });
                }
            }
            finally
            {
                SurfaceScreen.Probe = null;
                SurfaceScreen.Posted.Clear();
                SurfaceScreen.Foreground = IntPtr.Zero;
                SurfaceTheme.SetTheme("system");
                if (window != IntPtr.Zero) SurfaceNative.DestroyWindow(window);
                tray.Unregister();
            }
            return new Dictionary<string, object> { { "steps", steps } };
        }

        /// The probe for the surfaces' class (ISurfaces): HostSurfaces started from a `surfaces` event, ticked, told a new
        /// language and closed, its icon over a window never shown; the calls and what was posted to the core.
        private static object HostSurfacesCase(Dictionary<string, object> task)
        {
            var calls = new List<string>();
            var actions = new TrayProbeActions();
            var record = new List<object>();
            SurfaceScreen.Probe = calls;
            SurfaceScreen.Posted.Clear();
            double now = (double)task["now"];
            IntPtr window = IntPtr.Zero;
            TrayIcon made = null;
            var surfaces = new HostSurfaces { Worker = job => job() };
            surfaces.MakeTray = () =>
            {
                made = new TrayIcon
                {
                    Now = () => now, Monotonic = () => 5000.0, PerfCounter = () => 0.0, Metric = unused => 16,
                    IconRectReader = () => new[] { 1880, 1040, 1904, 1064 }, AskContrast = () => false, AskReduced = () => false,
                    AskBatterySaver = () => false, AskPlacement = () => false, AskOverflowOpen = () => false,
                    MakeCards = () => new ProbeCards { Asked = new List<object>() },
                };
                made.Epoch = made.StateSince = 5000.0;
                return made;
            };
            SurfaceScreen.Name = hwnd => made != null && hwnd == window ? "tray" : "0x" + hwnd.ToInt64().ToString("x");
            try
            {
                foreach (object entry in (List<object>)task["script"])
                {
                    var step = (List<object>)entry;
                    string op = (string)step[0];
                    calls.Clear();
                    actions.Posts.Clear();
                    if (op == "start")
                    {
                        var shown = (Dictionary<string, object>)step[1];
                        surfaces.Start(new SurfacesEvent
                        {
                            Icon = (string)shown["icon"], Strings = (Dictionary<string, object>)shown["strings"],
                            Settings = shown["settings"] as Dictionary<string, object>, Edition = (string)shown["edition"],
                            Demo = (string)shown["demo"], Locale = (string)shown["locale"], Letters = (string)shown["letters"],
                            Actions = actions,
                        });
                        if (made != null) window = made.Hwnd;
                    }
                    else if (op == "snapshot")
                        surfaces.Snapshot(new SnapshotEvent { Snapshot = (Dictionary<string, object>)step[1], Popup = null });
                    else if (op == "strings")
                        surfaces.Strings(new StringsEvent { Strings = (Dictionary<string, object>)step[1], Locale = (string)step[2],
                                                            Letters = (string)step[3] });
                    else if (op == "tick") made.Message(window, TrayIcon.WM_TIMER, TrayIcon.TIMER_TICK, 0);
                    else if (op == "close") surfaces.Close();
                    else if (op == "posted")
                    {
                        var posted = new List<long[]>(SurfaceScreen.Posted);
                        SurfaceScreen.Posted.Clear();
                        foreach (long[] message in posted)
                            if (message[1] == TrayIcon.WM_CLOSE)
                            {
                                made.Message(window, TrayIcon.WM_CLOSE, 0, 0);
                                made.Message(window, TrayIcon.WM_DESTROY, 0, 0);   // what DestroyWindow sends
                            }
                    }
                    record.Add(new Dictionary<string, object> { { "op", op }, { "calls", calls.FindAll(call => call.StartsWith("Shell_NotifyIconW")) },
                                                                { "posts", new List<object>(actions.Posts) } });
                }
            }
            finally
            {
                SurfaceScreen.Probe = null;
                SurfaceScreen.Posted.Clear();
                if (window != IntPtr.Zero) SurfaceNative.DestroyWindow(window);
                if (made != null) made.Unregister();
                SurfaceTheme.SetTheme("system");
                SurfaceTheme.SetDesign(null);
                SurfaceTheme.SetReduceMotion(false);
            }
            return new Dictionary<string, object> { { "steps", record } };
        }

        /// The posts a step queued run within it, as the reference's callbacks ran at once; the frame table's building
        /// stays queued for the script's "work".
        private static void FlushPosts(List<Action> work)
        {
            for (int index = 0; index < work.Count; )
            {
                Action job = work[index];
                if (TrayIcon.IsPost(job))
                {
                    work.RemoveAt(index);
                    job();
                }
                else index++;
            }
        }

        private static Dictionary<string, object> TrayState(TrayIcon tray)
        {
            return new Dictionary<string, object>
            {
                { "version4", tray.Version4 }, { "failed", tray.Failed }, { "unconfirmed", tray.Unconfirmed },
                { "icon_state", tray.IconState }, { "motion_allowed", tray.MotionAllowed },
                { "motion_ms", tray.MotionMs.HasValue ? (object)tray.MotionMs.Value : null }, { "frame_key", tray.FrameKey },
                { "shown", tray.ShownName }, { "last_tip", tray.LastTip }, { "tip_heard", tray.TipHeard },
                { "tip_moves", tray.TipMoves }, { "tip_silent", tray.TipSilent }, { "tip_fallback", tray.TipFallback },
                { "tip", tray.TipBroken ? (object)"broken" : tray.Tip != null }, { "locked", tray.SessionLocked },
                { "away", tray.SessionAway }, { "menu_mode", tray.MenuMode }, { "menu_theming", tray.MenuTheming },
                { "popup_failed", tray.PopupFailed }, { "popup", tray.Popup != null },
                { "menu", tray.MenuBroken ? (object)"broken" : tray.MenuDrawn != null },
                { "frames", tray.FramesBroken ? (object)false : (tray.Frames != null ? (object)tray.Frames.Size : null) },
            };
        }
    }
}

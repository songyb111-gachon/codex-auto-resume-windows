// The host's event pump and the window that receives it (v0.6.27, P6-DESIGN 1.4, 1.5; seat S6.2b).
//
// HostPump: an MTA background thread loops on car_next_event(250). Each event goes into a ConcurrentQueue and one
// PostMessage(hwnd, WM_APP + 1) is posted - the shape the reference's Inbox.wake has. The pump never touches a window
// and never calls the surfaces; a reply that is not an object with a "kind" is a failed pull and is skipped. After
// "ended" it stops pulling.
//
// HostWindow: a message-only window (parent HWND_MESSAGE: never on screen, never in the taskbar or Alt+Tab) owned by
// the UI thread. Its procedure drains the queue and hands each event to the surfaces on that thread: "surfaces" ->
// Start (with the actions' way back), "snapshot", "strings", "settings", "notice", "demo", "close"; "ended" ends the
// message loop with the event's exit_code. Its procedure delegate is held in a field for the window's whole life.
//
// HostActions: IHostActions over car_post_action - the surfaces post from worker threads, never the UI thread.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;

namespace CodexAutoResume
{
    internal sealed class HostPump
    {
        internal const uint WM_HOST_EVENT = 0x8000 + 1; // WM_APP + 1
        internal const uint PullMs = 250;

        [DllImport("user32.dll", SetLastError = true, ExactSpelling = true)]
        private static extern bool PostMessageW(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

        private readonly ConcurrentQueue<Dictionary<string, object>> queue = new ConcurrentQueue<Dictionary<string, object>>();
        private readonly IntPtr hwnd;
        private Thread thread;
        private volatile bool ended;

        internal HostPump(IntPtr hwnd)
        {
            this.hwnd = hwnd;
        }

        /// How many replies were not events (failed pulls), for the soak's count.
        internal int FailedPulls { get; private set; }

        internal void Start()
        {
            thread = new Thread(Run) { IsBackground = true, Name = "car-pump" };
            thread.SetApartmentState(ApartmentState.MTA);
            thread.Start();
        }

        private void Run()
        {
            while (!ended)
            {
                Dictionary<string, object> found;
                try
                {
                    string reply = HostCore.NextEvent(PullMs);
                    if (reply == null) continue;
                    found = Json.Parse(reply) as Dictionary<string, object>;
                }
                catch (Exception)
                {
                    found = null;
                }
                string kind = found == null ? null : Text(found, "kind");
                if (kind == null)
                {
                    FailedPulls++;
                    continue;
                }
                if (kind == HostEvents.Ended) ended = true;
                queue.Enqueue(found);
                PostMessageW(hwnd, WM_HOST_EVENT, IntPtr.Zero, IntPtr.Zero);
            }
        }

        internal bool TryTake(out Dictionary<string, object> found)
        {
            return queue.TryDequeue(out found);
        }

        internal static string Text(Dictionary<string, object> map, string key)
        {
            object value;
            return map.TryGetValue(key, out value) ? value as string : null;
        }

        internal static Dictionary<string, object> Object(Dictionary<string, object> map, string key)
        {
            object value;
            return map.TryGetValue(key, out value) ? value as Dictionary<string, object> : null;
        }

        /// One event handed to the surfaces, on the UI thread; the exit code where it was "ended", else null.
        internal static int? Deliver(Dictionary<string, object> found, ISurfaces surfaces, IHostActions actions)
        {
            // An if chain, not a string switch: a switch of this many strings makes the compiler name a class at random,
            // which the reproducible build refuses (build/normalize_pe.py).
            string kind = Text(found, "kind");
            if (kind == HostEvents.Surfaces)
            {
                surfaces.Start(new SurfacesEvent
                {
                    Icon = Text(found, "icon"),
                    Strings = Object(found, "strings"),
                    Settings = Object(found, "settings"),
                    Edition = Text(found, "edition"),
                    Demo = Text(found, "demo"),
                    Locale = Text(found, "locale"),
                    Letters = Text(found, "letters"),
                    Actions = actions,
                });
            }
            else if (kind == HostEvents.Snapshot)
            {
                surfaces.Snapshot(new SnapshotEvent { Snapshot = Object(found, "snapshot"), Popup = Object(found, "popup") });
            }
            else if (kind == HostEvents.Strings)
            {
                surfaces.Strings(new StringsEvent
                {
                    Strings = Object(found, "strings"),
                    Locale = Text(found, "locale"),
                    Letters = Text(found, "letters"),
                });
            }
            else if (kind == HostEvents.Settings)
            {
                surfaces.Settings(Object(found, "settings"));
            }
            else if (kind == HostEvents.Notice)
            {
                surfaces.Notice(Object(found, "notice"));
            }
            else if (kind == HostEvents.Demo)
            {
                surfaces.Demo(Object(found, "notice"));
            }
            else if (kind == HostEvents.Close)
            {
                surfaces.Close();
            }
            else if (kind == HostEvents.Ended)
            {
                object code;
                found.TryGetValue("exit_code", out code);
                return code is double ? (int)(double)code : HostMain.ExitError;
            }
            return null;
        }
    }

    /// The surfaces' way back: one closed action through car_post_action (HostCore), answered with its reply.
    internal sealed class HostActionsPost : IHostActions
    {
        public string Post(string action, IDictionary<string, object> fields)
        {
            var request = new Dictionary<string, object>();
            request["action"] = action;
            if (fields != null)
            {
                foreach (KeyValuePair<string, object> field in fields)
                {
                    if (field.Key != "action") request[field.Key] = field.Value;
                }
            }
            return HostCore.PostAction(Json.Write(request));
        }
    }

    /// The UI thread's message-only window and the message loop.
    internal sealed class HostWindow
    {
        private delegate IntPtr WndProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct WNDCLASSEXW
        {
            public uint cbSize;
            public uint style;
            public IntPtr lpfnWndProc;
            public int cbClsExtra;
            public int cbWndExtra;
            public IntPtr hInstance;
            public IntPtr hIcon;
            public IntPtr hCursor;
            public IntPtr hbrBackground;
            public string lpszMenuName;
            public string lpszClassName;
            public IntPtr hIconSm;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct MSG
        {
            public IntPtr hwnd;
            public uint message;
            public IntPtr wParam;
            public IntPtr lParam;
            public uint time;
            public int x;
            public int y;
        }

        private static readonly IntPtr HWND_MESSAGE = new IntPtr(-3);
        private const string ClassName = "CodexAutoResume.HostPump";

        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode, ExactSpelling = true)]
        private static extern ushort RegisterClassExW(ref WNDCLASSEXW windowClass);

        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode, ExactSpelling = true)]
        private static extern IntPtr CreateWindowExW(uint exStyle, string className, string windowName, uint style, int x,
                                                     int y, int width, int height, IntPtr parent, IntPtr menu,
                                                     IntPtr instance, IntPtr param);

        [DllImport("user32.dll", ExactSpelling = true)]
        private static extern IntPtr DefWindowProcW(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll", ExactSpelling = true)]
        private static extern int GetMessageW(out MSG msg, IntPtr hwnd, uint min, uint max);

        [DllImport("user32.dll", ExactSpelling = true)]
        private static extern bool TranslateMessage(ref MSG msg);

        [DllImport("user32.dll", ExactSpelling = true)]
        private static extern IntPtr DispatchMessageW(ref MSG msg);

        [DllImport("user32.dll", ExactSpelling = true)]
        private static extern void PostQuitMessage(int exitCode);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
        private static extern IntPtr GetModuleHandleW(string name);

        private readonly WndProc procedure;
        private readonly HostActionsPost actions = new HostActionsPost();

        internal HostWindow()
        {
            procedure = Procedure;
            var windowClass = new WNDCLASSEXW
            {
                cbSize = (uint)Marshal.SizeOf(typeof(WNDCLASSEXW)),
                lpfnWndProc = Marshal.GetFunctionPointerForDelegate(procedure),
                hInstance = GetModuleHandleW(null),
                lpszClassName = ClassName,
            };
            RegisterClassExW(ref windowClass);
            Handle = CreateWindowExW(0, ClassName, null, 0, 0, 0, 0, 0, HWND_MESSAGE, IntPtr.Zero,
                                     windowClass.hInstance, IntPtr.Zero);
            if (Handle == IntPtr.Zero) throw new InvalidOperationException("no message window: " + Marshal.GetLastWin32Error());
        }

        internal IntPtr Handle { get; private set; }
        internal HostPump Pump { get; set; }
        internal ISurfaces Surfaces { get; set; }
        internal Action<int> Ended { get; set; }

        private IntPtr Procedure(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam)
        {
            if (message != HostPump.WM_HOST_EVENT || Pump == null) return DefWindowProcW(hwnd, message, wParam, lParam);
            Dictionary<string, object> found;
            while (Pump.TryTake(out found))
            {
                int? code;
                try
                {
                    code = HostPump.Deliver(found, Surfaces, actions);
                }
                catch (Exception)
                {
                    // A surface that breaks costs that surface only (the reference's `_popup_broke`): the watcher runs on.
                    code = null;
                }
                if (code.HasValue)
                {
                    if (Ended != null) Ended(code.Value);
                    PostQuitMessage(0);
                }
            }
            return IntPtr.Zero;
        }

        /// The thread's message loop until WM_QUIT.
        internal static void Loop()
        {
            MSG msg;
            while (GetMessageW(out msg, IntPtr.Zero, 0, 0) > 0)
            {
                TranslateMessage(ref msg);
                DispatchMessageW(ref msg);
            }
        }
    }
}

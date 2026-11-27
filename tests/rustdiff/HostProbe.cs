// The test-side entry of the C# host's surfaces (S6.4): compiled with gui/host.sources' [contract], [surface] and [generated]
// files by tests/rustdiff/surfacehost.py, never part of the product. Where CODEX_AR_HOST_CALL names a call, it answers the
// call's one question of the surfaces' own code and writes the answer to CODEX_AR_HOST_OUT; with none it is the render mode
// (SurfaceRender.Run), as build/surface_render.py's driver is. It makes no window and loads no DLL.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace CodexAutoResume
{
    internal static class HostProbeDriver
    {
        private static int Main(string[] args)
        {
            if (Environment.GetEnvironmentVariable("CODEX_AR_HOST_SERVE") == "1") return Serve();
            string callFile = Environment.GetEnvironmentVariable("CODEX_AR_HOST_CALL");
            if (string.IsNullOrEmpty(callFile)) return SurfaceRender.Run() ?? 2;
            string answer;
            try
            {
                var call = (Dictionary<string, object>)Json.Parse(File.ReadAllText(callFile, Encoding.UTF8));
                answer = Json.Write(new Dictionary<string, object> { { "ok", Answer((string)call["call"], call) } });
            }
            catch (Exception exc)
            {
                answer = Json.Write(new Dictionary<string, object> { { "error", exc.GetType().Name + ": " + exc.Message } });
            }
            File.WriteAllText(Environment.GetEnvironmentVariable("CODEX_AR_HOST_OUT"), answer, new UTF8Encoding(false));
            return 0;
        }

        /// One call per line on standard input, one answer per line on standard output, until the input ends: the same
        /// questions, asked of one process (a test asks hundreds).
        private static int Serve()
        {
            var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
            var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { NewLine = "\n", AutoFlush = true };
            string line;
            while ((line = input.ReadLine()) != null)
            {
                string answer;
                try
                {
                    var call = (Dictionary<string, object>)Json.Parse(line);
                    answer = Json.Write(new Dictionary<string, object> { { "ok", Answer((string)call["call"], call) } });
                }
                catch (Exception exc)
                {
                    answer = Json.Write(new Dictionary<string, object> { { "error", exc.GetType().Name + ": " + exc.Message } });
                }
                output.WriteLine(answer);
            }
            return 0;
        }

        /// The render mode's `tray_words` case (gui/SurfaceRenderWindows.cs TrayWordsCase), asked of TrayWords alone: the icon's
        /// words from a snapshot, and what a failed cast says.
        private static object TrayWords_(Dictionary<string, object> call)
        {
            var snapshot = SurfaceRender.Field(call, "snapshot") as Dictionary<string, object>;
            var strings = (Dictionary<string, object>)call["strings"];
            double now = (double)call["now"];
            string edition = SurfaceRender.Field(call, "edition") as string;
            try
            {
                TrayWords.Parts parts = TrayWords.TooltipParts(snapshot, strings, now, edition);
                return new Dictionary<string, object>
                {
                    { "parts", parts.ToJson() }, { "tooltip", TrayWords.Tooltip(snapshot, strings, now, edition) },
                    { "joined", TrayWords.Joined(parts) }, { "meter_line", TrayWords.MeterLine(snapshot, strings) },
                };
            }
            catch (Exception exc)
            {
                return new Dictionary<string, object> { { "raised", exc is InvalidCastException ? "AttributeError" : exc.GetType().Name } };
            }
        }

        /// A value as Json.Write takes it: numbers as doubles, whatever their C# type.
        private static object Plain(object value)
        {
            if (value is int || value is long || value is uint || value is short || value is byte) return Convert.ToDouble(value);
            var map = value as Dictionary<string, object>;
            if (map != null)
            {
                var copy = new Dictionary<string, object>();
                foreach (KeyValuePair<string, object> pair in map) copy[pair.Key] = Plain(pair.Value);
                return copy;
            }
            var list = value as List<object>;
            if (list != null) return list.ConvertAll(Plain);
            var numbers = value as int[];
            if (numbers != null) return new List<object>(Array.ConvertAll(numbers, number => (object)(double)number));
            return value;
        }

        /// One question by its name. An if-chain, not a string switch: a switch of six or more strings compiles to a hash
        /// table the build cannot make the same twice (S6.3d takes them out of the host; the probe is kept the same way).
        private static object Answer(string name, Dictionary<string, object> call)
        {
            if (name == "tray_words") return TrayWords_(call);
            if (name == "icon_state")
                // tray.icon_state: a failure reported is "failed"; else the popup's word for the snapshot, as the icon's state
                return call["failed"] is bool && (bool)call["failed"] ? "failed"
                    : TrayMotion.ForLight(TipCard.SnapshotActivity(SurfaceRender.Field(call, "snapshot") as Dictionary<string, object>,
                                                                    (double)call["now"], call["attention"] is bool && (bool)call["attention"]));
            if (name == "menu_items")
                return Plain(TrayIcon.MenuItems(SurfaceRender.Field(call, "snapshot") as Dictionary<string, object>,
                                                SurfaceRender.Field(call, "strings") as Dictionary<string, object>,
                                                (double)call["now"], call["pending"] is bool && (bool)call["pending"],
                                                call["armed"] as string, call["popup"] is bool && (bool)call["popup"]));
            if (name == "tray_joined") return TrayWords.Joined(PartsOf((Dictionary<string, object>)call["parts"]));
            if (name == "placement") return Placement(call);
            if (name == "overflow")
                return TrayPlace.OverflowOpen(new FakeWindows
                {
                    Windows = (List<object>)call["windows"], Fail = call["fail"] is bool && (bool)call["fail"],
                });
            if (name == "card_layers") return CardLayers(call);
            if (name == "icon_tick") return IconTick(call);
            if (name == "icon_overflowed") return IconOverflowed(call);
            if (name == "icon_demo") return IconDemo(call);
            if (name == "icon_steps") return IconSteps(call);
            if (name == "menu_keys") return MenuKeys(call);
            if (name == "menu_messages") return MenuMessages(call);
            if (name == "popup_steps") return PopupSteps(call);
            if (name == "row_menu_class") return RowMenuClass(call);
            if (name == "menu_arrow") return MenuArrow(call);
            if (name == "tip_steps") return TipSteps(call);
            if (name == "tip_access") return TipAccess(call);
            if (name == "menu_numbered")
            {
                var actions = new Dictionary<int, object>();
                List<object> numbered = MenuPlan.Numbered((List<object>)call["entries"], actions);
                var pairs = new List<object>();
                foreach (KeyValuePair<int, object> pair in actions) pairs.Add(new List<object> { (double)pair.Key, Plain(pair.Value) });
                return new Dictionary<string, object> { { "numbered", Plain(numbered) }, { "actions", pairs } };
            }
            if (name == "icon_menu_ids")
                return new Dictionary<string, object>
                {
                    { "MENU_STATUS", (double)TrayIcon.MenuStatus }, { "MENU_OPEN", (double)TrayIcon.MenuOpen },
                    { "MENU_TOGGLE", (double)TrayIcon.MenuToggle }, { "MENU_STOP", (double)TrayIcon.MenuStop },
                    { "MENU_PENDING", (double)TrayIcon.MenuPending }, { "MENU_POWER_OFF", (double)TrayIcon.MenuPowerOff },
                    { "MENU_POPUP", (double)TrayIcon.MenuPopup },
                };
            throw new ArgumentException("no call " + name);
        }

        /// The core's side of IHostActions as a test sees it: every action posted, in order, with its fields; the ones whose
        /// index is in `raises` throw, as a callback of the reference's that raised would (the icon logs it and goes on).
        private sealed class RecordingActions : IHostActions
        {
            internal readonly List<object> Posted = new List<object>();
            internal List<object> Raises = new List<object>();

            public string Post(string action, IDictionary<string, object> fields)
            {
                int index = Posted.Count;
                Posted.Add(new List<object> { action, Plain(new Dictionary<string, object>(fields)) });
                if (Raises.Contains((double)index)) throw new InvalidOperationException("the callback raised");
                return null;
            }
        }

        /// The popup the icon makes for a click, standing in for the test's own (its `_popup_for_click`): each call recorded.
        private sealed class RecordingPopup : ITrayPopup
        {
            internal readonly List<object> Calls = new List<object>();
            public bool Visible { get { return false; } }
            public bool Attention() { Calls.Add("attention"); return false; }
            public void OnSelect(bool keyboard) { Calls.Add(keyboard ? "on_select keyboard" : "on_select"); }
            public void OnDoubleClick() { Calls.Add("on_double_click"); }
            public void Show() { Calls.Add("show"); }
            public void Hide() { Calls.Add("hide"); }
            public void Destroy() { Calls.Add("destroy"); }
            public void SetStrings(Dictionary<string, object> strings, string locale, string letters) { Calls.Add("set_strings"); }
            public void Snapshot(Dictionary<string, object> popup) { Calls.Add("snapshot"); }
            public void FollowSettings(Dictionary<string, object> values) { Calls.Add("follow_settings"); }
        }

        /// The drawn menu as the icon opens it, standing in for the test's own (its `_menu_drawn`, or what popup.Menu makes):
        /// each opening recorded with the items and words it was handed, answered in order (true: shown, false: Windows
        /// refused it the foreground, "raise": it broke); an opening past the answers is reported unanswered and refused, so
        /// the test's object can be asked and the run made again. The chooser of the last opening is kept for `choose`.
        private sealed class RecordingMenu : ITrayMenu
        {
            internal Queue<object> Answers;
            internal readonly List<object> Opens = new List<object>();
            internal bool Unanswered;
            internal int Destroyed;
            internal Action<object> Chosen;
            public bool Visible { get { return false; } }

            public bool Open(List<object> items, Dictionary<string, object> strings, string locale, string letters, Action<object> chosen)
            {
                Opens.Add(new List<object> { Plain(items), new Dictionary<string, object>(strings) });
                Chosen = chosen;
                if (Answers.Count == 0)
                {
                    Unanswered = true;
                    return false;
                }
                object answer = Answers.Dequeue();
                if (answer is string) throw new InvalidOperationException("UpdateLayeredWindow");
                return (bool)answer;
            }

            public void Destroy() { Destroyed++; }
        }

        /// The popup's row menu as the popup opens it, standing in for the test's own (what its make_menu makes, or the
        /// `_row_menu` it set): each opening recorded - its entries, point, owner and the click-away it was handed - and
        /// answered in order (true: shown, false: refused the foreground, "raise": it broke); an opening past the answers
        /// is reported unanswered and refused, so the test's object can be asked and the run made again. Its chooser and
        /// click-away are kept for later steps; its Close and Destroy counted. Its window is the test's object's (`Handle`).
        private sealed class RecordingRowMenu : IRowMenu
        {
            internal IntPtr Handle;
            internal PopupWindow Popup;
            internal Queue<object> Answers;
            internal readonly List<object> Opens = new List<object>();
            internal readonly List<Action<int>> Runs = new List<Action<int>>();
            internal readonly List<Action> Leaves = new List<Action>();
            internal bool Unanswered;
            internal int Closed, Destroyed;
            public IntPtr Hwnd { get { return Handle; } }

            public bool Open(List<object> entries, Dictionary<string, object> strings, Action<int> run, int[] point, IntPtr owner,
                             Action onLeave)
            {
                string leave = onLeave == null ? null
                    : onLeave.Method.Name == "Hide" && ReferenceEquals(onLeave.Target, Popup) ? "hide" : "other";
                Opens.Add(new Dictionary<string, object>
                {
                    { "entries", Plain(entries) }, { "strings", new Dictionary<string, object>(strings) },
                    { "point", point == null ? null : new List<object> { (double)point[0], (double)point[1] } },
                    { "owner", owner == Popup.Hwnd ? (object)"popup" : (double)owner.ToInt64() }, { "leave", leave },
                });
                Runs.Add(run);
                Leaves.Add(onLeave);
                if (Answers.Count == 0)
                {
                    Unanswered = true;
                    return false;
                }
                object answer = Answers.Dequeue();
                if (answer is string) throw new InvalidOperationException("UpdateLayeredWindow");
                return (bool)answer;
            }

            public void Close() { Closed++; }
            public void Destroy() { Destroyed++; }
        }

        /// Thrown where the popup reaches Windows' own row menu: PopupWindow.ContextMenu calls user32 for it directly, not
        /// through SurfaceScreen, so the probe never lets it run (it stops at ThemeMenu, the first thing that half does).
        private sealed class WindowsMenuReached : Exception
        {
        }

        /// The popup's row menu and focus with nothing shown (tests/rustdiff/hostpopup.py's HostPopup, the twin of
        /// ui/popup's Popup as tests/test_popup_row_menu_drawn.py drives it): a PopupWindow whose window is a message-only
        /// window of the probe's own (never shown; named "popup" in the record), every other call it would make of Windows
        /// recorded (SurfaceScreen.Probe), its actions posted to the core's stand-in on the calling thread, given the core's
        /// popup (`core`: view, menus, read - the test's model's), what the test painted (`painted`: rows and rtl) and its
        /// row menu (`make_menu`: a RecordingRowMenu is made on the popup's first opening; `menu_hwnd` its window). Then each
        /// step: visible, focus, row_menu (the test set `_row_menu`), context (ContextMenu with an lparam), message (to the
        /// window procedure), hide, destroy, choose (a command in an opening's chooser), leave (an opening's click-away).
        /// After each step: how many actions were posted, the menu's closes and destroys, how often the popup hid (its
        /// TimerTick killed), Visible and its row menu. Where Windows' own menu would open, the run stops (`windows`).
        private static object PopupSteps(Dictionary<string, object> call)
        {
            List<string> saved = SurfaceScreen.Probe;
            Func<IntPtr, string> savedName = SurfaceScreen.Name;
            SurfaceScreen.Probe = new List<string>();
            IntPtr own = SurfaceNative.CreateWindowExW(0, "STATIC", "", 0, 0, 0, 0, 0, new IntPtr(-3), IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (own == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
            var popup = new PopupWindow((Dictionary<string, object>)call["strings"], SurfaceRender.Field(call, "locale") as string);
            try
            {
                var logs = new List<object>();
                bool windows = false;
                var actions = new RecordingActions();
                var menu = new RecordingRowMenu
                {
                    Popup = popup, Answers = new Queue<object>((List<object>)call["menu_answers"]),
                    Handle = SurfaceRender.Field(call, "menu_hwnd") is double ? new IntPtr((long)(double)call["menu_hwnd"]) : IntPtr.Zero,
                };
                int made = 0;
                SurfaceScreen.Name = hwnd => hwnd == own ? "popup" : savedName(hwnd);
                popup.Hwnd = own;
                popup.Actions = actions;
                popup.Worker = work => work();
                popup.Log = line =>
                {
                    if (windows) throw new WindowsMenuReached();
                    logs.Add(line);
                };
                popup.ThemeMenu = () =>
                {
                    windows = true;
                    throw new WindowsMenuReached();
                };
                if (Flag(call, "make_menu")) popup.MakeMenu = () => { made++; return menu; };
                popup.Snapshot((Dictionary<string, object>)call["core"]);
                popup.View();
                var painted = SurfaceRender.Field(call, "painted") as Dictionary<string, object>;
                if (painted != null)
                {
                    var plan = new SurfacePlan { Rows = new List<KeyValuePair<object, int[]>>() };
                    foreach (object each in (List<object>)painted["rows"])
                    {
                        var row = (List<object>)each;
                        var rect = (List<object>)row[1];
                        plan.Rows.Add(new KeyValuePair<object, int[]>(row[0], new[] { (int)(double)rect[0], (int)(double)rect[1],
                                                                                         (int)(double)rect[2], (int)(double)rect[3] }));
                    }
                    if (painted["rtl"] is bool) plan.Rtl = (bool)painted["rtl"];
                    popup.PaintedPlan = plan;
                }
                System.Reflection.FieldInfo rowMenu = typeof(PopupWindow).GetField("rowMenu", System.Reflection.BindingFlags.Instance
                                                                                    | System.Reflection.BindingFlags.NonPublic);
                var after = new List<object>();
                foreach (object each in (List<object>)call["steps"])
                {
                    var step = (List<object>)each;
                    string what = (string)step[0];
                    int recorded = SurfaceScreen.Probe.Count;
                    try
                    {
                        if (what == "visible") popup.Visible = (bool)step[1];
                        else if (what == "focus") popup.Focus = step[1] == null ? null : new SurfaceTarget((string)step[1], step[2]);
                        else if (what == "row_menu") rowMenu.SetValue(popup, step[1] is bool ? (object)false : step[1] == null ? null : menu);
                        else if (what == "context")
                        {
                            try
                            {
                                typeof(PopupWindow).GetMethod("ContextMenu", System.Reflection.BindingFlags.Instance
                                                              | System.Reflection.BindingFlags.NonPublic)
                                                   .Invoke(popup, new object[] { (long)(double)step[1] });
                            }
                            catch (System.Reflection.TargetInvocationException exc)
                            {
                                throw exc.InnerException;
                            }
                        }
                        else if (what == "message") popup.Message((int)(double)step[1], (long)(double)step[2], (long)(double)step[3]);
                        else if (what == "hide") popup.Hide();
                        else if (what == "destroy") popup.Dispose();
                        else if (what == "choose") menu.Runs[(int)(double)step[1]]((int)(double)step[2]);
                        else if (what == "leave") menu.Leaves[(int)(double)step[1]]();
                        else throw new ArgumentException("no popup step " + what);
                    }
                    catch (WindowsMenuReached)
                    {
                        windows = true;
                    }
                    int hid = 0;
                    for (int at = recorded; at < SurfaceScreen.Probe.Count; at++)
                        if (SurfaceScreen.Probe[at] == "KillTimer popup " + PopupWindow.TimerTick && what != "destroy") hid++;
                    object state = rowMenu.GetValue(popup);
                    after.Add(new Dictionary<string, object>
                    {
                        { "posted", (double)actions.Posted.Count }, { "closed", (double)menu.Closed }, { "destroyed", (double)menu.Destroyed },
                        { "hid", (double)hid }, { "visible", popup.Visible }, { "opens", (double)menu.Opens.Count }, { "made", (double)made },
                        { "logs", (double)logs.Count }, { "row_menu", state == null ? "none" : state is bool ? "broken" : "there" },
                    });
                    if (windows) break;
                }
                return new Dictionary<string, object>
                {
                    { "steps", after }, { "posted", actions.Posted }, { "logs", logs }, { "opens", menu.Opens },
                    { "unanswered", menu.Unanswered }, { "windows", windows }, { "record", new List<object>(SurfaceScreen.Probe) },
                };
            }
            finally
            {
                popup.Hwnd = IntPtr.Zero;
                SurfaceNative.DestroyWindow(own);
                SurfaceScreen.Probe = saved;
                SurfaceScreen.Name = savedName;
            }
        }

        [System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private static extern int GetClassNameW(IntPtr hwnd, StringBuilder name, int size);
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hwnd);

        /// The row menu's own window (tests/test_popup_row_menu_drawn.py WindowsTests' first): a popup with a row whose
        /// menu is made as the live host's icon makes it (MenuWindow) and opened as the test opens it - made by Create, as
        /// an opening makes it, and never shown; the class of the window the popup's menu is in.
        private sealed class CreatingRowMenu : IRowMenu
        {
            internal MenuWindow Inner;
            public IntPtr Hwnd { get { return Inner.Hwnd; } }

            public bool Open(List<object> entries, Dictionary<string, object> strings, Action<int> run, int[] point, IntPtr owner,
                             Action onLeave)
            {
                Inner.Create();
                return true;
            }

            public void Close() { Inner.Close(); }
            public void Destroy() { Inner.Destroy(); }
        }

        private static object RowMenuClass(Dictionary<string, object> call)
        {
            List<string> saved = SurfaceScreen.Probe;
            SurfaceScreen.Probe = new List<string>();
            IntPtr own = SurfaceNative.CreateWindowExW(0, "STATIC", "", 0, 0, 0, 0, 0, new IntPtr(-3), IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (own == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
            var popup = new PopupWindow((Dictionary<string, object>)call["strings"]);
            var made = new List<CreatingRowMenu>();
            try
            {
                popup.Hwnd = own;
                popup.Worker = work => work();
                popup.ThemeMenu = () => { throw new WindowsMenuReached(); };
                popup.Log = line => { throw new WindowsMenuReached(); };
                popup.MakeMenu = () =>
                {
                    var menu = new CreatingRowMenu { Inner = new MenuWindow(unused => { }) };
                    made.Add(menu);
                    return menu;
                };
                popup.Snapshot((Dictionary<string, object>)call["core"]);
                popup.View();
                var plan = new SurfacePlan { Rows = new List<KeyValuePair<object, int[]>>() };
                plan.Rows.Add(new KeyValuePair<object, int[]>(call["key"], new[] { 0, 0, 200, 60 }));
                popup.PaintedPlan = plan;
                try
                {
                    typeof(PopupWindow).GetMethod("ContextMenu", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                                       .Invoke(popup, new object[] { (long)(double)call["lparam"] });
                }
                catch (System.Reflection.TargetInvocationException exc)
                {
                    if (exc.InnerException is WindowsMenuReached) return new Dictionary<string, object> { { "windows", true } };
                    throw exc.InnerException;
                }
                if (made.Count == 0) return new Dictionary<string, object> { { "windows", false }, { "class", null } };
                var name = new StringBuilder(256);
                GetClassNameW(made[0].Hwnd, name, 256);
                bool visible = IsWindowVisible(made[0].Hwnd);
                return new Dictionary<string, object> { { "windows", false }, { "class", name.ToString() }, { "visible", visible },
                                                        { "made", (double)made.Count } };
            }
            finally
            {
                foreach (CreatingRowMenu menu in made) menu.Inner.Destroy();
                popup.Hwnd = IntPtr.Zero;
                SurfaceNative.DestroyWindow(own);
                SurfaceScreen.Probe = saved;
            }
        }

        /// The submenu arrow (WindowsTests' second): the row's numbered entries laid out by the host's own renderer at scale 1
        /// in `locale` (light, not High Contrast, the soft design) and drawn offscreen; the first item's arrow rectangle, the
        /// plan's width and rtl, and how many distinct BGR inks the drawing has inside the arrow's rectangle.
        private static object MenuArrow(Dictionary<string, object> call)
        {
            using (SurfaceRenderer renderer = SurfaceRenderer.Open())
            {
                renderer.Theme = "light";
                renderer.Contrast = false;
                renderer.Design = "soft";
                SurfacePlan plan = renderer.MenuLayout(MenuEntries((List<object>)call["entries"]), 1.0, (string)call["locale"]);
                byte[] pixels = renderer.DrawMenu(plan).Pixels();
                int width = plan.Size[0];
                double[] arrow = SurfaceRenderer.Box(plan.Items[0]["arrow"]);
                var inks = new HashSet<int>();
                for (int y = (int)arrow[1]; y < (int)arrow[3]; y++)
                    for (int x = (int)arrow[0]; x < (int)arrow[2]; x++)
                    {
                        int at = (y * width + x) * 4;
                        inks.Add(pixels[at] | (pixels[at + 1] << 8) | (pixels[at + 2] << 16));
                    }
                return new Dictionary<string, object>
                {
                    { "arrow", new List<object> { arrow[0], arrow[1], arrow[2], arrow[3] } }, { "width", (double)width },
                    { "rtl", plan.Rtl == true }, { "inks", (double)inks.Count },
                };
            }
        }

        private static int[] IntsOf(object value)
        {
            return ((List<object>)value).ConvertAll(each => (int)(double)each).ToArray();
        }

        /// The icon's tooltip card's own decisions (tests/rustdiff/hosttip.py's HostTip, the twin of ui/tray/tipcard's
        /// TipCard as tests/test_tray_tipcard.py CardStateTests drives it): a TipCard whose window is a message-only window
        /// of the probe's own (never shown; OnScreen false), not in High Contrast, then each step: visible, fade (the test
        /// set `_fade` to none), plan (its scale and size), screen (the icon's box), origin, hide (at once or not), message
        /// (to its window procedure). A step that lets it fade or not says so (`moves`: Reduce motion off or on), and a
        /// message carries the pointer and the clock the test's patched tip_pointer and time.monotonic answer then. After
        /// each step: Visible and its fade.
        private static object TipSteps(Dictionary<string, object> call)
        {
            IntPtr own = SurfaceNative.CreateWindowExW(0, "STATIC", "", 0, 0, 0, 0, 0, new IntPtr(-3), IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (own == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
            var logs = new List<object>();
            var tip = new TipCard(() => null, null, line => logs.Add(line)) { Hwnd = own, OnScreen = false, Contrast = false };
            try
            {
                int[] pointer = { 0, 0 };
                double clock = 0;
                bool moves = true;
                tip.AskReduced = () => !moves;
                tip.AskContrast = () => false;
                tip.Pointer = () => pointer;
                tip.Monotonic = () => clock;
                System.Reflection.MethodInfo proc = typeof(TipCard).GetMethod("WindowProc", System.Reflection.BindingFlags.Instance
                                                                              | System.Reflection.BindingFlags.NonPublic);
                var after = new List<object>();
                foreach (object each in (List<object>)call["steps"])
                {
                    var step = (List<object>)each;
                    string what = (string)step[0];
                    if (what == "visible") tip.Visible = (bool)step[1];
                    else if (what == "fade")
                        typeof(TipCard).GetField("fadeWay", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                                       .SetValue(tip, step[1] as string);
                    else if (what == "plan") tip.Plan = new SurfacePlan { Scale = (double)step[1], Size = IntsOf(step[2]) };
                    else if (what == "screen") tip.Screen = new TipCard.TipScreen { Box = IntsOf(step[1]) };
                    else if (what == "origin") tip.Origin = IntsOf(step[1]);
                    else if (what == "hide")
                    {
                        moves = (bool)step[2];
                        tip.Hide((bool)step[1]);
                    }
                    else if (what == "message")
                    {
                        moves = (bool)step[4];
                        if (step[5] is List<object>) pointer = IntsOf(step[5]);
                        clock = (double)step[6];
                        proc.Invoke(tip, new object[] { own, (uint)(double)step[1], new IntPtr((long)(double)step[2]),
                                                        new IntPtr((long)(double)step[3]) });
                    }
                    else throw new ArgumentException("no tip step " + what);
                    after.Add(new Dictionary<string, object> { { "visible", tip.Visible }, { "fade", tip.Fade } });
                }
                return new Dictionary<string, object> { { "steps", after }, { "logs", logs } };
            }
            finally
            {
                tip.Dispose();
                SurfaceNative.DestroyWindow(own);
            }
        }

        [System.Runtime.InteropServices.UnmanagedFunctionPointer(System.Runtime.InteropServices.CallingConvention.StdCall)]
        private delegate int AccessOut(IntPtr self, IntPtr child, IntPtr found);
        [System.Runtime.InteropServices.UnmanagedFunctionPointer(System.Runtime.InteropServices.CallingConvention.StdCall)]
        private delegate int AccessCount(IntPtr self, IntPtr found);

        private static Delegate Slot(IntPtr pointer, int slot, Type kind)
        {
            IntPtr table = System.Runtime.InteropServices.Marshal.ReadIntPtr(pointer);
            return System.Runtime.InteropServices.Marshal.GetDelegateForFunctionPointer(
                System.Runtime.InteropServices.Marshal.ReadIntPtr(table, slot * IntPtr.Size), kind);
        }

        /// What a screen reader is handed when it asks the icon's card (tests/test_tray_tipcard.py AccessibleTests): the
        /// object SurfaceAccess.Attach(TipCard) answers WM_GETOBJECT with (its TipSource in an AccessObject), for a card with
        /// no window, shown, its text the test's; asked through the object's own table as the test asks the reference's
        /// (slot 10 accName, 13 accRole, 14 accState of CHILDID_SELF, 8 accChildCount): each call's HRESULT and answer.
        private static object TipAccess(Dictionary<string, object> call)
        {
            var tip = new TipCard(() => null) { Visible = true, Text = (string)call["text"] };
            Type sourceType = typeof(SurfaceAccess).GetNestedType("TipSource", System.Reflection.BindingFlags.NonPublic);
            object source = Activator.CreateInstance(sourceType, System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic,
                                                     null, new object[] { tip }, null);
            var made = new SurfaceAccess.AccessObject((SurfaceAccess.IAccessSource)source);
            IntPtr pointer = made.Pointer;
            IntPtr variant = System.Runtime.InteropServices.Marshal.AllocHGlobal(16);
            IntPtr answer = System.Runtime.InteropServices.Marshal.AllocHGlobal(16);
            try
            {
                for (int at = 0; at < 16; at += 4) System.Runtime.InteropServices.Marshal.WriteInt32(variant, at, 0);
                System.Runtime.InteropServices.Marshal.WriteInt16(variant, 0, 3);       // VT_I4, 0: CHILDID_SELF
                var found = new Dictionary<string, object>();
                System.Runtime.InteropServices.Marshal.WriteIntPtr(answer, IntPtr.Zero);
                int named = ((AccessOut)Slot(pointer, 10, typeof(AccessOut)))(pointer, variant, answer);
                IntPtr text = System.Runtime.InteropServices.Marshal.ReadIntPtr(answer);
                found["name"] = new List<object> { (double)named, text == IntPtr.Zero ? null : System.Runtime.InteropServices.Marshal.PtrToStringBSTR(text) };
                if (text != IntPtr.Zero) System.Runtime.InteropServices.Marshal.FreeBSTR(text);
                foreach (int slot in new[] { 13, 14 })
                {
                    for (int at = 0; at < 16; at += 4) System.Runtime.InteropServices.Marshal.WriteInt32(answer, at, 0);
                    int result = ((AccessOut)Slot(pointer, slot, typeof(AccessOut)))(pointer, variant, answer);
                    found[slot == 13 ? "role" : "state"] = new List<object> { (double)result,
                                                                              (double)System.Runtime.InteropServices.Marshal.ReadInt32(answer, 8) };
                }
                System.Runtime.InteropServices.Marshal.WriteInt32(answer, -1);
                int counted = ((AccessCount)Slot(pointer, 8, typeof(AccessCount)))(pointer, answer);
                found["count"] = new List<object> { (double)counted, (double)System.Runtime.InteropServices.Marshal.ReadInt32(answer) };
                found["constants"] = new List<object> { (double)SurfaceAccess.ROLE_SYSTEM_TOOLTIP, (double)SurfaceAccess.STATE_SYSTEM_READONLY };
                return found;
            }
            finally
            {
                System.Runtime.InteropServices.Marshal.FreeHGlobal(variant);
                System.Runtime.InteropServices.Marshal.FreeHGlobal(answer);
            }
        }

        /// A menu item as MenuItems makes it, from its JSON: the id an int, as NativeMenu reads it.
        private static List<object> MenuEntries(List<object> json)
        {
            var items = new List<object>();
            foreach (object each in json)
            {
                var item = each as Dictionary<string, object>;
                if (item == null)
                {
                    items.Add(null);
                    continue;
                }
                var copy = new Dictionary<string, object>(item);
                if (item.ContainsKey("id") && item["id"] is double) copy["id"] = (int)(double)item["id"];
                items.Add(copy);
            }
            return items;
        }

        /// The drawn menu's keys as MenuPlan answers them (menuplan.menu_step, menu_end, menu_letter): one answer per question.
        private static object MenuKeys(Dictionary<string, object> call)
        {
            var answers = new List<object>();
            foreach (object each in (List<object>)call["asked"])
            {
                var asked = (List<object>)each;
                string what = (string)asked[0];
                List<object> entries = MenuEntries((List<object>)asked[1]);
                int? current = asked[2] is double ? (int?)(int)(double)asked[2] : null;
                if (what == "step")
                {
                    int? found = MenuPlan.Step(entries, current, (bool)asked[3]);
                    answers.Add(found.HasValue ? (object)(double)found.Value : null);
                }
                else if (what == "end")
                {
                    int? found = MenuPlan.End(entries, (bool)asked[3]);
                    answers.Add(found.HasValue ? (object)(double)found.Value : null);
                }
                else if (what == "letter")
                {
                    KeyValuePair<int?, bool> found = MenuPlan.Letter(entries, current, (string)asked[3]);
                    answers.Add(new List<object> { found.Key.HasValue ? (object)(double)found.Key.Value : null, found.Value });
                }
                else throw new ArgumentException("no menu question " + what);
            }
            return answers;
        }

        /// The drawn menu's own handlers with nothing that draws it on a screen (tests/test_tray_menu_drawn.py
        /// BehaviourTests): a MenuWindow with no window, its entries, words and chooser the test's, its plan its own renderer's
        /// MenuLayout at `scale` (as Open lays it out, over a 1920-pixel work area), open (Visible); its push draws into its own canvas only (the
        /// test's `_push` does nothing, the host's draws offscreen and blits to no window), what it tells a screen reader
        /// recorded (its Telling; its Speaking as SurfaceAccess's, with the announcement recorded as the changes it would
        /// make). Then each step: send a message to its window procedure, set Visible or Selected as the test does, take its
        /// Spoken, or read its accessible items. After each step: what Handle returned, Visible, Selected, what was chosen,
        /// what was told; and the plan's items and card.
        private static object MenuMessages(Dictionary<string, object> call)
        {
            List<string> saved = SurfaceScreen.Probe;
            SurfaceScreen.Probe = new List<string>();
            var logged = new List<object>();
            var menu = new MenuWindow(line => logged.Add(line));
            bool create = Flag(call, "create");
            try
            {
                var chosen = new List<object>();
                var told = new List<object>();
                int left = 0;
                menu.Entries = MenuEntries((List<object>)call["entries"]);
                menu.Strings = new Dictionary<string, object>((Dictionary<string, object>)call["strings"]);
                if (SurfaceRender.Field(call, "locale") is string) menu.Locale = (string)call["locale"];
                menu.OnChoose = id => chosen.Add(Plain(id));
                if (Flag(call, "leave")) menu.OnLeave = () => left++;
                if (SurfaceRender.Field(call, "owner") is double) menu.Owner = new IntPtr((long)(double)call["owner"]);
                menu.Telling = (hwnd, winEvent) => told.Add(new List<object> { "tell", (double)winEvent });
                menu.Speaking = window =>
                {
                    List<Dictionary<string, object>> items = window.AccessibleItems();
                    List<Dictionary<string, object>> before = window.Spoken;
                    window.Spoken = items;
                    if (before.Count == 0) return;
                    var changes = new List<object>();
                    foreach (int[] change in SurfaceAccess.Changes(before, items))
                        changes.Add(new List<object> { (double)change[0], (double)change[1] });
                    told.Add(new List<object> { "announce", Items(before), Items(items), changes });
                };
                SurfaceRenderer renderer;
                if (create)
                {
                    // its own window, made and never shown (a submenu's and the pointer's timer need one), as the render
                    // mode's MenuWindowCase makes it: every call that would show it is recorded instead
                    menu.Create();
                    renderer = menu.Renderer;
                }
                else
                {
                    renderer = SurfaceRenderer.Open();
                    typeof(MenuWindow).GetField("renderer", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                                      .SetValue(menu, renderer);
                }
                menu.Plan = renderer.MenuLayout(menu.Entries, (double)call["scale"], menu.Locale, 1920);
                menu.Work = new[] { 0, 0, 1920, 1040 };
                if (SurfaceRender.Field(call, "origin") is List<object>)
                {
                    var origin = (List<object>)call["origin"];
                    menu.Origin = new[] { (int)(double)origin[0], (int)(double)origin[1] };
                }
                menu.Visible = true;
                var after = new List<object>();
                foreach (object each in (List<object>)call["steps"])
                {
                    var step = (List<object>)each;
                    string what = (string)step[0];
                    object returned = null;
                    if (what == "send" || what == "send_child")
                    {
                        MenuWindow target = what == "send" ? menu : menu.Child;
                        IntPtr answer = target.Message((int)(double)step[1], (long)(double)step[2], (long)(double)step[3]);
                        returned = (double)answer.ToInt64();
                    }
                    else if (what == "visible") menu.Visible = (bool)step[1];
                    else if (what == "select") menu.Selected = step[1] is double ? (int?)(int)(double)step[1] : null;
                    else if (what == "spoken") menu.Spoken = menu.AccessibleItems();
                    else if (what == "accessible") returned = Items(menu.AccessibleItems());
                    else throw new ArgumentException("no menu step " + what);
                    object childIndex = typeof(MenuWindow).GetField("childIndex", System.Reflection.BindingFlags.Instance
                                                                    | System.Reflection.BindingFlags.NonPublic).GetValue(menu);
                    MenuWindow child = menu.Child;
                    after.Add(new Dictionary<string, object>
                    {
                        { "returned", returned }, { "visible", menu.Visible },
                        { "selected", menu.Selected.HasValue ? (object)(double)menu.Selected.Value : null },
                        { "chosen", new List<object>(chosen) }, { "told", new List<object>(told) }, { "left", (double)left },
                        { "child_index", childIndex != null ? (object)(double)(int)childIndex : null },
                        { "child", child == null ? null : new Dictionary<string, object>
                            {
                                { "visible", child.Visible }, { "entries", Plain(child.Entries) }, { "entries_of", EntriesOf(menu, child) },
                                { "selected", child.Selected.HasValue ? (object)(double)child.Selected.Value : null },
                                { "plan", child.Plan != null ? PlanJson(child.Plan) : null },
                            } },
                        { "records", (double)SurfaceScreen.Probe.Count },
                    });
                }
                return new Dictionary<string, object>
                {
                    { "steps", after }, { "log", logged }, { "record", new List<object>(SurfaceScreen.Probe) }, { "plan", PlanJson(menu.Plan) },
                };
            }
            finally
            {
                if (create) menu.Destroy();
                else if (menu.Renderer != null) menu.Renderer.Dispose();
                SurfaceScreen.Probe = saved;
            }
        }

        /// The parent's item whose own items the submenu holds, the very objects in their order; null when it holds others.
        private static object EntriesOf(MenuWindow parent, MenuWindow child)
        {
            for (int index = 0; index < parent.Entries.Count; index++)
            {
                var entry = parent.Entries[index] as Dictionary<string, object>;
                var items = entry == null ? null : SurfaceRender.Field(entry, "items") as List<object>;
                if (items == null || items.Count != child.Entries.Count) continue;
                bool same = true;
                for (int at = 0; at < items.Count && same; at++) same = ReferenceEquals(items[at], child.Entries[at]);
                if (same) return (double)index;
            }
            return null;
        }

        /// A menu plan's items (kind, index, rect) and card as plain JSON.
        private static object PlanJson(SurfacePlan plan)
        {
            var planItems = new List<object>();
            foreach (PlanItem item in plan.Items)
                planItems.Add(new Dictionary<string, object> { { "kind", item.Kind }, { "index", Plain(item.Get("index")) }, { "rect", Plain(item.Rect) } });
            return new Dictionary<string, object> { { "items", planItems }, { "card", Plain(plan.Card) }, { "rtl", plan.Rtl == true } };
        }

        /// Accessible items as plain JSON.
        private static List<object> Items(List<Dictionary<string, object>> items)
        {
            var plain = new List<object>();
            foreach (Dictionary<string, object> item in items) plain.Add(Plain(item));
            return plain;
        }

        /// The icon over a run of steps (tests/rustdiff/hosticon.py's HostTray, the twin of ui/tray's Tray as the tests drive
        /// it): a TrayIcon with no window and no shell icon, everything it would ask of Windows recorded (SurfaceScreen.Probe),
        /// its posts recorded by the core's stand-in on the calling thread, given the state the test set (`snapshot`,
        /// `strings`, `failed`, `unconfirmed`, `last_tip`, whether a control layer is there and whether the menu offers what
        /// is waiting), then each step: update, refresh, select, failure_seen, unseen (the icon's own question of the core,
        /// whether the failure it would show is unseen), act (a menu command chosen). Whether a failure is unseen is the
        /// core's answer: `answers` are given in order (true, false, or "raise"); a question past them is answered "no" and
        /// reported `unanswered`, with the marks it was asked about, so the test's control layer can be asked and the run
        /// made again (the ask-back of surfaceproxy.py's perform).
        private static object IconSteps(Dictionary<string, object> call)
        {
            List<string> saved = SurfaceScreen.Probe;
            SurfaceScreen.Probe = new List<string>();
            try
            {
                var logs = new List<object>();
                var answers = new Queue<object>((List<object>)call["answers"]);
                bool unanswered = false;
                object askedWith = null;
                RecordingActions actions = Flag(call, "actions") ? new RecordingActions { Raises = (List<object>)call["raises"] } : null;
                var popup = new RecordingPopup();
                var menu = new RecordingMenu { Answers = new Queue<object>((List<object>)SurfaceRender.Field(call, "menu_answers") ?? new List<object>()) };
                int menusMade = 0;
                Func<Dictionary<string, object>, bool> core = shown =>
                {
                    if (answers.Count == 0)
                    {
                        unanswered = true;
                        askedWith = Plain(SurfaceRender.Field(shown, "failures"));
                        return false;
                    }
                    object answer = answers.Dequeue();
                    if (answer is string) throw new IOException("unreadable");
                    return (bool)answer;
                };
                var icon = new TrayIcon
                {
                    Hwnd = new IntPtr(12345), Actions = actions, Pending = Flag(call, "pending"), Log = line => logs.Add(line),
                    Worker = work => work(), Now = () => (double)call["now"], FailureUnseen = core, MakePopup = () => popup,
                    Strings = new Dictionary<string, object>((Dictionary<string, object>)call["strings"]),
                    Failed = Flag(call, "failed"), Unconfirmed = Flag(call, "unconfirmed"), LastTip = SurfaceRender.Field(call, "last_tip") as string,
                };
                // the menu's state the test set: its own window or none, a drawn menu there already, or one that broke before
                if (SurfaceRender.Field(call, "hwnd") is bool && !Flag(call, "hwnd")) icon.Hwnd = IntPtr.Zero;
                icon.MenuTheming = false;
                icon.MenuBroken = Flag(call, "menu_broken");
                if (Flag(call, "menu_present")) icon.MenuDrawn = menu;
                icon.MakeMenu = () => { menusMade++; return menu; };
                icon.NativeChoice = SurfaceRender.Field(call, "native_choice") is double ? (int)(double)call["native_choice"] : 0;
                icon.Cursor = () => new int[2];
                icon.Update((Dictionary<string, object>)call["snapshot"]);
                var results = new List<object>();
                foreach (object each in (List<object>)call["steps"])
                {
                    var step = (List<object>)each;
                    string what = (string)step[0];
                    if (what == "update") icon.Update((Dictionary<string, object>)step[1]);
                    else if (what == "refresh") icon.Refresh();
                    else if (what == "select") Private(icon, "Select", step.Count > 1 && step[1] is bool && (bool)step[1]);
                    else if (what == "failure_seen") Private(icon, "FailureSeen");
                    else if (what == "unseen") results.Add(Private(icon, "Unseen", (Dictionary<string, object>)step[1], icon.FailureUnseen));
                    else if (what == "act") Private(icon, "Act", (int)(double)step[1], (bool)step[2]);
                    else if (what == "menu") icon.Menu();
                    else if (what == "choose") menu.Chosen(step[1]);
                    else if (what == "native") results.Add((double)(int)Private(icon, "NativeMenu", MenuEntries((List<object>)step[1])));
                    else if (what == "drop_menu") Private(icon, "DropMenu");
                    else if (what == "popup_can_open") results.Add(icon.PopupCanOpen());
                    else throw new ArgumentException("no step " + what);
                }
                return new Dictionary<string, object>
                {
                    { "posted", actions != null ? actions.Posted : new List<object>() }, { "logs", logs },
                    { "record", new List<object>(SurfaceScreen.Probe) }, { "failed", icon.Failed }, { "unconfirmed", icon.Unconfirmed },
                    { "last_tip", icon.LastTip }, { "shown", Plain(icon.Shown()) }, { "results", results },
                    { "unanswered", unanswered }, { "asked_with", askedWith }, { "popup", popup.Calls },
                    { "menu_opens", menu.Opens }, { "menu_unanswered", menu.Unanswered }, { "menu_made", (double)menusMade },
                    { "menu_destroyed", (double)menu.Destroyed }, { "menu_broken", icon.MenuBroken }, { "menu_there", icon.MenuDrawn != null },
                };
            }
            finally
            {
                SurfaceScreen.Probe = saved;
            }
        }

        private static bool Flag(Dictionary<string, object> call, string name)
        {
            object value = SurfaceRender.Field(call, name);
            return value is bool && (bool)value;
        }

        private static object Private(TrayIcon icon, string method, params object[] arguments)
        {
            return typeof(TrayIcon).GetMethod(method, System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                                   .Invoke(icon, arguments);
        }

        /// The icon's one-second tick for an icon Windows keeps in the overflow flyout (tests/test_tray_overflow_open.py
        /// OpenFlyoutTickTests.tick): a TrayIcon with no window, its frames an IconFrames never built (the test's
        /// object.__new__), placed in the flyout, the flyout open or not, Reduce motion on or not, High Contrast and battery
        /// saver off, its rect (0, 0, 16, 16); Observe(snapshot) then SyncMotion, every SetTimer/KillTimer recorded by the
        /// probe's SurfaceScreen and replayed into the timers a FakeUser32 would hold.
        private static object IconTick(Dictionary<string, object> call)
        {
            List<string> saved = SurfaceScreen.Probe;
            SurfaceScreen.Probe = new List<string>();
            try
            {
                bool flyout = Flag(call, "flyout_open"), reduced = Flag(call, "reduced");
                var rect = new int[4];
                rect[2] = 16;
                rect[3] = 16;
                var icon = new TrayIcon
                {
                    Hwnd = new IntPtr(12345),
                    Frames = (IconFrames)System.Runtime.Serialization.FormatterServices.GetUninitializedObject(typeof(IconFrames)),
                    AskPlacement = () => true, AskOverflowOpen = () => flyout, AskReduced = () => reduced,
                    AskContrast = () => false, AskBatterySaver = () => false, IconRectReader = () => rect,
                };
                Private(icon, "Observe", (Dictionary<string, object>)call["snapshot"]);
                Private(icon, "SyncMotion");
                var timers = new Dictionary<string, object>();
                foreach (string line in SurfaceScreen.Probe)
                {
                    string[] parts = line.Split(' ');
                    if (parts[0] == "SetTimer") timers[parts[2]] = double.Parse(parts[3], System.Globalization.CultureInfo.InvariantCulture);
                    else if (parts[0] == "KillTimer") timers.Remove(parts[2]);
                }
                return new Dictionary<string, object> { { "state", icon.IconState }, { "allowed", icon.MotionAllowed }, { "timers", timers } };
            }
            finally
            {
                SurfaceScreen.Probe = saved;
            }
        }

        /// The icon's own question (Overflowed): placed in the flyout or not, and how often it asked whether the flyout is open.
        private static object IconOverflowed(Dictionary<string, object> call)
        {
            bool placed = Flag(call, "placed"), open = Flag(call, "open");
            int asked = 0;
            var icon = new TrayIcon { AskPlacement = () => placed, AskOverflowOpen = () => { asked++; return open; } };
            bool answer = (bool)Private(icon, "Overflowed");
            return new Dictionary<string, object> { { "answer", answer }, { "asked", (double)asked } };
        }

        /// The demo's event as the icon looks for it (tests/test_diagnostics_tools.py DemoTrayTests): a TrayIcon named for a
        /// demo with an action, its event a handle the test stands in for, signalled as `signalled` says look by look
        /// (DemoTaken), LookForDemo once per look; how often the action ran, and whether an icon asked for no demo makes an
        /// event at all (OpenDemo, under the probe's record, which makes none).
        private static object IconDemo(Dictionary<string, object> call)
        {
            List<string> saved = SurfaceScreen.Probe;
            SurfaceScreen.Probe = new List<string>();
            try
            {
                var signalled = new Queue<object>((List<object>)call["signalled"]);
                int asked = 0;
                var icon = new TrayIcon { DemoName = (string)call["event"], OnDemo = () => asked++, DemoTaken = () => (bool)signalled.Dequeue() };
                typeof(TrayIcon).GetField("demo", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                                .SetValue(icon, new IntPtr(0xE7));
                int looks = (int)(double)call["looks"];
                for (int look = 0; look < looks; look++) Private(icon, "LookForDemo");
                bool none = (IntPtr)Private(new TrayIcon(), "OpenDemo") == IntPtr.Zero;
                return new Dictionary<string, object> { { "asked", (double)asked }, { "no_demo_no_event", none } };
            }
            finally
            {
                SurfaceScreen.Probe = saved;
            }
        }

        /// A notification card made with no window (NoticeCard's `windows: false`, as the render mode's `cards` case makes
        /// it), its layers settled - the body at full size, the shadow at the deepest level, through PaintLayers - and
        /// dumped: the body's and the shadow's BGRA pixels, base64. `whole` is the shadow of a second card whose image says
        /// nothing is wholly opaque, so CutUnderBody finds no pixel to clear: the shadow as it is stamped, before the cut
        /// (tests/test_card_shadow_under_body.py's `cut=False`). The stamp reads only the card's size and corner, never the
        /// image, so nothing else of it differs.
        private static object CardLayers(Dictionary<string, object> call)
        {
            var work = new List<int>();
            foreach (object each in (List<object>)call["work"]) work.Add((int)(double)each);
            var answer = new Dictionary<string, object>();
            for (int pass = 0; pass < 2; pass++)
            {
                using (var card = new NoticeCard(null, (Dictionary<string, object>)call["vm"], (string)call["title"],
                                                 call["stays"] is bool && (bool)call["stays"], (double)call["hold"], 0,
                                                 (double)call["dpi"], work.ToArray(), (Dictionary<string, object>)call["drawn"], false,
                                                 SurfaceRender.Field(call, "letters") as string))
                {
                    if (pass == 1)
                    {
                        byte[] pixels = card.Image.Pixels;
                        for (int at = 3; at < pixels.Length; at += 4)
                            if (pixels[at] == 0xFF) pixels[at] = 0xFE;
                    }
                    card.PaintLayers(CardFrame.Settled);
                    if (pass == 1)
                    {
                        answer["whole"] = Convert.ToBase64String(card.Shadow.Pixels());
                        continue;
                    }
                    answer["size"] = new List<object> { (double)card.Size[0], (double)card.Size[1] };
                    answer["margin"] = (double)card.Margin;
                    answer["shadows"] = (double)card.Shadows.Count;
                    answer["body"] = Convert.ToBase64String(card.Body.Pixels());
                    answer["cut"] = Convert.ToBase64String(card.Shadow.Pixels());
                    answer["shadow_size"] = new List<object> { (double)card.Shadow.Width, (double)card.Shadow.Height };
                }
            }
            return answer;
        }

        /// HKEY_CURRENT_USER as IconPlacement reads it, as tests/test_tray_icon_motion.py's FakeRegistry is: {key path: {value
        /// name: value}}, what was read, and a failure on request ("subkeys" or "value").
        private sealed class FakeKeys : ICurrentUserKeys
        {
            internal Dictionary<string, object> Keys = new Dictionary<string, object>();
            internal string Fail;
            internal readonly List<object> Reads = new List<object>();

            public List<string> Subkeys(string path)
            {
                Reads.Add(new List<object> { "subkeys", path });
                if (Fail == "subkeys") throw new IOException("no such key");
                bool found = Keys.ContainsKey(path);
                var names = new List<string>();
                foreach (string key in Keys.Keys)
                {
                    if (!key.StartsWith(path + "\\", StringComparison.Ordinal)) continue;
                    found = true;
                    string rest = key.Substring(path.Length + 1);
                    if (rest.IndexOf((char)92) < 0) names.Add(rest);
                }
                if (!found) throw new FileNotFoundException(path);
                names.Sort(StringComparer.Ordinal);
                return names;
            }

            public object Value(string path, string name)
            {
                Reads.Add(new List<object> { "value", path, name });
                if (Fail == "value") throw new IOException("cannot read");
                object key;
                if (!Keys.TryGetValue(path, out key)) return null;
                object value;
                return ((Dictionary<string, object>)key).TryGetValue(name, out value) ? value : null;
            }
        }

        /// user32 and dwmapi as OverflowOpen asks them (tests/test_tray_overflow_open.py's FakeWindows): [class, visible,
        /// cloaked] per window in z-order; a failing FindWindowEx on request.
        private sealed class FakeWindows : IOverflowWindows
        {
            internal List<object> Windows;
            internal bool Fail;

            public IntPtr FindWindowEx(IntPtr after, string className)
            {
                if (Fail) throw new IOException("FindWindowExW");
                int start = after == IntPtr.Zero ? 0 : (int)after - 100 + 1;
                for (int index = start; index < Windows.Count; index++)
                    if ((string)((List<object>)Windows[index])[0] == className) return new IntPtr(100 + index);
                return IntPtr.Zero;
            }

            public bool IsWindowVisible(IntPtr hwnd) { return (bool)((List<object>)Windows[(int)hwnd - 100])[1]; }

            public int Cloaked(IntPtr hwnd, out uint value)
            {
                value = (bool)((List<object>)Windows[(int)hwnd - 100])[2] ? 1u : 0u;
                return 0;
            }
        }

        /// IconPlacement over a run of steps: each sets the clock and the registry, asks `Overflowed` and reports its answer
        /// and every read it made, in order.
        private static object Placement(Dictionary<string, object> call)
        {
            var keys = new FakeKeys { Fail = call["fail"] as string };
            double now = 0;
            var folders = (Dictionary<string, object>)call["folders"];
            var placement = new IconPlacement((string)call["executable"], (int)(double)call["uid"], keys,
                                              guid => folders.ContainsKey(guid) ? folders[guid] as string : null, () => now);
            var answers = new List<object>();
            foreach (object each in (List<object>)call["steps"])
            {
                var step = (Dictionary<string, object>)each;
                now = (double)step["clock"];
                keys.Keys = (Dictionary<string, object>)step["keys"];
                keys.Reads.Clear();
                answers.Add(new Dictionary<string, object> { { "answer", placement.Overflowed() }, { "reads", new List<object>(keys.Reads) } });
            }
            return answers;
        }

        /// The icon card's parts as the reference's dictionary holds them: title, edition, (text, counts) pieces, meter rows.
        private static TrayWords.Parts PartsOf(Dictionary<string, object> json)
        {
            var parts = new TrayWords.Parts { Title = (string)json["title"], Edition = json["edition"] as string };
            foreach (object each in (List<object>)json["line"])
            {
                var piece = (List<object>)each;
                parts.Line.Add(new TrayWords.Piece { Text = (string)piece[0], Counts = piece[1] is bool && (bool)piece[1] });
            }
            foreach (object each in (List<object>)json["meter"]) parts.Meter.Add((Dictionary<string, object>)each);
            return parts;
        }
    }
}

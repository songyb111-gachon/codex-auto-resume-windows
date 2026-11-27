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
            if (name == "card_shade") return CardShade(call);
            if (name == "float_recipe") return FloatRecipe(call);
            if (name == "popup_press") return PopupPress(call);
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
            if (name == "popup_access") return PopupAccess(call);
            if (name == "card_fitting") return CardFitting(call);
            if (name == "popup_fit") return PopupFit(call);
            if (name == "tip_icon") return TipIcon(call);
            if (name == "popup_reader") return OnSta(() => PopupReader(call));
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
            if (name == "popup_live") return PopupLive(call);
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
            internal bool Shown;
            public bool Visible { get { return Shown; } }
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
            internal bool Shown;
            public bool Visible { get { return Shown; } }

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

        /// The function at `slot` of the object's table: the object's own delegate where the table is managed (as
        /// SurfaceAccess's is), invoked with the arguments the native caller passes.
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
                int named = (int)Slot(pointer, 10, typeof(AccessOut)).DynamicInvoke(pointer, variant, answer);
                IntPtr text = System.Runtime.InteropServices.Marshal.ReadIntPtr(answer);
                found["name"] = new List<object> { (double)named, text == IntPtr.Zero ? null : System.Runtime.InteropServices.Marshal.PtrToStringBSTR(text) };
                if (text != IntPtr.Zero) System.Runtime.InteropServices.Marshal.FreeBSTR(text);
                foreach (int slot in new[] { 13, 14 })
                {
                    for (int at = 0; at < 16; at += 4) System.Runtime.InteropServices.Marshal.WriteInt32(answer, at, 0);
                    int result = (int)Slot(pointer, slot, typeof(AccessOut)).DynamicInvoke(pointer, variant, answer);
                    found[slot == 13 ? "role" : "state"] = new List<object> { (double)result,
                                                                              (double)System.Runtime.InteropServices.Marshal.ReadInt32(answer, 8) };
                }
                System.Runtime.InteropServices.Marshal.WriteInt32(answer, -1);
                int counted = (int)Slot(pointer, 8, typeof(AccessCount)).DynamicInvoke(pointer, answer);
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
                icon.PopupFailed = Flag(call, "popup_failed");
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
                    else if (what == "power_armed") results.Add(Private(icon, "Armed"));
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

        /// The popup's card drawn alone and its shadow window's picture (gui/SurfaceLayers.cs CardLayers), with no window: one
        /// renderer and one CardLayers over a history of steps - "draw" (the look set, the vm laid out and drawn with the light's
        /// first frame, as PopupWindow draws it), "shade" (the same, then CardLayers.Shade) and "drop" (the layers let go, the
        /// host's one release of its shadow images) - and what the last step left: the canvas, the card, the picture, its
        /// margin, the images kept, and the GDI+ objects alive past the run's start.
        private static object CardShade(Dictionary<string, object> call)
        {
            int start = SurfaceGdip.GdipObjects;
            SurfaceRenderer renderer = SurfaceRenderer.Open();
            var layer = new CardLayers(IntPtr.Zero);
            var answer = new Dictionary<string, object>();
            try
            {
                SurfacePlan plan = null;
                foreach (object each in (List<object>)call["steps"])
                {
                    var step = (Dictionary<string, object>)each;
                    string what = (string)step["step"];
                    if (what == "drop")
                    {
                        layer.Dispose();
                        continue;
                    }
                    if (what != "draw" && what != "shade") throw new ArgumentException("no card_shade step " + what);
                    renderer.Theme = (string)step["theme"];
                    renderer.Design = (string)step["design"];
                    renderer.Contrast = step["contrast"] is bool && (bool)step["contrast"];
                    renderer.Lone = step["lone"] is bool && (bool)step["lone"];
                    var vm = (Dictionary<string, object>)step["vm"];
                    plan = renderer.Layout(vm, (double)step["scale"], (string)step["locale"]);
                    renderer.Draw(plan, PopupMotion.Halo(PopupWords.Str(SurfaceRender.Field(vm, "light")), 0.0, false, renderer.Design));
                    if (what == "shade") layer.Shade(renderer, plan);
                }
                SurfaceNative.GdiFlush();
                if (plan != null)
                {
                    answer["card"] = Plain(plan.Card);
                    answer["width"] = (double)renderer.Canvas.Width;
                    if (SurfaceRender.Field(call, "canvas") is bool && (bool)call["canvas"])
                        answer["canvas"] = Convert.ToBase64String(renderer.Canvas.Pixels());
                }
                answer["images"] = (double)layer.Images.Count;
                answer["margin"] = (double)layer.Margin;
                if (SurfaceRender.Field(call, "picture") is bool && (bool)call["picture"] && layer.Picture != null)
                {
                    answer["picture_width"] = (double)layer.Picture.Width;
                    answer["picture"] = Convert.ToBase64String(layer.Picture.Pixels());
                }
                answer["gdip"] = (double)(SurfaceGdip.GdipObjects - start);
                return answer;
            }
            finally
            {
                layer.Dispose();
                renderer.Dispose();
            }
        }

        /// The popup's shadow rule as gui/SurfaceLayers.cs holds it: FloatShadows(theme, design) as [dx, dy, blur, colour, alpha]
        /// lists, or FloatReach of the shadows given at a scale.
        private static object FloatRecipe(Dictionary<string, object> call)
        {
            if ((string)call["op"] == "shadows")
            {
                var found = new List<object>();
                foreach (FloatShadow s in SurfaceLayers.FloatShadows((string)call["theme"], (string)call["design"]))
                    found.Add(new List<object> { s.Dx, s.Dy, s.Blur, s.Colour, s.Alpha });
                return found;
            }
            var shadows = new List<FloatShadow>();
            foreach (object each in (List<object>)call["shadows"])
            {
                var s = (List<object>)each;
                shadows.Add(new FloatShadow((double)s[0], (double)s[1], (double)s[2], (string)s[3], (double)s[4]));
            }
            return (double)SurfaceLayers.FloatReach(shadows, (double)call["scale"]);
        }

        /// The seventh press of the popup's title (gui/PopupWindow.cs "the seventh press"): op "steps" - a PopupWindow with no
        /// window (Hwnd none: Update and SyncFrames reach nothing; every Windows call recorded besides), given reduced, contrast,
        /// visible, the painted plan's items and the strings, runs press (the private TitlePressed), set_aside (AsideFrom) and
        /// aside_words (the private AsideWords, its Monotonic the step's clock) and answers SweepSince, AsideFrom, the last
        /// words and the Windows calls; op "layout" - the host renderer's plan of a vm (items' kind and rect, targets); op
        /// "hit" - PopupPlace.HitTest over targets.
        private static object PopupPress(Dictionary<string, object> call)
        {
            string op = (string)call["op"];
            if (op == "layout")
            {
                SurfaceRenderer renderer = SurfaceRenderer.Open();
                try
                {
                    SurfacePlan plan = renderer.Layout((Dictionary<string, object>)call["vm"], (double)call["scale"], (string)call["locale"]);
                    var items = new List<object>();
                    foreach (PlanItem item in plan.Items)
                        if (item.Get("rect") != null)
                            items.Add(new Dictionary<string, object>
                            {
                                { "kind", item.Kind }, { "rect", new List<object>(Array.ConvertAll(SurfaceRenderer.Box(item["rect"]), d => (object)d)) },
                            });
                    var targets = new List<object>();
                    foreach (KeyValuePair<object, int[]> pair in plan.Targets)
                        targets.Add(new List<object> { Plain(pair.Key is SurfaceTarget ? ((SurfaceTarget)pair.Key).ToList() : pair.Key), Plain(pair.Value) });
                    return new Dictionary<string, object> { { "items", items }, { "targets", targets } };
                }
                finally
                {
                    renderer.Dispose();
                }
            }
            if (op == "hit")
            {
                var targets = new List<KeyValuePair<object, int[]>>();
                foreach (object each in (List<object>)call["targets"])
                {
                    var pair = (List<object>)each;
                    targets.Add(new KeyValuePair<object, int[]>(TargetOf(pair[0]), IntsOf(pair[1])));
                }
                object hit = PopupPlace.HitTest(targets, (int)(double)call["x"], (int)(double)call["y"]);
                return Plain(hit is SurfaceTarget ? ((SurfaceTarget)hit).ToList() : hit);
            }
            if (op != "steps") throw new ArgumentException("no popup_press op " + op);
            List<string> saved = SurfaceScreen.Probe;
            SurfaceScreen.Probe = new List<string>();
            try
            {
                var popup = new PopupWindow((Dictionary<string, object>)call["strings"]);
                popup.Reduced = Flag(call, "reduced");
                popup.Contrast = Flag(call, "contrast");
                popup.Visible = Flag(call, "visible");
                var painted = new SurfacePlan();
                foreach (object each in (List<object>)call["items"])
                {
                    var item = new PlanItem((Dictionary<string, object>)each);
                    item["rect"] = IntsOf(item["rect"]);
                    painted.Items.Add(item);
                }
                popup.PaintedPlan = painted;
                System.Reflection.MethodInfo pressed = typeof(PopupWindow).GetMethod("TitlePressed", Hidden);
                System.Reflection.MethodInfo aside = typeof(PopupWindow).GetMethod("AsideWords", Hidden);
                object words = null;
                foreach (object each in (List<object>)call["steps"])
                {
                    var step = (List<object>)each;
                    string what = (string)step[0];
                    if (what == "press") pressed.Invoke(popup, new object[] { (long)(double)step[1], (double)step[2] });
                    else if (what == "set_aside") popup.AsideFrom = step[1] == null ? (double?)null : (double)step[1];
                    else if (what == "aside_words")
                    {
                        double clock = (double)step[2];
                        popup.Monotonic = () => clock;
                        words = aside.Invoke(popup, new object[] { step[1] });
                    }
                    else throw new ArgumentException("no popup_press step " + what);
                }
                return new Dictionary<string, object>
                {
                    { "sweep_since", popup.SweepSince.HasValue ? (object)popup.SweepSince.Value : null },
                    { "aside_from", popup.AsideFrom.HasValue ? (object)popup.AsideFrom.Value : null },
                    { "words", words }, { "windows", new List<object>(SurfaceScreen.Probe) },
                };
            }
            finally
            {
                SurfaceScreen.Probe = saved;
            }
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

        // ------------------------------------------------------------------ the popup for a screen reader (S6.4d3)
        /// A target as the reference's tuple, from its JSON list: [name] or [name, key]; anything else as it is.
        private static object TargetOf(object value)
        {
            var list = value as List<object>;
            if (list == null || list.Count == 0 || !(list[0] is string)) return value;
            return list.Count == 1 ? new SurfaceTarget((string)list[0]) : new SurfaceTarget((string)list[0], list[1]);
        }

        /// A plan as the reference's popup plan holds what accessible_items reads: its items (kind, rect, text, role...),
        /// its targets and its rows, each rectangle an int[] and each target a SurfaceTarget.
        private static SurfacePlan PlanOf(object value)
        {
            var json = value as Dictionary<string, object>;
            if (json == null) return null;
            var plan = new SurfacePlan();
            var items = SurfaceRender.Field(json, "items") as List<object>;
            if (items != null)
                foreach (object each in items)
                {
                    var item = new PlanItem((Dictionary<string, object>)each);
                    if (item.Get("rect") is List<object>) item["rect"] = IntsOf(item["rect"]);
                    if (item.Get("target") is List<object>) item["target"] = TargetOf(item["target"]);
                    plan.Items.Add(item);
                }
            foreach (string name in new[] { "targets", "rows" })
            {
                var pairs = SurfaceRender.Field(json, name) as List<object>;
                if (pairs == null) continue;
                var kept = new List<KeyValuePair<object, int[]>>();
                foreach (object each in pairs)
                {
                    var pair = (List<object>)each;
                    kept.Add(new KeyValuePair<object, int[]>(name == "targets" ? TargetOf(pair[0]) : pair[0], IntsOf(pair[1])));
                }
                if (name == "targets") plan.Targets = kept;
                else plan.Rows = kept;
            }
            return plan;
        }

        /// accessible_items' children from their JSON (as this probe answered them, perhaps changed by the test).
        private static List<Dictionary<string, object>> ChildrenOf(object value)
        {
            var children = new List<Dictionary<string, object>>();
            foreach (object each in (List<object>)value)
            {
                var item = new Dictionary<string, object>((Dictionary<string, object>)each);
                if (item["rect"] is List<object>) item["rect"] = IntsOf(item["rect"]);
                item["target"] = TargetOf(item["target"]);
                children.Add(item);
            }
            return children;
        }

        /// The children as JSON: each target a list, each rectangle a list of numbers, the states a list.
        private static List<object> ChildrenJson(List<Dictionary<string, object>> items)
        {
            var plain = new List<object>();
            foreach (Dictionary<string, object> item in items)
            {
                var copy = new Dictionary<string, object>(item);
                var target = item["target"] as SurfaceTarget;
                if (target != null) copy["target"] = target.ToList();
                var states = item["states"] as List<string>;
                if (states != null) copy["states"] = states.ConvertAll(state => (object)state);
                plain.Add(Plain(copy));
            }
            return plain;
        }

        /// The popup's screen-reader rules (gui/SurfaceAccess.cs's pure half, tests/test_popup_access.py AccessibleItemsTests):
        /// `items` (AccessibleItems of a vm, a plan, focus, hover, strings), `pick` (the child at a point), `changes` (the
        /// events between two sets of children), `switch_name`, `focus_order` (PopupPlace's, the keyboard's order) and
        /// `events` (the event numbers).
        private static object PopupAccess(Dictionary<string, object> call)
        {
            string op = (string)call["op"];
            if (op == "items")
                return ChildrenJson(SurfaceAccess.AccessibleItems(SurfaceRender.Field(call, "vm") as Dictionary<string, object>,
                                                                  PlanOf(SurfaceRender.Field(call, "plan")), TargetOf(SurfaceRender.Field(call, "focus")),
                                                                  TargetOf(SurfaceRender.Field(call, "hover")),
                                                                  SurfaceRender.Field(call, "strings") as Dictionary<string, object>));
            if (op == "pick")
                return (double)SurfaceAccess.Pick(ChildrenOf(call["items"]), (int)(double)call["x"], (int)(double)call["y"]);
            if (op == "changes")
            {
                var events = new List<object>();
                foreach (int[] change in SurfaceAccess.Changes(ChildrenOf(call["before"]), ChildrenOf(call["after"])))
                    events.Add(new List<object> { (double)change[0], (double)change[1] });
                return events;
            }
            if (op == "switch_name") return SurfaceAccess.SwitchName((Dictionary<string, object>)call["task"]);
            if (op == "focus_order")
            {
                var order = new List<object>();
                foreach (object target in PopupPlace.FocusOrder(PlanOf(call["plan"]).Targets))
                    order.Add(target is SurfaceTarget ? ((SurfaceTarget)target).ToList() : target);
                return order;
            }
            if (op == "events")
                return new Dictionary<string, object>
                {
                    { "focus", (double)SurfaceAccess.EVENT_FOCUS }, { "reorder", (double)SurfaceAccess.EVENT_REORDER },
                    { "statechange", (double)SurfaceAccess.EVENT_STATECHANGE }, { "namechange", (double)SurfaceAccess.EVENT_NAMECHANGE },
                };
            throw new ArgumentException("no popup_access op " + op);
        }

        /// The notification card's text size (CardPlan.Fitting, ui/card's Card.fitting), as CardWindow asks it: the screen's
        /// dpi and work area (none where the screen says none) and the `text` the snapshot carries, whatever its JSON type.
        private static object CardFitting(Dictionary<string, object> call)
        {
            object work = SurfaceRender.Field(call, "work");
            return new Dictionary<string, object>
            {
                { "fit", CardPlan.Fitting((double)call["dpi"], work is List<object> ? IntsOf(work) : null, SurfaceRender.Field(call, "text")) },
                { "room", new List<object> { CardPlan.Room[0], CardPlan.Room[1] } },
            };
        }

        private static readonly System.Reflection.BindingFlags Hidden = System.Reflection.BindingFlags.Instance
                                                                      | System.Reflection.BindingFlags.NonPublic;

        /// The popup at Windows' text size (tests/test_popup_access.py PopupTextSizeTests): a PopupWindow whose window is a
        /// message-only window of the probe's own (never shown), its renderer the host's own (SurfaceRenderer.Open), given the
        /// core's popup, the text size (`text`), the screen (`work`, dpi 96), then steps: usual (its renderer's plan of the
        /// view at 1 in "en": the size), rebuild (Rebuild: its scale and size), hide, read_look (ReadLook with Windows'
        /// text size answering the step's value), asks (the method a new PopupWindow asks the text size through). After each: Fit, the text size it holds, and whether its renderer made its
        /// fonts again since the last step (`fonts_made`, `fonts_scale`).
        private static object PopupFit(Dictionary<string, object> call)
        {
            List<string> saved = SurfaceScreen.Probe;
            SurfaceScreen.Probe = new List<string>();
            IntPtr own = SurfaceNative.CreateWindowExW(0, "STATIC", "", 0, 0, 0, 0, 0, new IntPtr(-3), IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (own == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
            var popup = new PopupWindow((Dictionary<string, object>)call["strings"]);
            SurfaceRenderer renderer = SurfaceRenderer.Open();
            try
            {
                popup.Hwnd = own;
                typeof(PopupWindow).GetField("renderer", Hidden).SetValue(popup, renderer);
                System.Reflection.FieldInfo text = typeof(PopupWindow).GetField("text", Hidden);
                text.SetValue(popup, (double)call["text"]);
                int[] work = IntsOf(call["work"]);
                popup.Screen = new PopupWindow.PopupScreen { Work = work, Monitor = work, Icon = null, Cursor = new[] { 0, 0 }, Dpi = 96 };
                popup.Dpi = 96;
                popup.AskContrast = () => false;
                popup.AskReduced = () => false;
                popup.AskAppsLight = () => null;
                popup.Snapshot((Dictionary<string, object>)call["core"]);
                double now = (double)call["now"];
                var after = new List<object>();
                object fonts = renderer.Fonts;
                foreach (object each in (List<object>)call["steps"])
                {
                    var step = (List<object>)each;
                    string what = (string)step[0];
                    var answer = new Dictionary<string, object>();
                    if (what == "usual") answer["size"] = Plain(renderer.Layout(popup.View(), 1.0, "en").Size);
                    else if (what == "rebuild")
                    {
                        SurfacePlan plan = popup.Rebuild(now);
                        answer["scale"] = plan.Scale;
                        answer["size"] = Plain(plan.Size);
                    }
                    else if (what == "hide") popup.Hide();
                    else if (what == "read_look")
                    {
                        double asked = (double)step[1];
                        popup.AskTextScale = () => asked;
                        popup.ReadLook();
                    }
                    else if (what == "asks")
                    {
                        // where a PopupWindow asks Windows' text size, as it is made (the one place a test replaces)
                        System.Reflection.MethodInfo asks = new PopupWindow().AskTextScale.Method;
                        answer["asks"] = asks.DeclaringType.Name + "." + asks.Name;
                    }
                    else throw new ArgumentException("no popup_fit step " + what);
                    answer["fit"] = popup.Fit.HasValue ? (object)popup.Fit.Value : null;
                    answer["text"] = text.GetValue(popup);
                    answer["fonts_made"] = !ReferenceEquals(fonts, renderer.Fonts);
                    answer["fonts_scale"] = renderer.Fonts == null ? null : (object)renderer.Fonts.Scale;
                    fonts = renderer.Fonts;
                    after.Add(answer);
                }
                return new Dictionary<string, object> { { "steps", after }, { "spacing_m", (double)PopupWindow.SpacingM } };
            }
            finally
            {
                typeof(PopupWindow).GetField("renderer", Hidden).SetValue(popup, null);
                renderer.Dispose();
                popup.Hwnd = IntPtr.Zero;
                SurfaceNative.DestroyWindow(own);
                SurfaceScreen.Probe = saved;
            }
        }

        [System.Runtime.InteropServices.DllImport("oleacc.dll")]
        private static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint id, ref Guid iid, out IntPtr found);
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool PeekMessageW(out SurfaceNative.MSG message, IntPtr hwnd, uint min, uint max, uint remove);
        [System.Runtime.InteropServices.UnmanagedFunctionPointer(System.Runtime.InteropServices.CallingConvention.StdCall)]
        private delegate int ReaderOut(IntPtr self, IntPtr found);
        [System.Runtime.InteropServices.UnmanagedFunctionPointer(System.Runtime.InteropServices.CallingConvention.StdCall)]
        private delegate int ReaderChild(IntPtr self, IntPtr child, IntPtr found);
        [System.Runtime.InteropServices.UnmanagedFunctionPointer(System.Runtime.InteropServices.CallingConvention.StdCall)]
        private delegate int ReaderPress(IntPtr self, IntPtr child);
        [System.Runtime.InteropServices.UnmanagedFunctionPointer(System.Runtime.InteropServices.CallingConvention.StdCall)]
        private delegate int ReaderHit(IntPtr self, int x, int y, IntPtr found);
        [System.Runtime.InteropServices.UnmanagedFunctionPointer(System.Runtime.InteropServices.CallingConvention.StdCall)]
        private delegate int ReaderBox(IntPtr self, IntPtr left, IntPtr top, IntPtr width, IntPtr height, IntPtr child);
        [System.Runtime.InteropServices.UnmanagedFunctionPointer(System.Runtime.InteropServices.CallingConvention.StdCall)]
        private delegate uint ReaderCounted(IntPtr self);
        private static int readerClasses;

        /// `work` on a thread of its own in a single-threaded apartment, as the host's UI thread is (the probe's own main
        /// thread is the runtime's multithreaded one, where SurfaceAccess leaves WM_GETOBJECT to Windows): its answer, or
        /// what it threw.
        private static object OnSta(Func<object> work)
        {
            object answer = null;
            Exception thrown = null;
            var thread = new System.Threading.Thread(() =>
            {
                try
                {
                    answer = work();
                }
                catch (Exception exc)
                {
                    thrown = exc;
                }
            });
            thread.SetApartmentState(System.Threading.ApartmentState.STA);
            thread.Start();
            thread.Join();
            if (thrown != null) throw thrown;
            return answer;
        }

        /// One call through slot `slot` of a COM object's table, as a native caller makes it: the delegate the table points
        /// at (the object's own managed one where the object is SurfaceAccess's) invoked with the arguments.
        private static int CallSlot(IntPtr pointer, int slot, Type kind, params object[] arguments)
        {
            var all = new object[arguments.Length + 1];
            all[0] = pointer;
            Array.Copy(arguments, 0, all, 1, arguments.Length);
            return Convert.ToInt32(Slot(pointer, slot, kind).DynamicInvoke(all));
        }

        private static IntPtr ChildVariant(int child)
        {
            IntPtr variant = System.Runtime.InteropServices.Marshal.AllocHGlobal(24);
            for (int at = 0; at < 24; at++) System.Runtime.InteropServices.Marshal.WriteByte(variant, at, 0);
            System.Runtime.InteropServices.Marshal.WriteInt16(variant, 0, (short)SurfaceAccess.VT_I4);
            System.Runtime.InteropServices.Marshal.WriteInt32(variant, 8, child);
            return variant;
        }

        /// A BSTR-answering slot (10 accName, 20 accDefaultAction) for a child: [HRESULT, text or null].
        private static List<object> ReadText(IntPtr pointer, int slot, int child)
        {
            IntPtr variant = ChildVariant(child), found = System.Runtime.InteropServices.Marshal.AllocHGlobal(8);
            try
            {
                System.Runtime.InteropServices.Marshal.WriteIntPtr(found, IntPtr.Zero);
                int result = CallSlot(pointer, slot, typeof(ReaderChild), variant, found);
                IntPtr text = System.Runtime.InteropServices.Marshal.ReadIntPtr(found);
                string value = text == IntPtr.Zero ? null : System.Runtime.InteropServices.Marshal.PtrToStringBSTR(text);
                if (text != IntPtr.Zero) System.Runtime.InteropServices.Marshal.FreeBSTR(text);
                return new List<object> { (double)result, value };
            }
            finally
            {
                System.Runtime.InteropServices.Marshal.FreeHGlobal(variant);
                System.Runtime.InteropServices.Marshal.FreeHGlobal(found);
            }
        }

        /// A VARIANT-answering slot (13 accRole, 14 accState) for a child: [HRESULT, vt, lVal].
        private static List<object> ReadNumber(IntPtr pointer, int slot, int child)
        {
            IntPtr variant = ChildVariant(child), found = ChildVariant(0);
            try
            {
                System.Runtime.InteropServices.Marshal.WriteInt16(found, 0, 0);
                int result = CallSlot(pointer, slot, typeof(ReaderChild), variant, found);
                return new List<object> { (double)result, (double)System.Runtime.InteropServices.Marshal.ReadInt16(found),
                                          (double)System.Runtime.InteropServices.Marshal.ReadInt32(found, 8) };
            }
            finally
            {
                System.Runtime.InteropServices.Marshal.FreeHGlobal(variant);
                System.Runtime.InteropServices.Marshal.FreeHGlobal(found);
            }
        }

        /// Messages for this thread, run until `until` holds or `seconds` pass (the reference's _pump).
        private static void PumpUntil(Func<bool> until, double seconds)
        {
            DateTime deadline = DateTime.UtcNow.AddSeconds(seconds);
            while (!until() && DateTime.UtcNow < deadline)
            {
                SurfaceNative.MSG message;
                while (PeekMessageW(out message, IntPtr.Zero, 0, 0, 1))
                {
                    SurfaceNative.TranslateMessage(ref message);
                    SurfaceNative.DispatchMessageW(ref message);
                }
                System.Threading.Thread.Sleep(20);
            }
        }

        /// The popup read the way a screen reader reads it (tests/test_popup_access.py ScreenReaderTests): a PopupWindow given
        /// the core's popup, whose window is a message-only window of the probe's own class (never shown; every message it
        /// gets is the popup's Message, so WM_GETOBJECT is the host's answer), SurfaceAccess attached as the host attaches it,
        /// shown for the keyboard and not activated at `origin` with every other call of Windows' recorded (SurfaceScreen.Probe).
        /// Its client object is fetched as Narrator fetches it (AccessibleObjectFromWindow, OBJID_CLIENT) and asked through its
        /// table: the count, every child's name, role, state, default action and box, a hit two pixels inside each child,
        /// the focused child, one past the last; OBJID_WINDOW's role (Windows' own object). The children the popup itself
        /// says are on screen (`items`), its client offset and its window's (0, 0) on screen. Then each step: tab (the Tab
        /// key; the events told while it was handled, as SurfaceAccess's Speaking computes them), press (accDoDefaultAction
        /// on a child; what was posted), reader (a script run by Windows PowerShell with no window, CAR_HWND the window,
        /// while this thread answers its questions: exit code, out, err).
        private static object PopupReader(Dictionary<string, object> call)
        {
            List<string> saved = SurfaceScreen.Probe;
            Func<IntPtr, string> savedName = SurfaceScreen.Name;
            SurfaceScreen.Probe = new List<string>();
            var popup = new PopupWindow((Dictionary<string, object>)call["strings"]);
            SurfaceNative.WndProc proc = (hwnd, message, wParam, lParam) => popup.Message((int)message, wParam.ToInt64(), lParam.ToInt64(), hwnd);
            IntPtr instance = SurfaceNative.GetModuleHandleW(null);
            string className = "CarProbeReader-" + System.Diagnostics.Process.GetCurrentProcess().Id + "-" + (++readerClasses);
            var klass = new SurfaceNative.WNDCLASSW { LpfnWndProc = proc, HInstance = instance, LpszClassName = className };
            if (SurfaceNative.RegisterClassW(ref klass) == 0) throw new InvalidOperationException("RegisterClassW");
            IntPtr own;
            using (new SurfaceNative.PerMonitorDpi())        // as PopupWindow.Create makes its window: Per-Monitor-v2 aware
                own = SurfaceNative.CreateWindowExW(0, className, "", 0, 0, 0, 4000, 4000, new IntPtr(-3), IntPtr.Zero, instance, IntPtr.Zero);
            if (own == IntPtr.Zero)
            {
                SurfaceNative.UnregisterClassW(className, instance);
                throw new InvalidOperationException("CreateWindowExW");
            }
            IntPtr pointer = IntPtr.Zero;
            try
            {
                var actions = new RecordingActions();
                var logs = new List<object>();
                SurfaceScreen.Name = hwnd => hwnd == own ? "popup" : savedName(hwnd);
                popup.Hwnd = own;
                typeof(PopupWindow).GetField("renderer", Hidden).SetValue(popup, SurfaceRenderer.Open());
                popup.Actions = actions;
                popup.Worker = work => work();
                popup.Log = line => logs.Add(line);
                popup.AskTextScale = () => 1.0;
                popup.AskContrast = () => false;
                popup.AskReduced = () => false;
                popup.AskAppsLight = () => null;
                int[] origin = IntsOf(call["origin"]);
                popup.ScreenReader = window => new PopupWindow.PopupScreen
                {
                    Work = new[] { 0, 0, 1920, 1040 }, Monitor = new[] { 0, 0, 1920, 1080 }, Cursor = new[] { 0, 0 }, Dpi = 96,
                };
                SurfaceAccess.Attach(popup);
                var told = new List<object>();
                Action<PopupWindow> speaking = popup.Speaking;
                popup.Speaking = window =>
                {
                    var before = new List<Dictionary<string, object>>();
                    foreach (object item in window.Spoken) before.Add((Dictionary<string, object>)item);
                    speaking(window);
                    if (before.Count == 0) return;
                    var after = new List<Dictionary<string, object>>();
                    foreach (object item in window.Spoken) after.Add((Dictionary<string, object>)item);
                    var events = new List<object>();
                    foreach (int[] change in SurfaceAccess.Changes(before, after)) events.Add(new List<object> { (double)change[0], (double)change[1] });
                    told.Add(events);
                };
                popup.Snapshot((Dictionary<string, object>)call["core"]);
                popup.Show(true, false, origin);
                Guid iid = SurfaceAccess.IidAccessible;
                int got = AccessibleObjectFromWindow(own, unchecked((uint)SurfaceAccess.OBJID_CLIENT), ref iid, out pointer);
                if (got != 0 || pointer == IntPtr.Zero) throw new InvalidOperationException("AccessibleObjectFromWindow " + got);
                Func<List<Dictionary<string, object>>> expected = () =>
                    SurfaceAccess.AccessibleItems(popup.Vm, popup.Plan, popup.Keyboard ? popup.Focus : null, popup.Hover, popup.Strings);
                List<Dictionary<string, object>> items = expected();
                IntPtr counted = System.Runtime.InteropServices.Marshal.AllocHGlobal(8);
                var children = new List<object>();
                object count, focus;
                try
                {
                    System.Runtime.InteropServices.Marshal.WriteInt32(counted, -1);
                    int result = CallSlot(pointer, 8, typeof(ReaderOut), counted);
                    count = new List<object> { (double)result, (double)System.Runtime.InteropServices.Marshal.ReadInt32(counted) };
                    for (int child = 0; child <= items.Count + 1; child++)
                    {
                        var row = new Dictionary<string, object>
                        {
                            { "name", ReadText(pointer, 10, child) }, { "role", ReadNumber(pointer, 13, child) },
                            { "state", ReadNumber(pointer, 14, child) }, { "action", ReadText(pointer, 20, child) },
                        };
                        IntPtr box = System.Runtime.InteropServices.Marshal.AllocHGlobal(16), variant = ChildVariant(child);
                        try
                        {
                            int located = CallSlot(pointer, 22, typeof(ReaderBox), box, box + 4, box + 8, box + 12, variant);
                            var parts = new List<object> { (double)located };
                            for (int at = 0; at < 16; at += 4) parts.Add((double)System.Runtime.InteropServices.Marshal.ReadInt32(box, at));
                            row["box"] = parts;
                            if (located == 0)
                            {
                                IntPtr hit = ChildVariant(0);
                                try
                                {
                                    int hitResult = CallSlot(pointer, 24, typeof(ReaderHit), System.Runtime.InteropServices.Marshal.ReadInt32(box) + 2,
                                                             System.Runtime.InteropServices.Marshal.ReadInt32(box, 4) + 2, hit);
                                    row["hit"] = new List<object> { (double)hitResult, (double)System.Runtime.InteropServices.Marshal.ReadInt16(hit),
                                                                    (double)System.Runtime.InteropServices.Marshal.ReadInt32(hit, 8) };
                                }
                                finally
                                {
                                    System.Runtime.InteropServices.Marshal.FreeHGlobal(hit);
                                }
                            }
                        }
                        finally
                        {
                            System.Runtime.InteropServices.Marshal.FreeHGlobal(box);
                            System.Runtime.InteropServices.Marshal.FreeHGlobal(variant);
                        }
                        children.Add(row);
                    }
                    IntPtr focused = ChildVariant(0);
                    try
                    {
                        int focusResult = CallSlot(pointer, 18, typeof(ReaderOut), focused);
                        focus = new List<object> { (double)focusResult, (double)System.Runtime.InteropServices.Marshal.ReadInt16(focused),
                                                   (double)System.Runtime.InteropServices.Marshal.ReadInt32(focused, 8) };
                    }
                    finally
                    {
                        System.Runtime.InteropServices.Marshal.FreeHGlobal(focused);
                    }
                }
                finally
                {
                    System.Runtime.InteropServices.Marshal.FreeHGlobal(counted);
                }
                object windowRole;
                IntPtr std;
                int stdResult = AccessibleObjectFromWindow(own, unchecked((uint)SurfaceAccess.OBJID_WINDOW), ref iid, out std);
                if (stdResult == 0 && std != IntPtr.Zero)
                {
                    windowRole = ReadNumber(std, 13, 0);
                    CallSlot(std, 2, typeof(ReaderCounted));
                }
                else windowRole = new List<object> { (double)stdResult };
                var corner = new SurfaceNative.POINT { X = 0, Y = 0 };
                using (new SurfaceNative.PerMonitorDpi()) SurfaceNative.ClientToScreen(own, ref corner);
                var steps = new List<object>();
                foreach (object each in (List<object>)call["steps"])
                {
                    var step = (List<object>)each;
                    string what = (string)step[0];
                    var answer = new Dictionary<string, object>();
                    if (what == "tab")
                    {
                        int before = told.Count;
                        popup.Message(SurfaceNative.WM_KEYDOWN, SurfaceNative.VK_TAB, 0);
                        answer["told"] = told.GetRange(before, told.Count - before);
                    }
                    else if (what == "press")
                    {
                        int before = actions.Posted.Count;
                        IntPtr variant = ChildVariant((int)(double)step[1]);
                        try
                        {
                            answer["result"] = (double)CallSlot(pointer, 25, typeof(ReaderPress), variant);
                        }
                        finally
                        {
                            System.Runtime.InteropServices.Marshal.FreeHGlobal(variant);
                        }
                        PumpUntil(() => false, 0.05);
                        answer["posted"] = actions.Posted.GetRange(before, actions.Posted.Count - before);
                    }
                    else if (what == "reader")
                    {
                        var start = new System.Diagnostics.ProcessStartInfo((string)step[1],
                            "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"" + (string)step[2] + "\"")
                        {
                            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                            StandardOutputEncoding = new UTF8Encoding(false), StandardErrorEncoding = new UTF8Encoding(false),
                        };
                        start.EnvironmentVariables["CAR_HWND"] = own.ToInt64().ToString(System.Globalization.CultureInfo.InvariantCulture);
                        using (System.Diagnostics.Process child = System.Diagnostics.Process.Start(start))
                        {
                            System.Threading.Tasks.Task<string> output = child.StandardOutput.ReadToEndAsync();
                            System.Threading.Tasks.Task<string> errors = child.StandardError.ReadToEndAsync();
                            PumpUntil(() => child.HasExited, 120);
                            if (!child.HasExited) child.Kill();
                            child.WaitForExit();
                            answer["code"] = (double)child.ExitCode;
                            answer["out"] = output.Result;
                            answer["err"] = errors.Result;
                        }
                    }
                    else throw new ArgumentException("no popup_reader step " + what);
                    steps.Add(answer);
                }
                return new Dictionary<string, object>
                {
                    { "items", ChildrenJson(items) }, { "count", count }, { "children", children }, { "focus", focus },
                    { "window_role", windowRole }, { "offset", Plain(popup.ClientOffset()) },
                    { "corner", new List<object> { (double)corner.X, (double)corner.Y } }, { "steps", steps },
                    { "posted", actions.Posted }, { "logs", logs },
                };
            }
            finally
            {
                if (pointer != IntPtr.Zero) CallSlot(pointer, 2, typeof(ReaderCounted));
                popup.Dispose();
                SurfaceNative.UnregisterClassW(className, instance);
                GC.KeepAlive(proc);
                SurfaceScreen.Probe = saved;
                SurfaceScreen.Name = savedName;
            }
        }

        /// The icon's tooltip card as the icon uses it, standing in for the test's card (tests/test_tray_tip_messages.py's
        /// Card): every call recorded in order - show with the icon's box its reader gave and the point, hide (at once or
        /// fading), destroy; a card the test made to fail at showing throws there, as the test's does.
        private sealed class RecordingTip : ITrayTip
        {
            internal readonly List<object> Calls = new List<object>();
            internal string Fail;

            public void Show(Func<int[]> icon, int[] point)
            {
                if (Fail == "show") throw new InvalidOperationException("UpdateLayeredWindow");
                int[] box = icon();
                Calls.Add(new List<object> { "show", box == null ? null : Plain(box), Plain(point) });
            }

            public void Hide(bool atOnce) { Calls.Add(new List<object> { "hide", atOnce }); }
            public void Destroy() { Calls.Add(new List<object> { "destroy" }); }
        }

        /// The icon with the shell's words about hovering (tests/rustdiff/hosttipicon.py's HostTipTray, the twin of ui/tray's
        /// Tray as tests/test_tray_tip_messages.py drives it): a TrayIcon whose window is the test's number, everything it
        /// would ask of Windows recorded (SurfaceScreen.Probe: the shell's Shell_NotifyIconW with its flags and szTip, the
        /// timers), its drawn menu always shown, its popup and its icon's box the test's, its clock and the pointer the
        /// test's at each step. The shell answers NIM_SETVERSION with `versions` in order (true or false), and a card the
        /// icon makes with `makes` in order ("card": a new RecordingTip, "raise": the making throws); a question past them is
        /// reported unanswered (refused) so the test's shell or card class can be asked and the run made again. Then each
        /// step: update, version4, tip (none, broken, or a card the test made: its index and fail mode), popup (shown or
        /// not, or none), menu_drawn (shown or not, or none), taskbar (TaskbarCreated's number), session (locked, away),
        /// message (to the icon's Message, with that moment's clock and pointer), notify, set_version, show_tip, open_popup,
        /// tip_shows, shown. Answered: the record, every card's calls, how many it made, the card it holds (none, broken,
        /// or its index), Version4, TipShows, the step results and its log.
        private static object TipIcon(Dictionary<string, object> call)
        {
            List<string> saved = SurfaceScreen.Probe;
            SurfaceScreen.Probe = new List<string>();
            try
            {
                var logs = new List<object>();
                var tips = new List<RecordingTip>();
                var versions = new Queue<object>((List<object>)call["versions"]);
                var makes = new Queue<object>((List<object>)call["makes"]);
                bool unanswered = false;
                int made = 0;
                double clock = 0;
                bool onIcon = false;
                int[] rect = IntsOf(call["icon_rect"]);
                var popup = new RecordingPopup();
                var menu = new RecordingMenu { Answers = new Queue<object>() };
                var icon = new TrayIcon
                {
                    Hwnd = new IntPtr((long)(double)call["hwnd"]), Log = line => logs.Add(line), Worker = work => work(),
                    Now = () => (double)call["now"], Monotonic = () => clock, Edition = SurfaceRender.Field(call, "edition") as string,
                    Strings = new Dictionary<string, object>((Dictionary<string, object>)call["strings"]),
                    Actions = new RecordingActions(), MakePopup = () => popup, IconRectReader = () => (int[])rect.Clone(),
                };
                icon.MenuTheming = false;
                icon.PowerArmed = () => null;
                icon.Cursor = () => onIcon ? new[] { rect[0], rect[1] } : new[] { rect[2] + 10, rect[3] + 10 };
                icon.MakeMenu = () =>
                {
                    menu.Answers.Enqueue(true);                    // the test's _draw_menu: always shown
                    return menu;
                };
                icon.ShellAnswer = action =>
                {
                    if (action != TrayIcon.NIM_SETVERSION) return true;
                    if (versions.Count == 0)
                    {
                        unanswered = true;
                        return false;
                    }
                    return (bool)versions.Dequeue();
                };
                icon.MakeTip = () =>
                {
                    made++;
                    if (makes.Count == 0)
                    {
                        unanswered = true;
                        throw new InvalidOperationException("unanswered");
                    }
                    if ((string)makes.Dequeue() == "raise") throw new InvalidOperationException("RegisterClassW");
                    var tip = new RecordingTip();
                    tips.Add(tip);
                    return tip;
                };
                var given = new Dictionary<int, RecordingTip>();
                var results = new List<object>();
                foreach (object each in (List<object>)call["steps"])
                {
                    var step = (List<object>)each;
                    string what = (string)step[0];
                    if (what == "update") icon.Update((Dictionary<string, object>)step[1]);
                    else if (what == "version4") icon.Version4 = (bool)step[1];
                    else if (what == "tip")
                    {
                        icon.TipBroken = (string)step[1] == "broken";
                        icon.Tip = null;
                        if ((string)step[1] == "card")
                        {
                            int index = (int)(double)step[2];
                            if (!given.ContainsKey(index))
                            {
                                given[index] = new RecordingTip { Fail = step[3] as string };
                                tips.Add(given[index]);
                            }
                            icon.Tip = given[index];
                        }
                    }
                    else if (what == "popup") icon.Popup = step[1] == null ? null : new RecordingPopup { Shown = (bool)step[1] };
                    else if (what == "menu_drawn")
                        icon.MenuDrawn = step[1] == null ? null : new RecordingMenu { Answers = new Queue<object>(), Shown = (bool)step[1] };
                    else if (what == "taskbar")
                        typeof(TrayIcon).GetField("taskbarCreated", Hidden).SetValue(icon, (uint)(double)step[1]);
                    else if (what == "session")
                    {
                        icon.SessionLocked = (bool)step[1];
                        icon.SessionAway = (bool)step[2];
                    }
                    else if (what == "message")
                    {
                        clock = (double)step[4];
                        onIcon = (bool)step[5];
                        icon.Message(icon.Hwnd, (int)(double)step[1], (long)(double)step[2], (long)(double)step[3]);
                    }
                    else if (what == "notify") Private(icon, "Notify", (int)(double)step[1]);
                    else if (what == "set_version") Private(icon, "SetVersion");
                    else if (what == "show_tip") Private(icon, "ShowTip", (long)(double)step[1]);
                    else if (what == "open_popup") Private(icon, "OpenPopup");
                    else if (what == "tip_shows") results.Add(icon.TipShows());
                    else if (what == "shown") results.Add(Plain(icon.Shown()));
                    else throw new ArgumentException("no tip_icon step " + what);
                }
                var calls = new List<object>();
                foreach (RecordingTip tip in tips) calls.Add(tip.Calls);
                object holds = icon.Tip == null ? (icon.TipBroken ? (object)"broken" : "none") : (double)tips.IndexOf((RecordingTip)icon.Tip);
                var cards = new List<object>();
                foreach (KeyValuePair<int, RecordingTip> pair in given)
                    cards.Add(new List<object> { (double)pair.Key, (double)tips.IndexOf(pair.Value) });
                return new Dictionary<string, object>
                {
                    { "record", new List<object>(SurfaceScreen.Probe) }, { "calls", calls }, { "made", (double)made },
                    { "given", cards }, { "holds", holds }, { "version4", icon.Version4 }, { "tip_shows", icon.TipShows() },
                    { "results", results }, { "logs", logs }, { "unanswered", unanswered }, { "popup", popup.Calls },
                };
            }
            finally
            {
                SurfaceScreen.Probe = saved;
            }
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

        // ------------------------------------------------------------------ the popup's own windows, kept (S6.4d5)
        /// A PopupWindow made with its real windows (PopupWindow.Create: the card and its shadow, real top-level layered
        /// windows), kept between questions on a thread of its own in a single-threaded apartment, as the host's UI thread
        /// is. Only a twin of a test whose original makes the same real windows asks this (tests/test_popup_card_window.py
        /// CardWindowTests and the motion tests' WindowTests: the main session's word of 2026-11-28 - the same far-off
        /// coordinates, never activated, destroyed in the test's own teardown, inside gui_lock.sh, never a dialog). The
        /// thread runs Windows' messages only inside a step (show, pump, ...), as the reference's test thread runs them
        /// only when the test pumps; between questions it only peeks, so Windows never takes it for hung.
        private sealed class HeldPopup
        {
            internal PopupWindow Popup;
            internal readonly List<object> Logs = new List<object>();
            internal List<string> Record;
            internal IntPtr Body, Shadow;
            internal double NextFrame, NextTick;
            internal bool Contrast, Reduced, Still, StillRaises;
            internal double Text = 1.0;
            internal object Answer;
            /// The test's clock (its time.monotonic) less the host's, read as each question comes; a frame's or a
            /// render's own instant while it runs (`Frozen`), as the reference reads the clock around one.
            internal double Offset;
            internal double? Frozen;
            /// Each frame of the opening as motion.opening answered it: (elapsed ms, alpha, below, arrived).
            internal List<object> Openings;
        }

        private static readonly Dictionary<long, HeldPopup> heldPopups = new Dictionary<long, HeldPopup>();
        private static readonly Queue<object[]> heldJobs = new Queue<object[]>();
        private static System.Threading.Thread heldThread;
        private static long heldMade;

        private static object PopupLive(Dictionary<string, object> call)
        {
            if (heldThread == null)
            {
                heldThread = new System.Threading.Thread(HeldLoop) { IsBackground = true };
                heldThread.SetApartmentState(System.Threading.ApartmentState.STA);
                heldThread.Start();
            }
            var done = new System.Threading.ManualResetEvent(false);
            var job = new object[] { call, done, null, null };
            lock (heldJobs)
            {
                heldJobs.Enqueue(job);
                System.Threading.Monitor.Pulse(heldJobs);
            }
            done.WaitOne();
            if (job[3] != null) throw (Exception)job[3];
            return job[2];
        }

        private static void HeldLoop()
        {
            while (true)
            {
                object[] job = null;
                lock (heldJobs)
                {
                    if (heldJobs.Count == 0) System.Threading.Monitor.Wait(heldJobs, 20);
                    if (heldJobs.Count > 0) job = heldJobs.Dequeue();
                }
                if (job != null)
                {
                    try
                    {
                        job[2] = HeldAnswer((Dictionary<string, object>)job[0]);
                    }
                    catch (Exception exc)
                    {
                        job[3] = exc is System.Reflection.TargetInvocationException && exc.InnerException != null ? exc.InnerException : exc;
                    }
                    ((System.Threading.ManualResetEvent)job[1]).Set();
                }
                SurfaceNative.MSG message;
                PeekMessageW(out message, IntPtr.Zero, 0, 0, 0);          // PM_NOREMOVE: answered, nothing run
            }
        }

        private static object HeldAnswer(Dictionary<string, object> call)
        {
            string op = (string)call["op"];
            HeldPopup held;
            if (op == "new")
            {
                held = new HeldPopup();
                long id = ++heldMade;
                var popup = new PopupWindow((Dictionary<string, object>)call["strings"]);
                held.Popup = popup;
                popup.Log = line => held.Logs.Add(line);
                popup.AskContrast = () => held.Contrast;
                popup.AskReduced = () => held.Reduced;
                popup.AskAppsLight = () => null;
                popup.AskTextScale = () => held.Text;
                popup.Monotonic = () => held.Frozen ?? TrayPlace.Monotonic() + held.Offset;
                popup.Held = () =>
                {
                    if (held.StillRaises) throw new InvalidOperationException("held");
                    return held.Still;
                };
                if (SurfaceRender.Field(call, "record") is bool && (bool)call["record"]) held.Record = new List<string>();
                heldPopups[id] = held;
                return HeldRun(held, id, call, () =>
                {
                    SurfaceAccess.Attach(popup);
                    popup.Create();
                    held.Body = popup.Hwnd;
                    held.Shadow = popup.Layers != null ? popup.Layers.ShadowHwnd : IntPtr.Zero;
                    popup.Snapshot((Dictionary<string, object>)call["core"]);
                });
            }
            long which = (long)(double)call["id"];
            if (!heldPopups.TryGetValue(which, out held)) throw new ArgumentException("no popup " + which);
            if (op == "end")
            {
                heldPopups.Remove(which);
                return HeldRun(held, which, call, () => held.Popup.Dispose());
            }
            if (op == "do") return HeldRun(held, which, call, null);
            throw new ArgumentException("no popup_live op " + op);
        }

        /// The look the test's patched questions answer now (`look`), then `first` and each step with this popup's calls
        /// recorded where the test records them (`record`), then the popup's state as the twin reads it.
        private static object HeldRun(HeldPopup held, long id, Dictionary<string, object> call, Action first)
        {
            var look = SurfaceRender.Field(call, "look") as Dictionary<string, object>;
            if (look != null)
            {
                held.Contrast = (bool)look["contrast"];
                held.Reduced = (bool)look["reduced"];
                held.Text = (double)look["text"];
                held.Still = look["still"] is bool && (bool)look["still"];
                held.StillRaises = look["still"] as string == "raise";
                if (look["clock"] is double) held.Offset = (double)look["clock"] - TrayPlace.Monotonic();
                SurfaceTheme.SetTheme(look["theme"]);
                SurfaceTheme.SetDesign(look["design"]);
            }
            Func<IntPtr, string> savedName = SurfaceScreen.Name;
            List<string> savedProbe = SurfaceScreen.Probe;
            SurfaceScreen.Name = hwnd => hwnd == held.Body && hwnd != IntPtr.Zero ? "card"
                                       : hwnd == held.Shadow && hwnd != IntPtr.Zero ? "shadow" : savedName(hwnd);
            var answers = new List<object>();
            try
            {
                SurfaceScreen.Probe = held.Record;
                if (first != null) first();
                var steps = SurfaceRender.Field(call, "steps") as List<object>;
                if (steps != null)
                    foreach (object each in steps)
                    {
                        held.Answer = null;
                        HeldStep(held, (List<object>)each);
                        answers.Add(held.Answer);
                    }
            }
            finally
            {
                SurfaceScreen.Probe = savedProbe;
                SurfaceScreen.Name = savedName;
            }
            return HeldState(held, id, answers);
        }

        private static void HeldStep(HeldPopup held, List<object> step)
        {
            PopupWindow popup = held.Popup;
            string what = (string)step[0];
            if (what == "show")
                popup.Show((bool)step[1], (bool)step[2], step[3] == null ? null : IntsOf(step[3]));
            else if (what == "hide") popup.Hide();
            else if (what == "destroy") popup.Dispose();
            else if (what == "read_look") popup.ReadLook();
            else if (what == "invalidate") typeof(PopupWindow).GetMethod("Invalidate", Hidden).Invoke(popup, null);
            else if (what == "push") typeof(PopupWindow).GetMethod("Push", Hidden).Invoke(popup, null);
            else if (what == "update") popup.Update();
            else if (what == "static_dirty") popup.StaticDirty = (bool)step[1];
            else if (what == "hover_index") popup.Hover = popup.Plan.Targets[(int)(double)step[1]].Key;
            else if (what == "pressed_index") popup.Pressed = step[1] == null ? null : popup.Plan.Targets[(int)(double)step[1]].Key;
            else if (what == "message")
                held.Answer = (double)popup.Message((int)(double)step[1], (long)(double)step[2], (long)(double)step[3]).ToInt64();
            else if (what == "record")
            {
                held.Record = (bool)step[1] ? (held.Record ?? new List<string>()) : null;
                SurfaceScreen.Probe = held.Record;
            }
            else if (what == "pump") HeldPump(held, (double)step[1]);
            else if (what == "screen")
            {
                var screen = (Dictionary<string, object>)step[1];
                var fixedScreen = new PopupWindow.PopupScreen
                {
                    Icon = screen["icon"] == null ? null : IntsOf(screen["icon"]), Cursor = IntsOf(screen["cursor"]),
                    Work = IntsOf(screen["work"]), Monitor = IntsOf(screen["monitor"]), Dpi = (double)screen["dpi"],
                };
                popup.ScreenReader = unused => fixedScreen;
            }
            else if (what == "refuse")
            {
                // Windows refusing the card: its shadow window is no layered window any more, so UpdateLayeredWindowIndirect
                // fails for it (the reference's patched layers.update fails every upload; the host's first push fails here)
                int style = SurfaceNative.GetWindowLongW(held.Shadow, SurfaceNative.GWL_EXSTYLE);
                SurfaceNative.SetWindowLongW(held.Shadow, SurfaceNative.GWL_EXSTYLE, style & ~(int)SurfaceNative.WS_EX_LAYERED);
            }
            else if (what == "hit")
            {
                object target = typeof(PopupWindow).GetMethod("Hit", Hidden).Invoke(popup, new object[] { (long)(double)step[1] });
                var named = target as SurfaceTarget;
                held.Answer = named != null ? named.ToList() : Plain(target);
            }
            else if (what == "client_offset") held.Answer = Plain(popup.ClientOffset());
            else if (what == "snapshot") popup.Snapshot((Dictionary<string, object>)step[1]);
            else if (what == "openings") held.Openings = (bool)step[1] ? (held.Openings ?? new List<object>()) : null;
            else if (what == "kept")
            {
                // the window procedure Windows calls is the delegate this popup holds (PopupWindow.proc), so the popup
                // being held keeps it callable for as long as its window exists
                var proc = (Delegate)typeof(PopupWindow).GetField("proc", Hidden).GetValue(popup);
                IntPtr called = popup.Hwnd == IntPtr.Zero ? IntPtr.Zero : GetWindowLongPtrW(popup.Hwnd, -4);
                held.Answer = new Dictionary<string, object>
                {
                    { "held", heldPopups.ContainsValue(held) }, { "window", popup.Hwnd != IntPtr.Zero },
                    { "its_own", proc != null && called != IntPtr.Zero
                                 && called == System.Runtime.InteropServices.Marshal.GetFunctionPointerForDelegate(proc) },
                };
            }
            else if (what == "render")
            {
                // where the test reads the faces its renderer's draw is given: the same instant for both (the test's
                // clock as the question came), FaceGlides read as Render reads it first, and whether Render drew whole
                bool faces = step.Count > 1 && step[1] is bool && (bool)step[1];
                SurfaceRenderer drawing = popup.Renderer;
                bool whole = popup.Plan == null || popup.StaticDirty || popup.Glides.Count > 0 || popup.Faces.Count > 0
                             || drawing.HaloPlan != popup.Plan || drawing.Theme != popup.Theme || drawing.Design != popup.Design
                             || drawing.Contrast != popup.Contrast;
                held.Frozen = TrayPlace.Monotonic() + held.Offset;
                object given = null;
                SurfaceCanvas canvas;
                try
                {
                    if (faces)
                    {
                        var shown = (Dictionary<object, ButtonFace>)typeof(PopupWindow).GetMethod("FaceGlides", Hidden).Invoke(popup, null);
                        var pairs = new List<object>();
                        foreach (KeyValuePair<object, ButtonFace> pair in shown)
                        {
                            var named = pair.Key as SurfaceTarget;
                            pairs.Add(new List<object> { named != null ? named.ToList() : Plain(pair.Key), Plain(pair.Value.Fill),
                                                         Plain(pair.Value.Edge), pair.Value.Amount });
                        }
                        given = pairs;
                    }
                    canvas = popup.Render();
                }
                finally
                {
                    held.Frozen = null;
                }
                var bytes = new List<object>();
                for (int at = 0; at < 4; at++) bytes.Add((double)System.Runtime.InteropServices.Marshal.ReadByte(canvas.Bits, at));
                held.Answer = new Dictionary<string, object> { { "first", bytes }, { "whole", whole }, { "faces", whole ? given : null } };
            }
            else if (what == "access") held.Answer = HeldAccess(popup, (int)(double)step[1]);
            else throw new ArgumentException("no popup_live step " + what);
        }

        /// Windows' messages for this thread for `seconds` (at least one round), as the reference's test pumps them; where
        /// the popup's calls are recorded (not made), what it posted itself is delivered and its frame and tick timers,
        /// which were recorded and not set, come when they are due.
        private static void HeldPump(HeldPopup held, double seconds)
        {
            PopupWindow popup = held.Popup;
            var clock = System.Diagnostics.Stopwatch.StartNew();
            System.Reflection.FieldInfo frameField = typeof(PopupWindow).GetField("frameMs", Hidden);
            do
            {
                SurfaceNative.MSG message;
                while (PeekMessageW(out message, IntPtr.Zero, 0, 0, 1))
                {
                    SurfaceNative.MSG each = message;
                    if (each.Hwnd == popup.Hwnd && each.Message == SurfaceNative.WM_TIMER && each.WParam.ToInt64() == PopupWindow.TimerFrame)
                        HeldFrame(held, () => SurfaceNative.DispatchMessageW(ref each));
                    else
                    {
                        SurfaceNative.TranslateMessage(ref message);
                        SurfaceNative.DispatchMessageW(ref message);
                    }
                }
                if (SurfaceScreen.Probing && popup.Hwnd != IntPtr.Zero)
                {
                    var posted = new List<long[]>(SurfaceScreen.Posted);
                    SurfaceScreen.Posted.Clear();
                    foreach (long[] each in posted) popup.Message((int)each[1], each[2], each[3], new IntPtr(each[0]));
                    double now = popup.Monotonic();
                    if (popup.FrameRunning && popup.Hwnd != IntPtr.Zero && now >= held.NextFrame)
                    {
                        object every = frameField.GetValue(popup);
                        held.NextFrame = now + (every == null ? PopupWindow.FrameMs : Convert.ToDouble(every)) / 1000.0;
                        HeldFrame(held, () => popup.Message(SurfaceNative.WM_TIMER, PopupWindow.TimerFrame, 0));
                    }
                    if (popup.Visible && popup.Hwnd != IntPtr.Zero)
                    {
                        if (held.NextTick == 0) held.NextTick = now + 1.0;
                        else if (now >= held.NextTick)
                        {
                            held.NextTick = now + 1.0;
                            popup.Message(SurfaceNative.WM_TIMER, PopupWindow.TimerTick, 0);
                        }
                    }
                }
                System.Threading.Thread.Sleep(2);
            } while (clock.Elapsed.TotalSeconds < seconds);
        }

        /// One frame delivered at its own instant, and where the opening was a step of it, that step as motion.opening
        /// answered it: the elapsed time it was asked at (from the instant its first frame read, as OpeningStep keeps it),
        /// the alpha and the rise it gave, and whether it said arrived.
        private static void HeldFrame(HeldPopup held, Action deliver)
        {
            PopupWindow popup = held.Popup;
            double[] before = popup.Opening;
            double now = TrayPlace.Monotonic() + held.Offset;
            held.Frozen = now;
            try
            {
                deliver();
            }
            finally
            {
                held.Frozen = null;
            }
            if (before == null || held.Openings == null) return;
            double started = double.IsNaN(before[0]) ? now * 1000.0 : before[0];
            held.Openings.Add(new List<object> { now * 1000.0 - started, (double)popup.Alpha, (double)popup.Below, popup.Opening == null });
        }

        /// The screen reader's children (SurfaceAccess.AccessibleItems) and the box of child `child` as accLocation answers
        /// it, through the client object Windows hands a reader (AccessibleObjectFromWindow, OBJID_CLIENT): [HRESULT, left,
        /// top, width, height].
        private static object HeldAccess(PopupWindow popup, int child)
        {
            List<Dictionary<string, object>> items = SurfaceAccess.AccessibleItems(popup.Vm, popup.Plan, popup.Keyboard ? popup.Focus : null,
                                                                                   popup.Hover, popup.Strings);
            var answer = new Dictionary<string, object> { { "items", ChildrenJson(items) } };
            if (child <= 0) return answer;
            Guid iid = SurfaceAccess.IidAccessible;
            IntPtr pointer;
            int got = AccessibleObjectFromWindow(popup.Hwnd, unchecked((uint)SurfaceAccess.OBJID_CLIENT), ref iid, out pointer);
            if (got != 0 || pointer == IntPtr.Zero) throw new InvalidOperationException("AccessibleObjectFromWindow " + got);
            IntPtr box = System.Runtime.InteropServices.Marshal.AllocHGlobal(16), variant = ChildVariant(child);
            try
            {
                int located = CallSlot(pointer, 22, typeof(ReaderBox), box, box + 4, box + 8, box + 12, variant);
                var parts = new List<object> { (double)located };
                for (int at = 0; at < 16; at += 4) parts.Add((double)System.Runtime.InteropServices.Marshal.ReadInt32(box, at));
                answer["location"] = parts;
            }
            finally
            {
                System.Runtime.InteropServices.Marshal.FreeHGlobal(box);
                System.Runtime.InteropServices.Marshal.FreeHGlobal(variant);
                System.Runtime.InteropServices.Marshal.Release(pointer);
            }
            return answer;
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern IntPtr GetWindowLongPtrW(IntPtr hwnd, int index);

        private static List<object> TargetsOf<T>(Dictionary<object, T> map, Func<T, object> value)
        {
            var pairs = new List<object>();
            if (map == null) return pairs;
            foreach (KeyValuePair<object, T> pair in map)
            {
                var named = pair.Key as SurfaceTarget;
                pairs.Add(new List<object> { named != null ? named.ToList() : Plain(pair.Key), value(pair.Value) });
            }
            return pairs;
        }

        private static object HeldState(HeldPopup held, long id, List<object> answers)
        {
            PopupWindow popup = held.Popup;
            SurfaceRenderer renderer = popup.Renderer;
            CardLayers layers = popup.Layers;
            SurfacePlan plan = popup.Plan;
            object planJson = null;
            if (plan != null)
            {
                var targets = new List<object>();
                foreach (KeyValuePair<object, int[]> pair in plan.Targets)
                {
                    var named = pair.Key as SurfaceTarget;
                    targets.Add(new List<object> { named != null ? named.ToList() : Plain(pair.Key), Plain(pair.Value) });
                }
                var items = new List<object>();
                foreach (PlanItem item in plan.Items)
                {
                    var named = item.Get("target") as SurfaceTarget;
                    items.Add(new Dictionary<string, object>
                    {
                        { "kind", item.Kind }, { "target", named != null ? named.ToList() : Plain(item.Get("target")) },
                    });
                }
                planJson = new Dictionary<string, object>
                {
                    { "card", Plain(plan.Card) }, { "size", Plain(plan.Size) }, { "scale", plan.Scale }, { "targets", targets },
                    { "items", items },
                };
            }
            var shadows = new List<object>();
            if (layers != null)
                foreach (FloatShadow shadow in layers.Shadows)
                    shadows.Add(new List<object> { shadow.Dx, shadow.Dy, shadow.Blur, shadow.Colour, shadow.Alpha });
            var records = new List<object>();
            if (held.Record != null) foreach (string line in held.Record) records.Add(line);
            object rounded = typeof(PopupWindow).GetField("rounded", Hidden).GetValue(popup);
            object opening = null;
            if (popup.Opening != null)
                opening = new List<object>(Array.ConvertAll(popup.Opening, number => double.IsNaN(number) ? null : (object)number));
            return new Dictionary<string, object>
            {
                { "id", (double)id }, { "hwnd", (double)held.Body.ToInt64() }, { "shadow", (double)held.Shadow.ToInt64() },
                { "live", popup.Hwnd != IntPtr.Zero }, { "card", popup.Card }, { "lone", renderer != null && renderer.Lone },
                { "rounded", rounded }, { "visible", popup.Visible }, { "alpha", (double)popup.Alpha }, { "below", (double)popup.Below },
                { "opening", opening }, { "owed", popup.Owed }, { "static_dirty", popup.StaticDirty }, { "frames", popup.FrameRunning },
                { "margin", layers == null ? null : (object)(double)layers.Margin }, { "layers", layers != null },
                { "shadows", shadows }, { "plan", planJson },
                { "halo_rows", renderer == null || renderer.HaloRows == null ? null : Plain(renderer.HaloRows) },
                { "logs", new List<object>(held.Logs) }, { "records", records }, { "recording", held.Record != null },
                { "answers", answers }, { "still", popup.Still },
                { "frame_ms", typeof(PopupWindow).GetField("frameMs", Hidden).GetValue(popup) is int
                              ? (object)(double)(int)typeof(PopupWindow).GetField("frameMs", Hidden).GetValue(popup) : null },
                { "faces", TargetsOf(popup.Faces, face => (object)new List<object> { face.Started, new List<object> { Plain(face.From[0]), Plain(face.From[1]) }, face.Length }) },
                { "face_states", TargetsOf((Dictionary<object, string>)typeof(PopupWindow).GetField("faceStates", Hidden).GetValue(popup),
                                           state => (object)state) },
                { "openings", held.Openings == null ? null : new List<object>(held.Openings) },
            };
        }
    }
}

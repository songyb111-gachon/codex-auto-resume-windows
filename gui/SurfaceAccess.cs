// Codex Auto Resume - what a screen reader is told of the popup, the icon's drawn menu and the tip card (v0.6.27, S6.3e).
//
// ui/popup/access.py ported call for call (B13): the pure half - accessible_items, switch_name, pick, changes - and the
// client object MSAA is handed for WM_GETOBJECT (OBJID_CLIENT), built by hand as the reference builds it through ctypes:
// IUnknown's three, IDispatch's four (not implemented) and IAccessible's twenty-one, in that order, answering only the
// three interfaces the reference answers, never freed while its window lives, every method but AddRef and Release turning
// an exception into E_FAIL. PopupAccessible, MenuAccessible (menuwindow.py's) and TipAccessible (tipcard.py's) are one
// object over three sources. x64 only, as the host is: a VARIANT argument arrives as a pointer to the caller's copy.
//
// Attach(...) fills the hooks the windows keep for it (PopupWindow.Accessible/Speaking, MenuWindow.Accessible/Speaking/
// Telling, TipCard.Accessible, SurfaceAccessHooks.Disconnecting). Nothing here decides anything: a child's default action
// is the window's own click on the target that was drawn.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal static class SurfaceAccess
    {
        internal static readonly Dictionary<string, int> Roles = new Dictionary<string, int> {
            { "dialog", 0x12 }, { "text", 0x29 }, { "row", 0x22 }, { "switch", 0x2C }, { "button", 0x2B }, { "menu", 0x0B },
            { "menuitem", 0x0C }, { "separator", 0x15 } };
        internal static readonly Dictionary<string, int> States = new Dictionary<string, int> {
            { "unavailable", 0x1 }, { "focused", 0x4 }, { "checked", 0x10 }, { "hot", 0x80 }, { "focusable", 0x100000 },
            { "haspopup", 0x40000000 }, { "readonly", 0x40 } };
        internal const int OBJID_CLIENT = -4, OBJID_WINDOW = 0, CHILDID_SELF = 0, WM_GETOBJECT = 0x003D;
        internal const int EVENT_FOCUS = 0x8005, EVENT_REORDER = 0x8004, EVENT_STATECHANGE = 0x800A, EVENT_NAMECHANGE = 0x800C;
        internal const int S_OK = 0, S_FALSE = 1;
        internal const int E_NOINTERFACE = -2147467262, E_NOTIMPL = -2147467263, E_FAIL = -2147467259;
        internal const int E_INVALIDARG = -2147024809, DISP_E_MEMBERNOTFOUND = -2147352573;
        internal const int VT_EMPTY = 0, VT_I4 = 3;
        internal const int ROLE_SYSTEM_TOOLTIP = 0x0D, STATE_SYSTEM_READONLY = 0x40;
        private static readonly int[] NavigateNext = { 2, 4, 5 }, NavigatePrevious = { 1, 3, 6 };
        private const int NavigateFirst = 7, NavigateLast = 8;
        private static readonly string[] PickedFirst = { "switch", "button" }, Passing = { "focused", "hot" };
        internal static readonly Guid IidUnknown = new Guid(0x00000000, 0x0000, 0x0000, 0xC0, 0, 0, 0, 0, 0, 0, 0x46);
        internal static readonly Guid IidDispatch = new Guid(0x00020400, 0x0000, 0x0000, 0xC0, 0, 0, 0, 0, 0, 0, 0x46);
        internal static readonly Guid IidAccessible = new Guid(0x618736E0, 0x3C3D, 0x11CF, 0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71);

        // ------------------------------------------------------------------ the pure half
        private static object Field(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) ? value : null;
        }

        /// Python's == between two targets (tuples, as lists here) or anything else.
        internal static bool Same(object one, object other)
        {
            var first = one as List<object>;
            var second = other as List<object>;
            if (first != null && second != null)
            {
                if (first.Count != second.Count) return false;
                for (int index = 0; index < first.Count; index++)
                    if (!Same(first[index], second[index])) return false;
                return true;
            }
            if (one == null || other == null) return one == null && other == null;
            if ((one is double || one is int || one is long) && (other is double || other is int || other is long))
                return Convert.ToDouble(one) == Convert.ToDouble(other);
            return one.Equals(other);
        }

        private static int[] Lookup(List<KeyValuePair<object, int[]>> pairs, object key)
        {
            if (pairs == null) return null;
            int[] found = null;
            foreach (KeyValuePair<object, int[]> pair in pairs)
                if (Same(pair.Key, key)) found = pair.Value;        // dict(): the last one wins
            return found;
        }

        /// accessible_items: the popup's children for a screen reader, in the order it draws them.
        internal static List<Dictionary<string, object>> AccessibleItems(Dictionary<string, object> vm, SurfacePlan plan, object focus = null,
                                                                       object hover = null, IDictionary<string, object> strings = null)
        {
            var items = new List<Dictionary<string, object>>();
            if (vm == null || vm.Count == 0 || plan == null) return items;
            var texts = new List<PlanItem>();
            foreach (PlanItem item in plan.Items) if (item.Kind == "text") texts.Add(item);
            Func<string, int[]> textRect = value =>
            {
                foreach (PlanItem item in texts) if ((string)item.Get("text") == value) return (int[])item.Rect.Clone();
                return null;
            };
            Action<string, object, int[], object, object, List<string>, object, object> add = (role, name, rect, value, description, states, target, action) =>
            {
                var set = new SortedSet<string>(states, StringComparer.Ordinal);
                if (target != null)
                {
                    set.Add("focusable");
                    if (Same(target, focus)) set.Add("focused");
                    if (Same(target, hover)) set.Add("hot");
                }
                else set.Add("readonly");
                items.Add(new Dictionary<string, object> {
                    { "role", role }, { "name", SurfaceMath.Truthy(name) ? name : "" }, { "value", value }, { "description", description },
                    { "states", new List<string>(set) }, { "rect", rect }, { "target", target }, { "action", action } });
            };
            var labels = new List<PlanItem>();
            var values = new List<PlanItem>();
            foreach (PlanItem item in texts)
            {
                if ((string)item.Get("role") == "label") labels.Add(item);
                if ((string)item.Get("role") == "value") values.Add(item);
            }
            var counts = Field(vm, "counts") as List<object>;
            if (counts != null)
                for (int index = 0; index < counts.Count; index++)
                {
                    var pair = (List<object>)counts[index];
                    int[] rect = null;
                    if (index < labels.Count && index < values.Count)
                    {
                        int[] first = labels[index].Rect, second = values[index].Rect;
                        rect = new[] { Math.Min(first[0], second[0]), first[1], Math.Max(first[2], second[2]), second[3] };
                    }
                    add("text", pair[0], rect, pair[1], null, new List<string>(), null, null);
                }
            var tasks = Field(vm, "tasks") as List<object>;
            if (tasks != null)
                foreach (object entry in tasks)
                {
                    var task = (Dictionary<string, object>)entry;
                    object key = Field(task, "interruption_id");
                    add("row", Field(task, "name"), Lookup(plan.Rows, key), Field(task, "status"), Field(task, "reason"),
                        new List<string>(), null, null);
                    var target = new SurfaceTarget("check", key);
                    bool on = SurfaceMath.Truthy(Field(task, "checked"));
                    var states = new List<string>();
                    if (on) states.Add("checked");
                    if (SurfaceMath.Truthy(Field(task, "busy"))) states.Add("unavailable");
                    add("switch", SwitchName(task), Lookup(plan.Targets, target), null, null, states, target,
                        PopupWords.Say(strings, on ? "popup.a11y_off" : "popup.a11y_on"));
                }
            object error = Field(vm, "error");
            foreach (object note in new[] { Field(vm, "more"), SurfaceMath.Truthy(error) ? error : Field(vm, "empty"), Field(vm, "zero_note"),
                                            Field(vm, "observe_note"), Field(vm, "usage_note"), Field(vm, "notice") })
                if (SurfaceMath.Truthy(note)) add("text", note, textRect(note as string), null, null, new List<string>(), null, null);
            foreach (object[] button in new[] { new object[] { "toggle", Field(vm, "toggle_text"), Field(vm, "toggle_busy") },
                                                new object[] { "dashboard", Field(vm, "dashboard_text"), false } })
            {
                var target = new SurfaceTarget((string)button[0]);
                add("button", button[1], Lookup(plan.Targets, target), null, null,
                    SurfaceMath.Truthy(button[2]) ? new List<string> { "unavailable" } : new List<string>(), target,
                    PopupWords.Say(strings, "popup.a11y_press"));
            }
            return items;
        }

        /// switch_name: the switch's label and its task's name, "Auto-resume: Docs".
        internal static string SwitchName(Dictionary<string, object> task)
        {
            string label = Field(task, "check_label") as string ?? "", name = Field(task, "name") as string ?? "";
            return label.Length > 0 && name.Length > 0 ? label + ": " + name : (label.Length > 0 ? label : name);
        }

        /// pick: the child at client point (x, y), 1-based, or 0; a switch or a button before what it lies in.
        internal static int Pick(List<Dictionary<string, object>> items, int x, int y)
        {
            foreach (bool first in new[] { true, false })
                for (int index = 0; index < items.Count; index++)
                {
                    var rect = items[index]["rect"] as int[];
                    if (rect == null || (Array.IndexOf(PickedFirst, (string)items[index]["role"]) >= 0) != first) continue;
                    if (rect[0] <= x && x < rect[2] && rect[1] <= y && y < rect[3]) return index + 1;
                }
            return 0;
        }

        private static List<string> Kept(object states)
        {
            var kept = new List<string>();
            foreach (object state in (System.Collections.IEnumerable)states)
                if (Array.IndexOf(Passing, (string)state) < 0) kept.Add((string)state);
            return kept;
        }

        private static bool Focused(Dictionary<string, object> item)
        {
            foreach (object state in (System.Collections.IEnumerable)item["states"]) if ((string)state == "focused") return true;
            return false;
        }

        /// changes: the events a new set of children raises over the last one, as (event, child).
        internal static List<int[]> Changes(List<Dictionary<string, object>> before, List<Dictionary<string, object>> after)
        {
            var events = new List<int[]>();
            bool shaped = before.Count == after.Count;
            for (int index = 0; shaped && index < after.Count; index++)
                shaped = (string)before[index]["role"] == (string)after[index]["role"] && Same(before[index]["target"], after[index]["target"]);
            if (!shaped) events.Add(new[] { EVENT_REORDER, CHILDID_SELF });
            else
                for (int index = 0; index < after.Count; index++)
                {
                    if (!Same(before[index]["name"], after[index]["name"])) events.Add(new[] { EVENT_NAMECHANGE, index + 1 });
                    if (!Same(new List<object>(Kept(before[index]["states"])), new List<object>(Kept(after[index]["states"]))))
                        events.Add(new[] { EVENT_STATECHANGE, index + 1 });
                }
            int was = before.FindIndex(Focused), now = after.FindIndex(Focused);
            if (now >= 0 && (now != was || (events.Count > 0 && events[0][0] == EVENT_REORDER)))
                events.Add(new[] { EVENT_FOCUS, now + 1 });
            return events;
        }

        // ------------------------------------------------------------------ the windows' hooks
        [DllImport("oleacc.dll")] private static extern IntPtr LresultFromObject(ref Guid riid, IntPtr wParam, IntPtr unknown);
        [DllImport("oleacc.dll")] private static extern int CreateStdAccessibleObject(IntPtr hwnd, int objectId, ref Guid riid, out IntPtr found);
        [DllImport("oleaut32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr SysAllocString(string text);
        [DllImport("ole32.dll")] private static extern int CoInitializeEx(IntPtr reserved, uint model);
        [DllImport("ole32.dll")] private static extern int CoDisconnectObject(IntPtr unknown, uint reserved);
        [DllImport("user32.dll")] private static extern void NotifyWinEvent(uint winEvent, IntPtr hwnd, int objectId, int childId);
        [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hwnd, out SurfaceNative.RECT rect);
        private const uint COINIT_APARTMENTTHREADED = 0x2;
        private const int RPC_E_CHANGED_MODE = -2147417850;

        /// The client objects made, by surface: each kept for as long as its window lives (access.py's popup._access).
        private static readonly Dictionary<object, AccessObject> made = new Dictionary<object, AccessObject>();

        /// Fill the hooks of the host's surfaces: WM_GETOBJECT's answer, what changed told, the hold cut as a window goes.
        internal static void Attach(PopupWindow popup)
        {
            popup.Accessible = (window, wParam, lParam) => Answer(window, window.Hwnd, wParam, lParam, () => new PopupSource(window));
            popup.Speaking = window =>
            {
                List<Dictionary<string, object>> items = AccessibleItems(window.Vm, window.Plan, window.Keyboard ? window.Focus : null, null,
                                                                       window.Strings);
                var before = new List<Dictionary<string, object>>();
                foreach (object item in window.Spoken) before.Add((Dictionary<string, object>)item);
                window.Spoken = new List<object>(items);
                if (before.Count > 0) Announce(window.Hwnd, window.Visible, before, items);
            };
            SurfaceAccessHooks.Disconnecting = Disconnect;
        }

        internal static void Attach(MenuWindow menu)
        {
            menu.Accessible = (window, wParam, lParam) => Answer(window, window.Hwnd, wParam, lParam, () => new MenuSource(window));
            menu.Speaking = window =>
            {
                List<Dictionary<string, object>> items = window.AccessibleItems();
                List<Dictionary<string, object>> before = window.Spoken;
                window.Spoken = items;
                if (before.Count > 0) Announce(window.Hwnd, window.Visible, before, items);
            };
            menu.Telling = Tell;
            SurfaceAccessHooks.Disconnecting = Disconnect;
        }

        internal static void Attach(TipCard tip)
        {
            tip.Accessible = (card, wParam, lParam) => Answer(card, card.Hwnd, wParam, lParam, () => new TipSource(card));
            SurfaceAccessHooks.Disconnecting = Disconnect;
        }

        /// answer: WM_GETOBJECT for a surface - its client object when OBJID_CLIENT is asked for, else null (Windows answers).
        /// COM comes up single-threaded the first time; where it is up multithreaded the window is left to Windows.
        internal static IntPtr? Answer(object surface, IntPtr hwnd, IntPtr wParam, IntPtr lParam, Func<IAccessSource> source)
        {
            if (unchecked((int)(lParam.ToInt64() & 0xFFFFFFFF)) != OBJID_CLIENT || hwnd == IntPtr.Zero) return null;
            AccessObject found;
            if (!made.TryGetValue(surface, out found))
            {
                if (CoInitializeEx(IntPtr.Zero, COINIT_APARTMENTTHREADED) == RPC_E_CHANGED_MODE) return null;
                found = new AccessObject(source());
                made[surface] = found;
            }
            Guid iid = IidAccessible;
            return LresultFromObject(ref iid, wParam, found.Pointer);
        }

        /// disconnect: every screen reader's hold on the surface's object cut; the object is kept.
        internal static void Disconnect(object surface)
        {
            AccessObject found;
            if (!made.TryGetValue(surface, out found)) return;
            try
            {
                CoDisconnectObject(found.Pointer, 0);
            }
            catch (Exception)
            {
            }
        }

        /// tell: `winEvent` happened to the window (a menu opening or closing); nothing where it cannot be said.
        internal static void Tell(IntPtr hwnd, uint winEvent)
        {
            if (hwnd == IntPtr.Zero) return;
            try
            {
                NotifyWinEvent(winEvent, hwnd, OBJID_CLIENT, CHILDID_SELF);
            }
            catch (Exception)
            {
            }
        }

        /// announce: what changed on screen, told to whoever listens.
        internal static void Announce(IntPtr hwnd, bool visible, List<Dictionary<string, object>> before, List<Dictionary<string, object>> after)
        {
            if (hwnd == IntPtr.Zero || !visible) return;
            foreach (int[] change in Changes(before, after)) NotifyWinEvent((uint)change[0], hwnd, OBJID_CLIENT, change[1]);
        }

        // ------------------------------------------------------------------ what each surface answers from
        /// What the object reads from its window (PopupAccessible's popup, MenuAccessible's menu, TipAccessible's card).
        internal interface IAccessSource
        {
            IntPtr Hwnd { get; }
            bool Visible { get; }
            List<Dictionary<string, object>> Items();
            /// The object's own name and description (the child CHILDID_SELF).
            string SelfName();
            string SelfDescription();
            /// The item's description (the menu's and the popup's own; the tip's is always none).
            object Description(Dictionary<string, object> item);
            /// The role of the object itself, or of a child; null: as the generic object answers.
            int Role(Dictionary<string, object> item);
            /// The state of a valid child or the object; null: the generic answer.
            int? State(Dictionary<string, object> item);
            /// Where its (0, 0) is on its plan.
            int[] Offset();
            void Activate(object target);
        }

        private sealed class PopupSource : IAccessSource
        {
            private readonly PopupWindow popup;
            internal PopupSource(PopupWindow popup) { this.popup = popup; }
            public IntPtr Hwnd { get { return popup.Hwnd; } }
            public bool Visible { get { return popup.Visible; } }
            public List<Dictionary<string, object>> Items()
            {
                return AccessibleItems(popup.Vm, popup.Plan, popup.Keyboard ? popup.Focus : null, popup.Hover, popup.Strings);
            }
            public string SelfName() { return popup.Vm != null && popup.Vm.Count > 0 ? Field(popup.Vm, "title") as string : null; }
            public string SelfDescription() { return popup.Vm != null && popup.Vm.Count > 0 ? Field(popup.Vm, "state_text") as string : null; }
            public object Description(Dictionary<string, object> item) { return item["description"]; }
            public int Role(Dictionary<string, object> item) { return Roles[item == null ? "dialog" : (string)item["role"]]; }
            public int? State(Dictionary<string, object> item) { return null; }
            public int[] Offset() { return popup.ClientOffset(); }
            public void Activate(object target) { popup.Activate(target); }
        }

        private sealed class MenuSource : IAccessSource
        {
            private readonly MenuWindow menu;
            internal MenuSource(MenuWindow menu) { this.menu = menu; }
            public IntPtr Hwnd { get { return menu.Hwnd; } }
            public bool Visible { get { return menu.Visible; } }
            public List<Dictionary<string, object>> Items() { return menu.AccessibleItems(); }
            public string SelfName() { return PopupWords.Say(menu.Strings, "tray.title"); }
            public string SelfDescription() { return null; }
            public object Description(Dictionary<string, object> item) { return item["description"]; }
            public int Role(Dictionary<string, object> item) { return Roles[item == null ? "menu" : (string)item["role"]]; }
            public int? State(Dictionary<string, object> item) { return null; }
            public int[] Offset() { return new[] { 0, 0 }; }
            public void Activate(object target) { menu.Activate(Convert.ToInt32(target)); }
        }

        private sealed class TipSource : IAccessSource
        {
            private readonly TipCard tip;
            internal TipSource(TipCard tip) { this.tip = tip; }
            public IntPtr Hwnd { get { return tip.Hwnd; } }
            public bool Visible { get { return tip.Visible; } }
            public List<Dictionary<string, object>> Items() { return new List<Dictionary<string, object>>(); }
            public string SelfName() { return tip.Text; }
            public string SelfDescription() { return null; }
            public object Description(Dictionary<string, object> item) { return null; }
            public int Role(Dictionary<string, object> item) { return ROLE_SYSTEM_TOOLTIP; }
            public int? State(Dictionary<string, object> item) { return STATE_SYSTEM_READONLY; }
            public int[] Offset() { return new[] { 0, 0 }; }
            public void Activate(object target) { }
        }

        // ------------------------------------------------------------------ the object MSAA is handed
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int Query(IntPtr self, IntPtr riid, IntPtr found);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate uint Counted(IntPtr self);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int OneOut(IntPtr self, IntPtr found);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int TypeInfo(IntPtr self, uint index, uint locale, IntPtr found);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int Names(IntPtr self, IntPtr riid, IntPtr names, uint count, uint locale, IntPtr ids);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int Invoked(IntPtr self, int id, IntPtr riid, uint locale, ushort flags, IntPtr parameters, IntPtr result, IntPtr exception, IntPtr wrong);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int OfChild(IntPtr self, IntPtr child, IntPtr found);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int HelpTopic(IntPtr self, IntPtr file, IntPtr child, IntPtr topic);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int Selecting(IntPtr self, int flags, IntPtr child);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int Locating(IntPtr self, IntPtr left, IntPtr top, IntPtr width, IntPtr height, IntPtr child);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int Navigating(IntPtr self, int direction, IntPtr child, IntPtr found);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int Hitting(IntPtr self, int x, int y, IntPtr found);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate int Defaulting(IntPtr self, IntPtr child);

        /// PopupAccessible: one per surface, made the first time a screen reader asks, answered on the UI thread.
        internal sealed class AccessObject
        {
            private readonly IAccessSource source;
            private readonly List<Delegate> callbacks = new List<Delegate>();
            internal readonly IntPtr Pointer;
            internal int References = 1;

            internal AccessObject(IAccessSource source)
            {
                this.source = source;
                Delegate[] methods = {
                    new Query(QueryInterface), new Counted(AddRef), new Counted(Release), new OneOut(TypeInfoCount),
                    new TypeInfo((self, index, locale, found) => E_NOTIMPL),
                    new Names((self, riid, names, count, locale, ids) => E_NOTIMPL),
                    new Invoked((self, id, riid, locale, flags, parameters, result, exception, wrong) => E_NOTIMPL),
                    new OneOut(Guarded<IntPtr>(Parent)), new OneOut(Guarded<IntPtr>(ChildCount)),
                    new OfChild(Guarded2(Child)), new OfChild(Guarded2(Name)), new OfChild(Guarded2(Value)),
                    new OfChild(Guarded2(Description)), new OfChild(Guarded2(Role)), new OfChild(Guarded2(State)),
                    new OfChild(Guarded2(Nothing)), new HelpTopic((self, file, child, topic) => Safe(() => HelpTopicOf(file, topic))),
                    new OfChild(Guarded2(Nothing)), new OneOut(Guarded<IntPtr>(Focus)), new OneOut(Guarded<IntPtr>(Selection)),
                    new OfChild(Guarded2(DefaultAction)), new Selecting((self, flags, child) => DISP_E_MEMBERNOTFOUND),
                    new Locating((self, left, top, width, height, child) => Safe(() => Location(left, top, width, height, child))),
                    new Navigating((self, direction, child, found) => Safe(() => Navigate(direction, child, found))),
                    new Hitting((self, x, y, found) => Safe(() => HitTest(x, y, found))),
                    new Defaulting((self, child) => Safe(() => DoDefaultAction(child))),
                    new OfChild((self, child, value) => E_NOTIMPL), new OfChild((self, child, value) => E_NOTIMPL),
                };
                IntPtr table = Marshal.AllocHGlobal(IntPtr.Size * methods.Length);
                for (int index = 0; index < methods.Length; index++)
                {
                    callbacks.Add(methods[index]);
                    Marshal.WriteIntPtr(table, index * IntPtr.Size, Marshal.GetFunctionPointerForDelegate(methods[index]));
                }
                Pointer = Marshal.AllocHGlobal(IntPtr.Size);
                Marshal.WriteIntPtr(Pointer, table);
            }

            private static int Safe(Func<int> body)
            {
                try
                {
                    return body();
                }
                catch (Exception)
                {
                    return E_FAIL;
                }
            }

            private static Func<IntPtr, IntPtr, int> Guarded<T>(Func<IntPtr, int> body)
            {
                return (self, found) => Safe(() => body(found));
            }

            private static Func<IntPtr, IntPtr, IntPtr, int> Guarded2(Func<IntPtr, IntPtr, int> body)
            {
                return (self, child, found) => Safe(() => body(child, found));
            }

            // ---- IUnknown and IDispatch
            private int QueryInterface(IntPtr self, IntPtr riid, IntPtr found)
            {
                if (found == IntPtr.Zero) return E_INVALIDARG;
                var wanted = (Guid)Marshal.PtrToStructure(riid, typeof(Guid));
                if (wanted == IidUnknown || wanted == IidDispatch || wanted == IidAccessible)
                {
                    Marshal.WriteIntPtr(found, Pointer);
                    References += 1;
                    return S_OK;
                }
                Marshal.WriteIntPtr(found, IntPtr.Zero);
                return E_NOINTERFACE;
            }

            private uint AddRef(IntPtr self)
            {
                References += 1;
                return (uint)References;
            }

            private uint Release(IntPtr self)
            {
                References = Math.Max(0, References - 1);   // never freed here: kept for as long as its window lives
                return (uint)References;
            }

            private int TypeInfoCount(IntPtr self, IntPtr found)
            {
                if (found != IntPtr.Zero) Marshal.WriteInt32(found, 0);
                return S_OK;
            }

            // ---- what is asked about
            /// _item: (child id, item); item null for the object itself; child null for an id that is not a child.
            private int? Item(IntPtr variant, out Dictionary<string, object> item)
            {
                item = null;
                if (variant == IntPtr.Zero || Marshal.ReadInt16(variant) != VT_I4) return null;
                int child = Marshal.ReadInt32(variant, 8);
                if (child == CHILDID_SELF) return CHILDID_SELF;
                List<Dictionary<string, object>> items = source.Items();
                if (child < 1 || child > items.Count) return null;
                item = items[child - 1];
                return child;
            }

            private static int Number(IntPtr found, int number)
            {
                Marshal.WriteInt16(found, 0, VT_I4);
                Marshal.WriteInt32(found, 8, number);
                return S_OK;
            }

            private static int Empty(IntPtr found)
            {
                Marshal.WriteInt16(found, 0, VT_EMPTY);
                Marshal.WriteInt32(found, 8, 0);
                return S_FALSE;
            }

            private int Text(IntPtr child, IntPtr found, Func<Dictionary<string, object>, object> read)
            {
                Marshal.WriteIntPtr(found, IntPtr.Zero);
                Dictionary<string, object> item;
                if (Item(child, out item) == null) return E_INVALIDARG;
                object value = read(item);
                if (!SurfaceMath.Truthy(value)) return S_FALSE;
                var text = value as string;
                // SysAllocString takes a string only: anything else failed in the reference's ctypes call (E_FAIL).
                if (text == null) throw new ArgumentException("not a string");
                Marshal.WriteIntPtr(found, SysAllocString(text));
                return S_OK;
            }

            // ---- IAccessible
            private int Parent(IntPtr found)
            {
                Marshal.WriteIntPtr(found, IntPtr.Zero);
                IntPtr hwnd = source.Hwnd;
                if (hwnd == IntPtr.Zero) return S_FALSE;
                Guid iid = IidDispatch;
                IntPtr parent;
                if (CreateStdAccessibleObject(hwnd, OBJID_WINDOW, ref iid, out parent) != 0) return S_FALSE;
                Marshal.WriteIntPtr(found, parent);
                return S_OK;
            }

            private int ChildCount(IntPtr found)
            {
                Marshal.WriteInt32(found, source.Items().Count);
                return S_OK;
            }

            private int Child(IntPtr child, IntPtr found)
            {
                Dictionary<string, object> item;
                int? which = Item(child, out item);
                Marshal.WriteIntPtr(found, IntPtr.Zero);
                return which == null ? E_INVALIDARG : S_FALSE;        // every child is a simple element
            }

            private int Name(IntPtr child, IntPtr found) { return Text(child, found, item => item == null ? source.SelfName() : item["name"]); }
            private int Value(IntPtr child, IntPtr found) { return Text(child, found, item => item == null ? null : item["value"]); }
            private int Description(IntPtr child, IntPtr found)
            {
                return Text(child, found, item => item == null ? source.SelfDescription() : source.Description(item));
            }
            private int DefaultAction(IntPtr child, IntPtr found) { return Text(child, found, item => item == null ? null : item["action"]); }
            private int Nothing(IntPtr child, IntPtr found) { return Text(child, found, item => null); }

            private static int HelpTopicOf(IntPtr file, IntPtr topic)
            {
                Marshal.WriteIntPtr(file, IntPtr.Zero);
                Marshal.WriteInt32(topic, 0);
                return S_FALSE;
            }

            private int Role(IntPtr child, IntPtr found)
            {
                Dictionary<string, object> item;
                if (Item(child, out item) == null) return E_INVALIDARG;
                return Number(found, source.Role(item));
            }

            private int State(IntPtr child, IntPtr found)
            {
                Dictionary<string, object> item;
                if (Item(child, out item) == null) return E_INVALIDARG;
                int? fixedState = source.State(item);
                if (fixedState.HasValue) return Number(found, fixedState.Value);
                var states = new List<string>();
                if (item == null)
                {
                    states.Add("focusable");
                    bool anyFocused = false;
                    foreach (Dictionary<string, object> entry in source.Items()) anyFocused |= Focused(entry);
                    if (Foreground() && !anyFocused) states.Add("focused");
                }
                else foreach (object state in (System.Collections.IEnumerable)item["states"]) states.Add((string)state);
                int value = 0;
                foreach (string state in states) value |= States[state];
                return Number(found, value);
            }

            private bool Foreground()
            {
                IntPtr hwnd = source.Hwnd;
                return hwnd != IntPtr.Zero && source.Visible && SurfaceNative.GetForegroundWindow() == hwnd;
            }

            private int Focus(IntPtr found)
            {
                List<Dictionary<string, object>> items = source.Items();
                for (int index = 0; index < items.Count; index++)
                    if (Focused(items[index])) return Number(found, index + 1);
                return Foreground() ? Number(found, CHILDID_SELF) : Empty(found);
            }

            private int Selection(IntPtr found) { return Empty(found); }

            private int Location(IntPtr left, IntPtr top, IntPtr width, IntPtr height, IntPtr child)
            {
                Dictionary<string, object> item;
                int? which = Item(child, out item);
                IntPtr hwnd = source.Hwnd;
                if (which == null || hwnd == IntPtr.Zero) return E_INVALIDARG;
                int[] box;
                using (new SurfaceNative.PerMonitorDpi())
                {
                    if (item == null)
                    {
                        SurfaceNative.RECT rect;
                        GetWindowRect(hwnd, out rect);
                        box = new[] { rect.Left, rect.Top, rect.Right, rect.Bottom };
                    }
                    else if (item["rect"] == null)
                    {
                        Marshal.WriteInt32(left, 0);
                        Marshal.WriteInt32(top, 0);
                        Marshal.WriteInt32(width, 0);
                        Marshal.WriteInt32(height, 0);
                        return S_FALSE;
                    }
                    else
                    {
                        var rect = (int[])item["rect"];
                        int[] offset = source.Offset();
                        var corner = new SurfaceNative.POINT { X = rect[0] - offset[0], Y = rect[1] - offset[1] };
                        SurfaceNative.ClientToScreen(hwnd, ref corner);
                        box = new[] { corner.X, corner.Y, corner.X + rect[2] - rect[0], corner.Y + rect[3] - rect[1] };
                    }
                }
                Marshal.WriteInt32(left, box[0]);
                Marshal.WriteInt32(top, box[1]);
                Marshal.WriteInt32(width, box[2] - box[0]);
                Marshal.WriteInt32(height, box[3] - box[1]);
                return S_OK;
            }

            private int Navigate(int direction, IntPtr child, IntPtr found)
            {
                Dictionary<string, object> item;
                int? which = Item(child, out item);
                if (which == null) return E_INVALIDARG;
                int count = source.Items().Count;
                if (which == CHILDID_SELF && (direction == NavigateFirst || direction == NavigateLast))
                    return count > 0 ? Number(found, direction == NavigateFirst ? 1 : count) : Empty(found);
                bool next = Array.IndexOf(NavigateNext, direction) >= 0, previous = Array.IndexOf(NavigatePrevious, direction) >= 0;
                if (which != CHILDID_SELF && (next || previous))
                {
                    int other = which.Value + (next ? 1 : -1);
                    return 1 <= other && other <= count ? Number(found, other) : Empty(found);
                }
                return which != CHILDID_SELF ? Empty(found) : DISP_E_MEMBERNOTFOUND;
            }

            private int HitTest(int x, int y, IntPtr found)
            {
                IntPtr hwnd = source.Hwnd;
                if (hwnd == IntPtr.Zero) return Empty(found);
                var point = new SurfaceNative.POINT { X = x, Y = y };
                using (new SurfaceNative.PerMonitorDpi())
                {
                    SurfaceNative.RECT rect;
                    GetWindowRect(hwnd, out rect);
                    if (!(rect.Left <= x && x < rect.Right && rect.Top <= y && y < rect.Bottom)) return Empty(found);
                    SurfaceNative.ScreenToClient(hwnd, ref point);
                }
                int[] offset = source.Offset();
                return Number(found, Pick(source.Items(), point.X + offset[0], point.Y + offset[1]));
            }

            private int DoDefaultAction(IntPtr child)
            {
                Dictionary<string, object> item;
                int? which = Item(child, out item);
                if (which == null || item == null || item["target"] == null)
                    return which != null ? DISP_E_MEMBERNOTFOUND : E_INVALIDARG;
                foreach (object state in (System.Collections.IEnumerable)item["states"]) if ((string)state == "unavailable") return S_OK;
                source.Activate(item["target"]);
                return S_OK;
            }

            /// The probe's walk of one child: name, value, description and default action as [hr, text]; role and state as
            /// [hr, vt, value]; navigate up, down, first and last as [hr, vt, value] - each through the method the vtable
            /// holds, with a VARIANT of VT_I4 `child`.
            internal List<object> Walk(int child)
            {
                var row = new List<object> { child };
                IntPtr variant = Marshal.AllocHGlobal(24), found = Marshal.AllocHGlobal(24);
                try
                {
                    for (int at = 0; at < 24; at++) Marshal.WriteByte(variant, at, 0);
                    Marshal.WriteInt16(variant, 0, VT_I4);
                    Marshal.WriteInt32(variant, 8, child);
                    foreach (int slot in new[] { 10, 11, 12, 20 })
                    {
                        Marshal.WriteIntPtr(found, IntPtr.Zero);
                        int code = ((OfChild)callbacks[slot])(Pointer, variant, found);
                        IntPtr text = Marshal.ReadIntPtr(found);
                        row.Add(new List<object> { code, text == IntPtr.Zero ? null : Marshal.PtrToStringBSTR(text) });
                    }
                    foreach (int direction in new[] { 0, 0, 1, 2, 7, 8 })
                    {
                        for (int at = 0; at < 24; at++) Marshal.WriteByte(found, at, 0);
                        int code;
                        if (row.Count == 5) code = ((OfChild)callbacks[13])(Pointer, variant, found);
                        else if (row.Count == 6) code = ((OfChild)callbacks[14])(Pointer, variant, found);
                        else code = ((Navigating)callbacks[23])(Pointer, direction, variant, found);
                        row.Add(new List<object> { code, (int)Marshal.ReadInt16(found), Marshal.ReadInt32(found, 8) });
                    }
                }
                finally
                {
                    Marshal.FreeHGlobal(variant);
                    Marshal.FreeHGlobal(found);
                }
                return row;
            }

            internal int Count()
            {
                IntPtr found = Marshal.AllocHGlobal(4);
                try
                {
                    ((OneOut)callbacks[8])(Pointer, found);
                    return Marshal.ReadInt32(found);
                }
                finally
                {
                    Marshal.FreeHGlobal(found);
                }
            }
        }

        /// The probe's record of what a screen reader is told of the popup now: its children (targets as lists), the child
        /// each one's centre picks, the events since `before`, and the client object's answers child by child.
        internal static Dictionary<string, object> Probe(PopupWindow popup, ref List<Dictionary<string, object>> before)
        {
            List<Dictionary<string, object>> items = AccessibleItems(popup.Vm, popup.Plan, popup.Keyboard ? popup.Focus : null, popup.Hover,
                                                                   popup.Strings);
            var shown = new List<object>();
            var picks = new List<object>();
            foreach (Dictionary<string, object> item in items)
            {
                var copy = new Dictionary<string, object>(item);
                var target = item["target"] as SurfaceTarget;
                if (target != null) copy["target"] = target.ToList();
                shown.Add(copy);
                var rect = item["rect"] as int[];
                picks.Add(rect == null ? null : (object)Pick(items, SurfaceMath.Div(rect[0] + rect[2], 2), SurfaceMath.Div(rect[1] + rect[3], 2)));
            }
            var changes = new List<object>();
            foreach (int[] change in Changes(before, items)) changes.Add(new List<object> { change[0], change[1] });
            before = items;
            var target_ = new AccessObject(new PopupSource(popup));
            var answers = new List<object>();
            for (int child = 0; child < items.Count + 2; child++) answers.Add(target_.Walk(child));
            return new Dictionary<string, object> { { "items", shown }, { "picks", picks }, { "changes", changes },
                                                    { "count", target_.Count() }, { "answers", answers } };
        }
    }
}

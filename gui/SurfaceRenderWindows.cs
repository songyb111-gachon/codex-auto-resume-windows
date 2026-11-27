// Codex Auto Resume - the render mode's cases for the surfaces' windows and their words (v0.6.27, S6.3c).
//
// The other half of SurfaceRender (gui/SurfaceRender.cs): cases that hold what the windows decide - the icon's words,
// where Windows keeps the icon - against the reference, as comparison A holds the plans. Nothing here makes a window
// anybody sees, posts an action or writes anything but the answer.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal static partial class SurfaceRender
    {
        /// A case of the windows' half, or false when `surface` is none of them.
        private static bool WindowCase(string surface, Dictionary<string, object> task, Dictionary<string, TableTextCalc> tables,
                                       out object plan)
        {
            if (surface == "tray_words")
            {
                plan = TrayWordsCase(task);
                return true;
            }
            if (surface == "tray_place")
            {
                plan = TrayPlaceCase(task);
                return true;
            }
            if (surface == "tip_window")
            {
                plan = TipWindowCase(task);
                return true;
            }
            if (surface == "popup_window")
            {
                plan = PopupWindowCase(task);
                return true;
            }
            if (surface == "menu_window")
            {
                plan = MenuWindowCase(task);
                return true;
            }
            if (surface == "card_stack")
            {
                plan = CardStackCase(task);
                return true;
            }
            if (surface == "tray_icon")
            {
                plan = TrayIconCase(task);
                return true;
            }
            if (surface == "host_surfaces")
            {
                plan = HostSurfacesCase(task);
                return true;
            }
            plan = null;
            return false;
        }

        /// The icon's words from a snapshot: tooltip_parts, tooltip, tooltip_joined and meter_line.
        private static object TrayWordsCase(Dictionary<string, object> task)
        {
            var snapshot = Field(task, "snapshot") as Dictionary<string, object>;
            var strings = (Dictionary<string, object>)task["strings"];
            double now = (double)task["now"];
            string edition = Field(task, "edition") as string;
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
    
        /// Windows' settings for the icon as a job gives them, one registry state per step.
        private sealed class JobKeys : ICurrentUserKeys
        {
            internal Dictionary<string, object> Keys = new Dictionary<string, object>();

            public List<string> Subkeys(string path)
            {
                var key = Field(Keys, path) as Dictionary<string, object>;
                var names = Field(key, "subkeys") as List<object>;
                if (names == null) throw new System.IO.FileNotFoundException(path);
                return names.ConvertAll(name => (string)name);
            }

            public object Value(string path, string name)
            {
                var key = Field(Keys, path) as Dictionary<string, object>;
                if (key == null) return null;
                if (SurfaceMath.Truthy(Field(key, "broken"))) throw new UnauthorizedAccessException(path);
                return Field(Field(key, "values") as Dictionary<string, object>, name);
            }
        }

        /// The flyout's windows as a job gives them: [class, visible, cloaked or null for a failed question].
        private sealed class JobWindows : IOverflowWindows
        {
            internal List<object> Windows;

            public IntPtr FindWindowEx(IntPtr after, string className)
            {
                for (int at = (int)after; at < Windows.Count; at++)
                    if ((string)((List<object>)Windows[at])[0] == className) return new IntPtr(at + 1);
                return IntPtr.Zero;
            }

            public bool IsWindowVisible(IntPtr hwnd) { return (bool)((List<object>)Windows[(int)hwnd - 1])[1]; }

            public int Cloaked(IntPtr hwnd, out uint value)
            {
                object cloaked = ((List<object>)Windows[(int)hwnd - 1])[2];
                value = cloaked == null ? 0u : (uint)(double)cloaked;
                return cloaked == null ? -2147467259 : 0;
            }
        }

        /// IconPlacement over a run of registry states and clock readings, the paths compared, the flyout's windows.
        private static object TrayPlaceCase(Dictionary<string, object> task)
        {
            var keys = new JobKeys();
            double now = 0;
            var folders = (Dictionary<string, object>)task["folders"];
            var placement = new IconPlacement((string)task["executable"], (int)(double)task["uid"], keys,
                                              guid => Field(folders, guid) as string, () => now);
            var answers = new List<object>();
            foreach (object entry in (List<object>)task["steps"])
            {
                var step = (Dictionary<string, object>)entry;
                now = (double)step["clock"];
                keys.Keys = (Dictionary<string, object>)step["keys"];
                answers.Add(placement.Overflowed());
            }
            var paths = new List<object>();
            foreach (object path in (List<object>)task["paths"]) paths.Add(TrayPlace.SamePath((string)path));
            var open = new List<object>();
            foreach (object windows in (List<object>)task["overflow"])
                open.Add(TrayPlace.OverflowOpen(new JobWindows { Windows = (List<object>)windows }));
            return new Dictionary<string, object>
            {
                { "answers", answers }, { "executable", placement.Executable }, { "paths", paths }, { "open", open },
            };
        }

        [DllImport("user32.dll")]
        private static extern IntPtr SendMessageW(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

        private static void SystemColoursFrom(object system)
        {
            SurfaceRenderer.SystemColours = null;
            if (system == null) return;
            SurfaceRenderer.SystemColours = new Dictionary<string, int[]>();
            foreach (KeyValuePair<string, object> pair in (Dictionary<string, object>)system)
                SurfaceRenderer.SystemColours[pair.Key] = Ints(pair.Value);
        }

        /// The probe mode for the icon's card: a TipCard whose window is made and never shown (its pushes to the screen
        /// left out), driven by a script of the icon's calls, its own messages (sent to its window procedure) and the
        /// clocks; after each step what it is - shown, its alpha and fade, its frame timer, where it stands, its text and
        /// its picture by digest. And the live-path proof: the window's own picture against the render mode's DrawTip for
        /// the same parts at the same frame, byte for byte, with no GDI+ object left.
        private static object TipWindowCase(Dictionary<string, object> task)
        {
            SystemColoursFrom(Field(task, "system"));
            SurfaceFonts.Pinned = Field(task, "pinned") as string;
            var look = (List<object>)task["look"];
            SurfaceTheme.SetTheme(look[0]);
            SurfaceTheme.SetDesign(look[1]);
            bool contrast = (bool)look[2];
            bool reduced = (bool)task["reduced"];
            var screenValue = (Dictionary<string, object>)task["screen"];
            var screen = new TipCard.TipScreen
            {
                Box = Ints(screenValue["box"]), Dpi = (uint)(double)screenValue["dpi"], Work = Ints(screenValue["work"]),
                Monitor = Ints(screenValue["monitor"]),
            };
            var snapshot = Field(task, "snapshot") as Dictionary<string, object>;
            var strings = (Dictionary<string, object>)task["strings"];
            string edition = Field(task, "edition") as string;
            string letters = Field(task, "letters") as string;
            double wall = (double)task["now"];
            double clock = 1000.0;
            int[] pointer = null;
            bool held = false;
            var logged = new List<object>();
            int before = SurfaceGdip.GdipObjects;
            var steps = new List<object>();
            var proofs = new List<object>();
            try
            {
                var card = new TipCard(() => new TipCard.Content
                {
                    Parts = TrayWords.TooltipParts(snapshot, strings, wall, edition), Snapshot = snapshot, Strings = strings,
                    Locale = (string)task["locale"], Letters = letters,
                }, () => held, line => logged.Add(line), SurfaceMath.Truthy(Field(task, "days")));
                card.OnScreen = false;
                card.Monotonic = () => clock;
                card.Now = () => wall;
                card.Pointer = () => pointer;
                card.ScreenReader = (icon, point) => screen;
                card.AskContrast = () => contrast;
                card.AskReduced = () => reduced;
                card.AskAppsLight = () => (string)look[0] == "light";
                card.AskTextScale = () => (double)task["text_scale"];
                try
                {
                    foreach (object entry in (List<object>)task["script"])
                    {
                        var step = (List<object>)entry;
                        string op = (string)step[0];
                        object returned = null;
                        if (op == "show") card.Show();
                        else if (op == "hide") card.Hide(true);
                        else if (op == "leave") card.Hide(false);
                        else if (op == "clock") clock += (double)step[1];
                        else if (op == "pointer") pointer = step[1] == null ? null : Ints(step[1]);
                        else if (op == "held") held = (bool)step[1];
                        else if (op == "message")
                        {
                            // Sent to the window procedure on this thread: no message loop, no timer ever fires by itself.
                            double answer = SendMessageW(card.Hwnd, (uint)(double)step[1], new IntPtr((long)(double)step[2]),
                                                         IntPtr.Zero).ToInt64();
                            returned = step.Count > 3 && SurfaceMath.Truthy(step[3]) ? (object)answer : null;
                        }
                        else if (op == "proof")
                        {
                            byte[] window = card.Render().Pixels();
                            using (SurfaceRenderer renderer = SurfaceRenderer.Open())
                            {
                                renderer.Theme = SurfaceTheme.EffectiveTheme(SurfaceTheme.ThemeSetting, (string)look[0] == "light");
                                renderer.Design = SurfaceTheme.DesignSetting;
                                renderer.Contrast = contrast;
                                renderer.Letters = letters;
                                var parts = (Dictionary<string, object>)task["parts"];
                                string day = SurfaceRenderer.TipDay(Field(task, "day") as string, contrast, SurfaceTheme.DesignSetting);
                                SurfacePlan plan = renderer.TipLayout(parts, task["light"], card.Plan.Scale, (string)task["locale"], day);
                                byte[] render = renderer.DrawTip(plan, card.Frame()).Pixels();
                                proofs.Add(new List<object>
                                {
                                    Digest(window), Digest(render), Json.Write(Dump(plan)) == Json.Write(Dump(card.Plan)),
                                });
                            }
                            continue;
                        }
                        steps.Add(new Dictionary<string, object>
                        {
                            { "op", op }, { "visible", card.Visible }, { "alpha", card.Alpha }, { "fade", card.Fade },
                            { "frames", card.FrameRunning }, { "origin", card.Plan != null ? (object)card.Origin : null },
                            { "size", card.Plan != null ? (object)card.Plan.Size : null }, { "text", card.Text },
                            { "pixels", card.Renderer != null && card.Plan != null ? Digest(card.Renderer.Canvas.Pixels()) : null },
                            { "returned", returned },
                        });
                    }
                }
                finally
                {
                    card.Dispose();
                }
            }
            finally
            {
                SurfaceFonts.Pinned = null;
                SurfaceRenderer.SystemColours = null;
                SurfaceTheme.SetTheme("system");
                SurfaceTheme.SetDesign(null);
            }
            return new Dictionary<string, object>
            {
                { "steps", steps }, { "proofs", proofs }, { "log", logged }, { "left", SurfaceGdip.GdipObjects - before },
            };
        }

        /// What the probe's popup posts: each action and its fields, answered as the core answers a done action.
        private sealed class ProbeActions : IHostActions
        {
            internal readonly List<object> Posts = new List<object>();

            public string Post(string action, IDictionary<string, object> fields)
            {
                Posts.Add(new List<object> { action, fields });
                return "{\"ok\": true}";
            }
        }

        /// A row's drawn menu that records what it was asked to open and keeps its run, for the script to choose from.
        private sealed class ProbeMenu : IRowMenu
        {
            internal readonly List<object> Opened = new List<object>();
            internal Action<int> Run;

            public IntPtr Hwnd { get { return new IntPtr(0x7777); } }

            public bool Open(List<object> entries, Dictionary<string, object> strings, Action<int> run, int[] point, IntPtr owner,
                             Action onLeave)
            {
                Run = run;
                Opened.Add(new List<object> { Dump(entries), point });
                return true;
            }

            public void Close() { Opened.Add("close"); }

            public void Destroy() { Opened.Add("destroy"); }
        }

        /// The probe mode for the popup: a PopupWindow whose windows are made and never shown (every call that would reach
        /// the screen recorded by SurfaceScreen.Probe instead), driven by a script of the icon's calls, Windows' messages
        /// (sent to its window procedure), the clocks, and the core's snapshots and answers where the reference's model
        /// took them; after each step what it is and the calls it made. And the live-path proof: the window's own picture
        /// against the render mode's Draw of the same view, plan and frame, byte for byte, with no GDI+ object left.
        private static object PopupWindowCase(Dictionary<string, object> task)
        {
            SystemColoursFrom(Field(task, "system"));
            SurfaceFonts.Pinned = Field(task, "pinned") as string;
            var look = (List<object>)task["look"];
            SurfaceTheme.SetTheme(look[0]);
            SurfaceTheme.SetDesign(look[1]);
            SurfaceTheme.SetReduceMotion(false);
            bool contrast = (bool)look[2];
            bool reduced = (bool)task["reduced"];
            var screenValue = (Dictionary<string, object>)task["screen"];
            var strings = (Dictionary<string, object>)task["strings"];
            double wall = (double)task["now"];
            double clock = 1000.0;
            bool held = false;
            var logged = new List<object>();
            int before = SurfaceGdip.GdipObjects;
            var steps = new List<object>();
            var proofs = new List<object>();
            var calls = new List<string>();
            var works = new List<Action>();
            var views = new List<Dictionary<string, object>>();
            var actions = new ProbeActions();
            var menu = new ProbeMenu();
            var known = new Dictionary<long, string>();
            SurfaceScreen.Probe = calls;
            SurfaceScreen.Posted.Clear();
            SurfaceScreen.Keys.Clear();
            try
            {
                var spoken = new List<Dictionary<string, object>>();
                var popup = new PopupWindow(strings, (string)task["locale"], Field(task, "letters") as string,
                                            SurfaceMath.Truthy(Field(task, "days")), () => held);
                popup.Log = line => logged.Add(line);
                popup.Actions = actions;
                popup.Worker = work => works.Add(work);
                popup.MakeMenu = () => menu;
                popup.Monotonic = () => clock;
                popup.Now = () => wall;
                popup.ScreenReader = unused => new PopupWindow.PopupScreen
                {
                    Icon = Ints(screenValue["icon"]), Cursor = Ints(screenValue["cursor"]), Work = Ints(screenValue["work"]),
                    Monitor = Ints(screenValue["monitor"]), Dpi = (double)screenValue["dpi"],
                };
                popup.AskContrast = () => contrast;
                popup.AskReduced = () => reduced;
                popup.AskAppsLight = () => (string)look[0] == "light";
                popup.AskTextScale = () => (double)task["text_scale"];
                SurfaceScreen.Name = hwnd =>
                {
                    if (popup.Hwnd != IntPtr.Zero) known[popup.Hwnd.ToInt64()] = "card";
                    if (popup.Layers != null && popup.Layers.ShadowHwnd != IntPtr.Zero) known[popup.Layers.ShadowHwnd.ToInt64()] = "shadow";
                    string name;
                    return known.TryGetValue(hwnd.ToInt64(), out name) ? name : "0x" + hwnd.ToInt64().ToString("x");
                };
                Action pump = () =>
                {
                    for (int i = 0; i < 100 && SurfaceScreen.Posted.Count > 0; i++)
                    {
                        long[] posted = SurfaceScreen.Posted[0];
                        SurfaceScreen.Posted.RemoveAt(0);
                        if (posted[1] == -1) popup.Snapshot(views[(int)posted[2]]);
                        else popup.Message((int)posted[1], posted[2], posted[3], new IntPtr(posted[0]));
                    }
                };
                try
                {
                    foreach (object entry in (List<object>)task["script"])
                    {
                        var described = (Dictionary<string, object>)entry;
                        string op = (string)described["op"];
                        var step = (List<object>)described["do"];
                        string kind = (string)step[0];
                        calls.Clear();
                        menu.Opened.Clear();
                        actions.Posts.Clear();
                        object returned = null;
                        if (kind == "core")
                        {
                            popup.Snapshot((Dictionary<string, object>)step[1]);
                            continue;
                        }
                        if (kind == "show") popup.Show((bool)step[1], (bool)step[2]);
                        else if (kind == "select") popup.OnSelect((bool)step[1]);
                        else if (kind == "double") popup.OnDoubleClick();
                        else if (kind == "clock") clock += (double)step[1];
                        else if (kind == "held") held = (bool)step[1];
                        else if (kind == "shift") SurfaceScreen.Keys[0x10] = (short)((bool)step[1] ? -128 : 0);
                        else if (kind == "messages")
                        {
                            var answers = new List<object>();
                            foreach (object sent in (List<object>)step[1])
                            {
                                var one = (List<object>)sent;
                                answers.Add(popup.Message((int)(double)one[0], (long)(double)one[1], (long)(double)one[2]).ToInt64());
                            }
                            returned = answers;
                        }
                        else if (kind == "pump") pump();
                        else if (kind == "result")
                        {
                            var running = new List<Action>(works);
                            works.Clear();
                            int mark = SurfaceScreen.Posted.Count;
                            foreach (Action work in running) work();
                            List<long[]> answered = SurfaceScreen.Posted.GetRange(mark, SurfaceScreen.Posted.Count - mark);
                            SurfaceScreen.Posted.RemoveRange(mark, SurfaceScreen.Posted.Count - mark);
                            int next = 0;
                            foreach (object one in (List<object>)step[1])
                            {
                                var happened = (Dictionary<string, object>)one;
                                if (happened.ContainsKey("answer"))
                                {
                                    if (next < answered.Count) SurfaceScreen.Posted.Add(answered[next++]);
                                    else logged.Add("probe: an answer the reference took was never posted");
                                }
                                else
                                {
                                    views.Add((Dictionary<string, object>)happened["view"]);
                                    SurfaceScreen.Posted.Add(new long[] { 0, -1, views.Count - 1, 0 });
                                }
                            }
                            while (next < answered.Count) SurfaceScreen.Posted.Add(answered[next++]);
                            pump();
                        }
                        else if (kind == "choose")
                        {
                            if (menu.Run != null) menu.Run((int)(double)step[1]);
                        }
                        else if (kind == "strings")
                        {
                            // The core's snapshot in the new words comes before the window turns to its posted strings, as
                            // the reference's model has the new words by the time that message is handled.
                            popup.SetStrings((Dictionary<string, object>)step[1], (string)step[2], (string)step[3]);
                            views.Add((Dictionary<string, object>)step[4]);
                            SurfaceScreen.Posted.Insert(Math.Max(0, SurfaceScreen.Posted.Count - 1),
                                                        new long[] { 0, -1, views.Count - 1, 0 });
                        }
                        else if (kind == "proof")
                        {
                            popup.StaticDirty = true;
                            byte[] window = popup.Render().Pixels();
                            using (SurfaceRenderer renderer = SurfaceRenderer.Open())
                            {
                                renderer.Theme = popup.Theme;
                                renderer.Design = popup.Design;
                                renderer.Contrast = popup.Contrast;
                                renderer.Lone = popup.Card;
                                renderer.Letters = popup.Letters;
                                SurfacePlan plan = renderer.Layout(popup.Vm, popup.Plan.Scale, popup.Locale);
                                byte[] render = renderer.Draw(plan, popup.Frame(), popup.Hover, popup.Pressed,
                                                              popup.Keyboard ? popup.Focus : null, null, popup.SceneNowMs()).Pixels();
                                proofs.Add(new List<object>
                                {
                                    Digest(window), Digest(render), Json.Write(Dump(plan)) == Json.Write(Dump(popup.Plan)),
                                });
                            }
                            continue;
                        }
                        var kept = new List<object>();
                        foreach (string call in calls)
                            if (!call.StartsWith("PostMessageW card " + SurfaceNative.WM_POPUP_RESULT + " ")) kept.Add(call);
                        Func<object, object> target = value => value is SurfaceTarget ? ((SurfaceTarget)value).ToList() : value;
                        steps.Add(new Dictionary<string, object>
                        {
                            { "op", op }, { "visible", popup.Visible }, { "alpha", popup.Alpha }, { "below", popup.Below },
                            { "home", popup.Home }, { "card", popup.Card }, { "frames", popup.FrameRunning },
                            { "pending", popup.PendingShow != null }, { "hover", target(popup.Hover) },
                            { "pressed", target(popup.Pressed) }, { "focus", target(popup.Focus) }, { "keyboard", popup.Keyboard },
                            { "size", popup.Plan != null ? popup.Plan.Size : null },
                            { "painted", popup.PaintedPlan != null && popup.PaintedPlan == popup.Plan },
                            { "pixels", popup.Renderer != null && popup.Plan != null ? Digest(popup.Renderer.Canvas.Pixels()) : null },
                            { "calls", kept }, { "menus", new List<object>(menu.Opened) },
                            { "posts", new List<object>(actions.Posts) }, { "returned", returned },
                            { "sweeping", popup.Sweeping() }, { "dpi", popup.Dpi },
                            { "a11y", SurfaceAccess.Probe(popup, ref spoken) },
                        });
                    }
                }
                finally
                {
                    popup.Dispose();
                }
            }
            finally
            {
                SurfaceScreen.Probe = null;
                SurfaceScreen.Posted.Clear();
                SurfaceScreen.Keys.Clear();
                SurfaceFonts.Pinned = null;
                SurfaceRenderer.SystemColours = null;
                SurfaceTheme.SetTheme("system");
                SurfaceTheme.SetDesign(null);
            }
            return new Dictionary<string, object>
            {
                { "steps", steps }, { "proofs", proofs }, { "log", logged }, { "left", SurfaceGdip.GdipObjects - before },
            };
        }

        /// The probe mode for the drawn menu: a MenuWindow made and never shown (every call that would reach the screen
        /// recorded by SurfaceScreen.Probe instead), driven by a script of openings, its timers, keys, letters and the
        /// pointer (sent to its window procedure, or its submenu's); after each step what it and its submenu are, the
        /// calls, what was chosen and who was told it closed.
        private static object MenuWindowCase(Dictionary<string, object> task)
        {
            SystemColoursFrom(Field(task, "system"));
            SurfaceFonts.Pinned = Field(task, "pinned") as string;
            var look = (List<object>)task["look"];
            SurfaceTheme.SetTheme(look[0]);
            SurfaceTheme.SetDesign(look[1]);
            SurfaceTheme.SetReduceMotion(false);
            bool contrast = (bool)look[2];
            bool reduced = (bool)task["reduced"];
            var strings = (Dictionary<string, object>)task["strings"];
            double dpi = (double)task["dpi"];
            int[] work = Ints(task["work"]);
            var owner = new IntPtr((long)(double)task["owner"]);
            double clock = 1000.0;
            var logged = new List<object>();
            int before = SurfaceGdip.GdipObjects;
            var steps = new List<object>();
            var proofs = new List<object>();
            var calls = new List<string>();
            var known = new Dictionary<long, string>();
            SurfaceScreen.Probe = calls;
            SurfaceScreen.Posted.Clear();
            SurfaceScreen.Styles.Clear();
            SurfaceScreen.Foreground = IntPtr.Zero;
            SurfaceScreen.Grant = true;
            try
            {
                var menu = new MenuWindow(line => logged.Add(line));
                menu.Monotonic = () => clock;
                menu.ScreenReader = at => new MenuWindow.MenuScreen { Cursor = at ?? new[] { 960, 520 }, Dpi = dpi, Work = work };
                menu.AskContrast = () => contrast;
                menu.AskReduced = () => reduced;
                menu.AskAppsLight = () => (string)look[0] == "light";
                menu.AskTextScale = () => (double)task["text_scale"];
                SurfaceScreen.Name = hwnd =>
                {
                    if (menu.Hwnd != IntPtr.Zero) known[menu.Hwnd.ToInt64()] = "menu";
                    if (menu.Child != null && menu.Child.Hwnd != IntPtr.Zero) known[menu.Child.Hwnd.ToInt64()] = "child";
                    string name;
                    return known.TryGetValue(hwnd.ToInt64(), out name) ? name : "0x" + hwnd.ToInt64().ToString("x");
                };
                menu.Telling = (hwnd, winEvent) => calls.Add("NotifyWinEvent " + SurfaceScreen.Name(hwnd) + " " + winEvent);
                var chosen = new List<object>();
                var left = new List<object>();
                Func<MenuWindow, object> described = one =>
                {
                    if (one == null) return null;
                    return new Dictionary<string, object>
                    {
                        { "visible", one.Visible }, { "selected", one.Selected }, { "alpha", one.Alpha }, { "below", one.Below },
                        { "fade", one.FadeWay }, { "origin", one.Origin }, { "size", one.Plan != null ? one.Plan.Size : null },
                        { "pixels", one.Renderer != null && one.Plan != null ? Digest(one.Renderer.Canvas.Pixels()) : null },
                    };
                };
                try
                {
                    foreach (object entry in (List<object>)task["script"])
                    {
                        var described_ = (Dictionary<string, object>)entry;
                        string op = (string)described_["op"];
                        var step = (List<object>)described_["do"];
                        calls.Clear();
                        chosen.Clear();
                        left.Clear();
                        object returned = null;
                        if (op == "proof")
                        {
                            proofs.Add(new List<object> { MenuProof(menu), MenuProof(menu.Child) });
                            continue;
                        }
                        if (op == "open")
                            returned = menu.Open((List<object>)step[2], strings, (string)task["locale"], Field(task, "letters") as string,
                                                 id => chosen.Add(id), step[1] == null ? null : Ints(step[1]), owner,
                                                 () => left.Add(true));
                        else if (op == "clock") clock += (double)step[1];
                        else if (op == "grant") SurfaceScreen.Grant = (bool)step[1];
                        else
                        {
                            MenuWindow target = (string)step[1] == "child" ? menu.Child : menu;
                            var sent = (List<object>)step[2];
                            if (target != null && target.Hwnd != IntPtr.Zero)
                                returned = (long)target.Message((int)(double)sent[0], (long)(double)sent[1], (long)(double)sent[2]);
                        }
                        steps.Add(new Dictionary<string, object>
                        {
                            { "op", op }, { "menu", described(menu) }, { "child", described(menu.Child) },
                            { "calls", new List<string>(calls) }, { "chosen", new List<object>(chosen) },
                            { "left", new List<object>(left) }, { "returned", returned },
                        });
                    }
                }
                finally
                {
                    menu.Destroy();
                }
            }
            finally
            {
                SurfaceScreen.Probe = null;
                SurfaceScreen.Styles.Clear();
                SurfaceScreen.Foreground = IntPtr.Zero;
                SurfaceScreen.Grant = true;
                SurfaceFonts.Pinned = null;
                SurfaceRenderer.SystemColours = null;
                SurfaceTheme.SetTheme("system");
                SurfaceTheme.SetDesign(null);
            }
            return new Dictionary<string, object>
            {
                { "steps", steps }, { "proofs", proofs }, { "log", logged }, { "left", SurfaceGdip.GdipObjects - before },
            };
        }

        /// The live-path proof for one drawn menu (or its submenu): the window's own picture (Render, as its push draws it)
        /// against a fresh renderer's MenuLayout and DrawMenu of the same entries, scale, language, work area and item in
        /// hand - the render mode's - byte for byte, and the two plans equal. Null when it has no picture.
        private static object MenuProof(MenuWindow one)
        {
            if (one == null || one.Renderer == null || one.Plan == null) return null;
            byte[] window = one.Render().Pixels();
            using (SurfaceRenderer renderer = SurfaceRenderer.Open())
            {
                renderer.Theme = one.Theme;
                renderer.Design = one.Design;
                renderer.Contrast = one.Contrast;
                renderer.Letters = one.Letters;
                SurfacePlan plan = renderer.MenuLayout(one.Entries, one.Plan.Scale, one.Locale, one.Work[2] - one.Work[0]);
                byte[] render = renderer.DrawMenu(plan, one.Selected).Pixels();
                return new List<object> { Digest(window), Digest(render), Json.Write(Dump(plan)) == Json.Write(Dump(one.Plan)) };
            }
        }

        /// The probe mode for the notification cards together: a CardStack whose cards' windows are made and never shown
        /// (their pushes recorded by SurfaceScreen.Probe), driven by a script of notices, the stack's timers and the
        /// pointer on a card (sent to the window procedure); after each step every card's phase, place and marks, the
        /// frame timer, the calls and what was posted.
        private static object CardStackCase(Dictionary<string, object> task)
        {
            SystemColoursFrom(Field(task, "system"));
            SurfaceFonts.Pinned = Field(task, "pinned") as string;
            var whereValue = (Dictionary<string, object>)task["where"];
            var drawn = (Dictionary<string, object>)task["drawn"];
            var focuses = (List<object>)task["focuses"];
            double clock = 1000.0;
            int asked = 0;
            var logged = new List<object>();
            int before = SurfaceGdip.GdipObjects;
            var steps = new List<object>();
            var proofs = new List<object>();
            var notices = new Dictionary<NoticeCard, Dictionary<string, object>>();
            var calls = new List<string>();
            var actions = new ProbeActions();
            SurfaceScreen.Probe = calls;
            SurfaceScreen.Posted.Clear();
            try
            {
                var stack = new CardStack();
                stack.Log = line => logged.Add(line);
                stack.Actions = actions;
                stack.Worker = work => work();
                stack.Clock = () => clock;
                stack.Holding = () => (double)task["hold"];
                stack.Locate = () => new CardStack.CardScreen
                {
                    Anchor = IntsOrNull(whereValue["anchor"]), Dpi = (double)whereValue["dpi"], Work = Ints(whereValue["work"]),
                    Monitor = Ints(whereValue["monitor"]),
                };
                stack.Appearance = () => new Dictionary<string, object>(drawn);
                stack.Focus = () =>
                {
                    asked += 1;
                    return new Dictionary<string, object>((Dictionary<string, object>)focuses[asked / 2 % 2]);
                };
                IntPtr stackHwnd = IntPtr.Zero;
                SurfaceScreen.Name = hwnd =>
                {
                    if (hwnd == stackHwnd && hwnd != IntPtr.Zero) return "stack";
                    NoticeCard card;
                    if (stack.Windows.TryGetValue(hwnd, out card))
                        return (card.Shadow != null && card.Shadow.Hwnd == hwnd ? "shadow:" : "body:") + card.Title;
                    return "0x" + hwnd.ToInt64().ToString("x");
                };
                stack.Create();
                stackHwnd = stack.Hwnd;
                try
                {
                    foreach (object entry in (List<object>)task["script"])
                    {
                        var described = (Dictionary<string, object>)entry;
                        string op = (string)described["op"];
                        var step = (List<object>)described["do"];
                        calls.Clear();
                        actions.Posts.Clear();
                        object returned = null;
                        string kind = (string)step[0];
                        if (kind == "proof")
                        {
                            var proof = new List<object>();
                            foreach (NoticeCard card in stack.Cards)
                            {
                                Dictionary<string, object> notice;
                                proof.Add(notices.TryGetValue(card, out notice)
                                          ? CardProof(card, notice, clock, stack.Locate(), stack.Appearance(), (double)task["hold"])
                                          : null);
                            }
                            proofs.Add(proof);
                            continue;
                        }
                        if (kind == "show")
                        {
                            NoticeCard shown = stack.Show((Dictionary<string, object>)step[1]);
                            if (shown != null) notices[shown] = (Dictionary<string, object>)step[1];
                        }
                        else if (kind == "clock") clock += (double)step[1];
                        else if (kind == "stack")
                        {
                            var sent = (List<object>)step[1];
                            returned = stack.Message(stack.Hwnd, (int)(double)sent[0], (long)(double)sent[1], (long)(double)sent[2]).ToInt64();
                        }
                        else if (kind == "card")
                        {
                            var sent = (List<object>)step[2];
                            NoticeCard card = stack.Cards[(int)(double)step[1]];
                            returned = stack.Message(card.Body.Hwnd, (int)(double)sent[0], (long)(double)sent[1], (long)(double)sent[2]).ToInt64();
                        }
                        else if (kind == "end") stack.Dispose();
                        var cards = new List<object>();
                        foreach (NoticeCard card in stack.Cards)
                            cards.Add(new Dictionary<string, object>
                            {
                                { "id", stack.IdOf(card) }, { "phase", card.Motion.Phase }, { "position", card.Motion.Position },
                                { "edge", card.Edge }, { "seen", card.Seen }, { "superseded", card.Superseded }, { "ended", card.Ended },
                                { "pushed_out", card.PushedOut }, { "moved_out", card.MovedOut },
                                { "hover", card.Hover is SurfaceTarget ? ((SurfaceTarget)card.Hover).ToList() : card.Hover },
                                { "tracking", card.Tracking }, { "size", card.Size },
                            });
                        steps.Add(new Dictionary<string, object>
                        {
                            { "op", op }, { "returned", returned }, { "frames", stack.FrameRunning }, { "frame_ms", stack.FrameMs },
                            { "calls", new List<string>(calls) }, { "posts", new List<object>(actions.Posts) }, { "cards", cards },
                        });
                    }
                }
                finally
                {
                    if (stack.Hwnd != IntPtr.Zero) stack.Dispose();
                }
            }
            finally
            {
                SurfaceScreen.Probe = null;
                SurfaceFonts.Pinned = null;
                SurfaceRenderer.SystemColours = null;
            }
            return new Dictionary<string, object>
            {
                { "steps", steps }, { "proofs", proofs }, { "log", logged }, { "left", SurfaceGdip.GdipObjects - before },
            };
        }

        /// The live-path proof for one notification card: its two windows' pictures as its own paint draws them for `now`
        /// against the render mode's - a card made offscreen from the same notice, place and look, born when it was, with
        /// its pointer marks and its light's last breath, redrawn and painted for the live card's frame - byte for byte,
        /// and the two plans equal. Null when the card has no windows.
        private static object CardProof(NoticeCard card, Dictionary<string, object> notice, double now, CardStack.CardScreen where,
                                        Dictionary<string, object> drawn, double hold)
        {
            if (card.Body == null) return null;
            card.Paint(now);
            string window = Digest(Joined(card.Body.Pixels(), card.Shadow.Pixels()));
            CardFrame frame = card.Motion.Frame(now);
            using (var fresh = new NoticeCard(null, (Dictionary<string, object>)notice["view"], PopupWords.Str(Field(notice, "title")),
                                              Equals(Field(notice, "stays"), true), hold, card.Born, where.Dpi, where.Work, drawn,
                                              false, Field(notice, "letters") as string))
            {
                fresh.Hover = card.Hover;
                fresh.Pressed = card.Pressed;
                fresh.Breathed = card.Breathed;
                fresh.Redraw();
                fresh.PaintLayers(frame);
                string render = Digest(Joined(fresh.Body.Pixels(), fresh.Shadow.Pixels()));
                return new List<object> { window, render, Json.Write(Dump(fresh.Plan)) == Json.Write(Dump(card.Plan)) };
            }
        }

        private static byte[] Joined(byte[] first, byte[] second)
        {
            var whole = new byte[first.Length + second.Length];
            Buffer.BlockCopy(first, 0, whole, 0, first.Length);
            Buffer.BlockCopy(second, 0, whole, first.Length, second.Length);
            return whole;
        }
    }
}

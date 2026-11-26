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
            switch (surface)
            {
                case "tray_words":
                    plan = TrayWordsCase(task);
                    return true;
                case "tray_place":
                    plan = TrayPlaceCase(task);
                    return true;
                case "tip_window":
                    plan = TipWindowCase(task);
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
    }
}

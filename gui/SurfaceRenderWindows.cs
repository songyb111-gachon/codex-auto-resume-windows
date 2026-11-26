// Codex Auto Resume - the render mode's cases for the surfaces' windows and their words (v0.6.27, S6.3c).
//
// The other half of SurfaceRender (gui/SurfaceRender.cs): cases that hold what the windows decide - the icon's words,
// where Windows keeps the icon - against the reference, as comparison A holds the plans. Nothing here makes a window
// anybody sees, posts an action or writes anything but the answer.
using System;
using System.Collections.Generic;

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
    }
}

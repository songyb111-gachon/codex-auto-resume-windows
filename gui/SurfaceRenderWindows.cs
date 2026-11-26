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
    }
}

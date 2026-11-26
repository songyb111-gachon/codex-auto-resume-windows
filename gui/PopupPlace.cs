// Codex Auto Resume - where the popup goes, and what is under the pointer (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/placement.py, call for call: taskbar_edge, place, hit_test,
// focus_order and next_focus. Beside the notification area, on the monitor the icon is on, cut to the work area, and
// never over the taskbar, whichever edge it is on. Rectangles are (left, top, right, bottom) in physical pixels.
using System;
using System.Collections.Generic;

namespace CodexAutoResume
{
    internal static class PopupPlace
    {
        /// Which edge of the monitor the taskbar is on, from how the work area is inset (taskbar_edge). With none
        /// inset (an auto-hidden taskbar) the edge nearest the anchor's centre; with no anchor, the bottom.
        internal static string TaskbarEdge(int[] work, int[] monitor, int[] anchor = null)
        {
            if (work[3] < monitor[3]) return "bottom";
            if (work[1] > monitor[1]) return "top";
            if (work[0] > monitor[0]) return "left";
            if (work[2] < monitor[2]) return "right";
            if (anchor != null)
            {
                double cx = (anchor[0] + anchor[2]) / 2.0, cy = (anchor[1] + anchor[3]) / 2.0;
                // min() over the dictionary's order keeps the first of equal distances: bottom, top, left, right.
                string[] edges = { "bottom", "top", "left", "right" };
                double[] distance = { monitor[3] - cy, cy - monitor[1], cx - monitor[0], monitor[2] - cx };
                int best = 0;
                for (int i = 1; i < edges.Length; i++) if (distance[i] < distance[best]) best = i;
                return edges[best];
            }
            return "bottom";
        }

        internal static int Clamp(int value, int low, int high)
        {
            if (high < low) return low;
            return Math.Max(low, Math.Min(value, high));
        }

        /// Where the window goes (place): beside the icon, on the taskbar's side, inside the work area; without an icon
        /// rectangle the cursor stands in for it. (x, y) and the edge.
        internal static int[] Place(int[] size, int[] work, int[] monitor, int[] icon, int[] cursor, int gap, out string edge)
        {
            int width = size[0], height = size[1];
            int[] anchor = icon;
            if (anchor == null && cursor != null) anchor = new[] { cursor[0], cursor[1], cursor[0] + 1, cursor[1] + 1 };
            edge = TaskbarEdge(work, monitor, anchor);
            int left = work[0], top = work[1], right = work[2], bottom = work[3];
            if (anchor == null) anchor = new[] { right - 1, bottom - 1, right, bottom };
            int cx = SurfaceMath.Div(anchor[0] + anchor[2], 2), cy = SurfaceMath.Div(anchor[1] + anchor[3], 2);
            int x, y;
            if (edge == "bottom")
            {
                x = cx - SurfaceMath.Div(width, 2);
                y = Math.Min(anchor[1], bottom) - gap - height;
            }
            else if (edge == "top")
            {
                x = cx - SurfaceMath.Div(width, 2);
                y = Math.Max(anchor[3], top) + gap;
            }
            else if (edge == "left")
            {
                x = Math.Max(anchor[2], left) + gap;
                y = cy - SurfaceMath.Div(height, 2);
            }
            else
            {
                x = Math.Min(anchor[0], right) - gap - width;
                y = cy - SurfaceMath.Div(height, 2);
            }
            x = Clamp(x, left + gap, right - gap - width);
            y = Clamp(y, top + gap, bottom - gap - height);
            return new[] { x, y };
        }

        /// The first target whose rectangle holds (x, y), or null (hit_test).
        internal static object HitTest(List<KeyValuePair<object, int[]>> targets, int x, int y)
        {
            foreach (KeyValuePair<object, int[]> pair in targets)
            {
                int[] r = pair.Value;
                if (r[0] <= x && x < r[2] && r[1] <= y && y < r[3]) return pair.Key;
            }
            return null;
        }

        /// Reading order: each task's switch, then Pause/Resume, then Open Dashboard (focus_order).
        internal static List<object> FocusOrder(List<KeyValuePair<object, int[]>> targets)
        {
            var order = new List<object>();
            foreach (KeyValuePair<object, int[]> pair in targets) order.Add(pair.Key);
            return order;
        }

        /// The next (or, backwards, the previous) target round the order (next_focus); null for an empty order.
        internal static object NextFocus(List<object> order, object current, bool backwards = false)
        {
            if (order.Count == 0) return null;
            int at = current == null ? -1 : order.IndexOf(current);
            if (at < 0) return backwards ? order[order.Count - 1] : order[0];
            int index = at + (backwards ? -1 : 1);
            return order[((index % order.Count) + order.Count) % order.Count];
        }
    }
}

// Codex Auto Resume - a special day's pieces, frame by frame, and the icon's mark (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/brand/days.py's drawing half, call for call: path_points, the scene's and the
// specks' elements (scene_elements, speck_elements), where each is a moment in (element_at with _wave, _drift, _centre
// and _placed), scene_frame, speck_frame with its `within` (_reach, speck_reach, _height), and the icon's mark (MARKS,
// _rotated, _box, _inside, _on_line, mark_colour).
//
// The elements are read from gui/Brand.cs's DayScene and DaySpecks, which build/make_brand.py writes from days.py's own
// lists (scene_text, speck_text): every number in them is one days.py rounded to three places, so the text says each
// exactly and the parse gives the same double. The mark is computed, as days.py computes it, because its turned points are
// not rounded. Every cosine, sine and power is the C runtime's (SurfaceMath), as Python's math is.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace CodexAutoResume
{
    /// One element of a day (days.py's [kind, numbers, colour, opacity, motion, motion's numbers]).
    internal sealed class DayElement
    {
        internal string Kind, Colour, Motion;
        internal double[] Numbers, Values;
        internal double Opacity;
    }

    /// One shape to draw (element_at's (kind, numbers, colour, opacity)).
    internal sealed class DayShape
    {
        internal string Kind, Colour;
        internal double[] Numbers;
        internal double Opacity;
    }

    internal static class SurfaceDays
    {
        internal const double SceneWidth = 190.0, SceneHeight = 66.0, SpeckBand = 300.0;

        private static readonly Regex Token = new Regex(@"[MmLlHhVvQqTtZz]|-?(?:\d+\.?\d*|\.\d+)", RegexOptions.CultureInvariant);

        private static int Arguments(char upper)
        {
            switch (upper)
            {
                case 'M': case 'L': case 'T': return 2;
                case 'H': case 'V': return 1;
                case 'Q': return 4;
                default: return 0;
            }
        }

        private static double Square(double value) { return SurfaceMath.Pow(value, 2.0); }

        /// An SVG path of M, L, H, V, Q, T and Z, flattened: a list of subpaths, each a list of (x, y) (path_points).
        internal static List<List<double[]>> PathPoints(string path, int steps = 8)
        {
            var tokens = new List<string>();
            foreach (Match match in Token.Matches(path)) tokens.Add(match.Value);
            var subpaths = new List<List<double[]>>();
            var points = new List<double[]>();
            double x = 0.0, y = 0.0, startX = 0.0, startY = 0.0;
            double[] control = null;
            int at = 0;
            string command = null;
            while (at < tokens.Count)
            {
                if (char.IsLetter(tokens[at][0]))
                {
                    command = tokens[at];
                    at++;
                    if (command == "Z" || command == "z")
                    {
                        points.Add(new[] { startX, startY });
                        x = startX;
                        y = startY;
                        control = null;
                        continue;
                    }
                }
                char upper = char.ToUpperInvariant(command[0]);
                bool relative = char.IsLower(command[0]);
                int count = Arguments(upper);
                var values = new double[count];
                for (int i = 0; i < count; i++) values[i] = double.Parse(tokens[at + i], CultureInfo.InvariantCulture);
                at += count;
                double baseX = relative ? x : 0.0, baseY = relative ? y : 0.0;
                if (upper == 'M')
                {
                    if (points.Count > 0) subpaths.Add(points);
                    x = baseX + values[0];
                    y = baseY + values[1];
                    startX = x;
                    startY = y;
                    points = new List<double[]> { new[] { x, y } };
                    command = relative ? "l" : "L";
                    control = null;
                }
                else if (upper == 'L' || upper == 'H' || upper == 'V')
                {
                    if (upper == 'H') x = baseX + values[0];
                    else if (upper == 'V') y = baseY + values[0];
                    else
                    {
                        x = baseX + values[0];
                        y = baseY + values[1];
                    }
                    points.Add(new[] { x, y });
                    control = null;
                }
                else
                {
                    double cx, cy, endX, endY;
                    if (upper == 'Q')
                    {
                        cx = baseX + values[0];
                        cy = baseY + values[1];
                        endX = baseX + values[2];
                        endY = baseY + values[3];
                    }
                    else
                    {
                        if (control != null)
                        {
                            cx = 2 * x - control[0];
                            cy = 2 * y - control[1];
                        }
                        else
                        {
                            cx = x;
                            cy = y;
                        }
                        endX = baseX + values[0];
                        endY = baseY + values[1];
                    }
                    for (int step = 1; step <= steps; step++)
                    {
                        double t = step / (double)steps;
                        points.Add(new[] { Square(1 - t) * x + 2 * (1 - t) * t * cx + t * t * endX,
                                           Square(1 - t) * y + 2 * (1 - t) * t * cy + t * t * endY });
                    }
                    x = endX;
                    y = endY;
                    control = new[] { cx, cy };
                }
            }
            if (points.Count > 0) subpaths.Add(points);
            return subpaths;
        }

        // ------------------------------------------------------------------ the elements
        private static readonly Dictionary<string, List<DayElement>> Scenes = new Dictionary<string, List<DayElement>>();
        private static readonly Dictionary<string, List<DayElement>> Specks = new Dictionary<string, List<DayElement>>();
        private static readonly Dictionary<string, List<double[]>> Reaches = new Dictionary<string, List<double[]>>();
        private static readonly object Lock = new object();

        private static double[] Numbers(string text)
        {
            if (text.Length == 0) return new double[0];
            string[] parts = text.Split(' ');
            var found = new double[parts.Length];
            for (int i = 0; i < parts.Length; i++) found[i] = double.Parse(parts[i], CultureInfo.InvariantCulture);
            return found;
        }

        /// scene_text's lines back into the elements they were written from.
        internal static List<DayElement> Parse(string text)
        {
            var elements = new List<DayElement>();
            if (string.IsNullOrEmpty(text)) return elements;
            foreach (string line in text.Split('\n'))
            {
                string[] fields = line.Split(';');
                elements.Add(new DayElement {
                    Kind = fields[0], Numbers = Numbers(fields[1]), Colour = fields[2],
                    Opacity = double.Parse(fields[3], CultureInfo.InvariantCulture), Motion = fields[4],
                    Values = Numbers(fields.Length > 5 ? fields[5] : "") });
            }
            return elements;
        }

        /// `look`'s scene as the list every surface draws from (scene_elements).
        internal static List<DayElement> SceneElements(string look)
        {
            lock (Lock)
            {
                List<DayElement> found;
                if (!Scenes.TryGetValue(look, out found))
                {
                    string text = Brand.DayScene(look);
                    if (text == null) throw new KeyNotFoundException(look);
                    found = Scenes[look] = Parse(text);
                }
                return found;
            }
        }

        /// `look`'s specks in one band SpeckBand by 66 (speck_elements).
        internal static List<DayElement> SpeckElements(string look)
        {
            lock (Lock)
            {
                List<DayElement> found;
                if (!Specks.TryGetValue(look, out found))
                {
                    string text = Brand.DaySpecks(look);
                    if (text == null) throw new KeyNotFoundException(look);
                    found = Specks[look] = Parse(text);
                }
                return found;
            }
        }

        private static double[] Centre(string kind, double[] numbers)
        {
            if (kind == "poly")
            {
                double left = double.MaxValue, right = double.MinValue, top = double.MaxValue, bottom = double.MinValue;
                for (int at = 0; at + 1 < numbers.Length; at += 2)
                {
                    left = Math.Min(left, numbers[at]);
                    right = Math.Max(right, numbers[at]);
                    top = Math.Min(top, numbers[at + 1]);
                    bottom = Math.Max(bottom, numbers[at + 1]);
                }
                return new[] { (left + right) / 2.0, (top + bottom) / 2.0 };
            }
            return new[] { numbers[0], numbers[1] };
        }

        private delegate double[] Move(double x, double y);

        /// `numbers` with `move` applied to every point (_placed).
        private static double[] Placed(string kind, double[] numbers, Move move)
        {
            if (kind == "poly" || kind == "stroke")
            {
                int start = kind == "stroke" ? 1 : 0;
                var placed = new List<double>();
                for (int i = 0; i < start; i++) placed.Add(numbers[i]);
                for (int at = start; at < numbers.Length; at += 2)
                {
                    double[] point = move(numbers[at], numbers[at + 1]);
                    placed.Add(point[0]);
                    placed.Add(point[1]);
                }
                return placed.ToArray();
            }
            double[] moved = move(numbers[0], numbers[1]);
            var whole = new double[numbers.Length];
            whole[0] = moved[0];
            whole[1] = moved[1];
            for (int i = 2; i < numbers.Length; i++) whole[i] = numbers[i];
            return whole;
        }

        private static double Radians(double degrees) { return degrees * (Math.PI / 180.0); }

        /// 0 to 1 and back to 0 over `duration`, eased in and out (_wave).
        private static double Wave(double seconds, double duration, double delay = 0.0)
        {
            return (1.0 - SurfaceMath.Cos(2.0 * Math.PI * SurfaceMath.Mod((seconds - delay) / duration, 1.0))) / 2.0;
        }

        /// -10 to 14 and back, a whole `duration` each way (_drift).
        private static double Drift(double seconds, double duration)
        {
            double turn = seconds / duration;
            double part = SurfaceMath.Mod(turn, 1.0);
            if ((long)turn % 2 != 0) part = 1.0 - part;
            return -10.0 + 24.0 * (1.0 - SurfaceMath.Cos(Math.PI * part)) / 2.0;
        }

        /// One element `seconds` in (element_at).
        internal static DayShape ElementAt(DayElement element, double seconds)
        {
            string kind = element.Kind;
            double[] numbers = (double[])element.Numbers.Clone();
            double[] values = element.Values;
            double opacity = element.Opacity;
            switch (element.Motion)
            {
                case "fall":
                {
                    double part = SurfaceMath.Mod((seconds - values[1]) / values[0], 1.0);
                    double[] centre = Centre(kind, numbers);
                    double centreX = centre[0], centreY = centre[1];
                    double dy = -14.0 + 96.0 * part;
                    double radians = Radians(values[2] * part);
                    double c = SurfaceMath.Cos(radians), s = SurfaceMath.Sin(radians);
                    numbers = Placed(kind, numbers, (x, y) => new[] { centreX + (x - centreX) * c - (y - centreY) * s,
                                                                      centreY + dy + (x - centreX) * s + (y - centreY) * c });
                    break;
                }
                case "twinkle":
                {
                    double level = Wave(seconds, values[0], values[1]);
                    double[] centre = Centre(kind, numbers);
                    double centreX = centre[0], centreY = centre[1];
                    double size = 0.7 + 0.4 * level;
                    numbers = Placed(kind, numbers, (x, y) => new[] { centreX + (x - centreX) * size, centreY + (y - centreY) * size });
                    opacity = 0.25 + 0.75 * level;
                    break;
                }
                case "breathe":
                    opacity = values[1] + values[2] * Wave(seconds, values[0]);
                    break;
                case "drift":
                {
                    double dx = Drift(seconds, values[0]);
                    numbers = Placed(kind, numbers, (x, y) => new[] { x + dx, y });
                    break;
                }
                case "sway":
                {
                    double radians = Radians(-5.0 + 10.0 * Wave(seconds, values[0]));
                    double c = SurfaceMath.Cos(radians), s = SurfaceMath.Sin(radians);
                    double px = values[1], py = values[2];
                    numbers = Placed(kind, numbers, (x, y) => new[] { px + (x - px) * c - (y - py) * s, py + (x - px) * s + (y - py) * c });
                    break;
                }
                case "flame":
                {
                    double tall = numbers[3] * (1.0 + 0.35 * Wave(seconds, values[0]));
                    numbers[1] = values[1] - tall;
                    numbers[3] = tall;
                    break;
                }
            }
            return new DayShape { Kind = kind, Numbers = numbers, Colour = element.Colour, Opacity = opacity };
        }

        /// `look`'s scene `milliseconds` in, as the shapes to draw in order, in its 190 by 66 (scene_frame).
        internal static List<DayShape> SceneFrame(string look, double milliseconds)
        {
            var shapes = new List<DayShape>();
            foreach (DayElement element in SceneElements(look)) shapes.Add(ElementAt(element, milliseconds / 1000.0));
            return shapes;
        }

        /// How far along its band an element can ever reach, (from, to) (_reach).
        private static double[] Reach(DayElement element)
        {
            string kind = element.Kind;
            double[] numbers = element.Numbers;
            if (kind == "round") return new[] { numbers[0], numbers[0] + numbers[2] };
            double centreX, far;
            if (kind == "poly")
            {
                double[] centre = Centre(kind, numbers);
                centreX = centre[0];
                far = double.NegativeInfinity;
                for (int at = 0; at + 1 < numbers.Length; at += 2)
                {
                    double distance = IconMark.Hypot(numbers[at] - centre[0], numbers[at + 1] - centre[1]);
                    if (distance > far) far = distance;
                }
            }
            else
            {
                centreX = numbers[0];
                far = numbers[2];
            }
            far *= 1.1;
            return new[] { centreX - far, centreX + far };
        }

        /// For each of `look`'s specks, how far along the band it can ever reach (speck_reach).
        internal static List<double[]> SpeckReach(string look)
        {
            List<DayElement> elements = SpeckElements(look);
            lock (Lock)
            {
                List<double[]> found;
                if (!Reaches.TryGetValue(look, out found))
                {
                    found = new List<double[]>();
                    foreach (DayElement element in elements) found.Add(Reach(element));
                    Reaches[look] = found;
                }
                return found;
            }
        }

        /// A shape's (top, bottom) (_height).
        private static double[] Height(DayShape shape)
        {
            double[] numbers = shape.Numbers;
            if (shape.Kind == "poly")
            {
                double top = double.MaxValue, bottom = double.MinValue;
                for (int at = 1; at < numbers.Length; at += 2)
                {
                    top = Math.Min(top, numbers[at]);
                    bottom = Math.Max(bottom, numbers[at]);
                }
                return new[] { top, bottom };
            }
            if (shape.Kind == "round") return new[] { numbers[1], numbers[1] + numbers[3] };
            return new[] { numbers[1] - numbers[2], numbers[1] + numbers[2] };
        }

        /// `look`'s specks `milliseconds` in, in their band; `within` (from, to) along the band, or null for all of them
        /// (speck_frame).
        internal static List<DayShape> SpeckFrame(string look, double milliseconds, double[] within = null)
        {
            double seconds = milliseconds / 1000.0;
            List<DayElement> elements = SpeckElements(look);
            var shown = new List<DayShape>();
            if (within == null)
            {
                foreach (DayElement element in elements) shown.Add(ElementAt(element, seconds));
                return shown;
            }
            double least = within[0], most = within[1];
            List<double[]> reaches = SpeckReach(look);
            for (int i = 0; i < elements.Count; i++)
            {
                double start = reaches[i][0], end = reaches[i][1];
                if (end < least || start > most) continue;
                DayShape shape = ElementAt(elements[i], seconds);
                double[] height = Height(shape);
                if (height[1] >= 0.0 && height[0] <= SceneHeight) shown.Add(shape);
            }
            return shown;
        }

        // ------------------------------------------------------------------ the icon's mark, in the icon's 32 by 32
        private sealed class MarkShape
        {
            internal string Kind, Colour;
            internal List<double[]> Points;
            internal double[] Numbers;
        }

        private static List<double[]> Rotated(List<double[]> points, double degrees, double px, double py)
        {
            double radians = Radians(degrees);
            double c = SurfaceMath.Cos(radians), s = SurfaceMath.Sin(radians);
            var turned = new List<double[]>();
            foreach (double[] point in points)
            {
                double x = point[0], y = point[1];
                turned.Add(new[] { px + (x - px) * c - (y - py) * s, py + (x - px) * s + (y - py) * c });
            }
            return turned;
        }

        private static List<double[]> Box(double x, double y, double w, double h)
        {
            return new List<double[]> { new[] { x, y }, new[] { x + w, y }, new[] { x + w, y + h }, new[] { x, y + h } };
        }

        private static MarkShape Poly(List<double[]> points, string colour) { return new MarkShape { Kind = "poly", Points = points, Colour = colour }; }

        private static MarkShape Circle(double cx, double cy, double radius, string colour)
        {
            return new MarkShape { Kind = "circle", Numbers = new[] { cx, cy, radius }, Colour = colour };
        }

        private static MarkShape Line(double x1, double y1, double x2, double y2, double width, string colour)
        {
            return new MarkShape { Kind = "line", Numbers = new[] { x1, y1, x2, y2, width }, Colour = colour };
        }

        private static readonly Dictionary<string, List<MarkShape>> MarkTable = new Dictionary<string, List<MarkShape>>();

        /// MARKS[look].
        private static List<MarkShape> Marks(string look)
        {
            lock (Lock)
            {
                List<MarkShape> found;
                if (MarkTable.TryGetValue(look, out found)) return found;
                found = new List<MarkShape>();
                switch (look)
                {
                    case "birthday":
                        found.Add(Poly(Rotated(Box(21, 3, 3.4, 6), 25, 22, 6), "#FFD76A"));
                        found.Add(Circle(27, 9.5, 1.7, "#FFFFFF"));
                        found.Add(Poly(Rotated(Box(25, 2.5, 3, 5), -30, 26, 5), "#FFB3C0"));
                        break;
                    case "new_year":
                        found.Add(Poly(PathPoints("M25.5 2l1 3.5 3.5 1-3.5 1-1 3.5-1-3.5-3.5-1 3.5-1z", 1)[0], "#FFE9A8"));
                        break;
                    case "christmas":
                        found.Add(Line(25.5, 2.5, 25.5, 10.5, 1.1, "#FFFFFF"));
                        found.Add(Line(21.8, 4.5, 29.2, 8.5, 1.1, "#FFFFFF"));
                        found.Add(Line(21.8, 8.5, 29.2, 4.5, 1.1, "#FFFFFF"));
                        break;
                    case "seollal":
                        string[] colours = { "#F2C230", "#3FA86B", "#3B6FC9", "#E88BB0" };
                        for (int index = 0; index < colours.Length; index++) found.Add(Poly(Box(2, 23.5 + index * 1.5, 28, 1.5), colours[index]));
                        break;
                    case "chuseok":
                        found.Add(Circle(25.5, 6.5, 4.0, "#F6E7B4"));
                        found.Add(Circle(24.2, 5.6, 0.8, "#E2CF96"));
                        break;
                    default:
                        throw new KeyNotFoundException(look);
                }
                MarkTable[look] = found;
                return found;
            }
        }

        private static bool Inside(List<double[]> points, double x, double y)
        {
            bool inside = false;
            for (int index = 0; index < points.Count; index++)
            {
                double x1 = points[index][0], y1 = points[index][1];
                double[] other = points[index == 0 ? points.Count - 1 : index - 1];
                double x2 = other[0], y2 = other[1];
                if ((y1 > y) != (y2 > y) && x < x1 + (y - y1) * (x2 - x1) / (y2 - y1)) inside = !inside;
            }
            return inside;
        }

        private static bool OnLine(double x, double y, double x1, double y1, double x2, double y2, double width)
        {
            double dx = x2 - x1, dy = y2 - y1;
            double t = Math.Max(0.0, Math.Min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)));
            return Square(x - x1 - t * dx) + Square(y - y1 - t * dy) <= width * width / 4.0;
        }

        /// The (red, green, blue) of `look`'s mark at (x, y) in the icon's 32 by 32, or null where it is not (mark_colour).
        internal static int[] MarkColour(string look, double x, double y)
        {
            string found = null;
            foreach (MarkShape shape in Marks(look))
            {
                bool hit;
                if (shape.Kind == "poly") hit = Inside(shape.Points, x, y);
                else if (shape.Kind == "circle")
                    hit = Square(x - shape.Numbers[0]) + Square(y - shape.Numbers[1]) <= Square(shape.Numbers[2]);
                else hit = OnLine(x, y, shape.Numbers[0], shape.Numbers[1], shape.Numbers[2], shape.Numbers[3], shape.Numbers[4]);
                if (hit) found = shape.Colour;
            }
            return found != null ? SurfaceTheme.Rgb(System.Drawing.ColorTranslator.FromHtml(found)) : null;
        }
    }
}

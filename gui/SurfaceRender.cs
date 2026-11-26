// Codex Auto Resume - the host's render mode: the surfaces laid out (and drawn) into memory, never on a screen
// (v0.6.27, S6.3; P6-DESIGN 3.2).
//
// With CODEX_AR_RENDER_PLAN naming a job, CodexAutoResume.exe loads no DLL and makes no window anybody sees (the host's
// Main, S6.2b, hands the job to Run below before anything else). A job is JSON:
//
//   {"format": "car-surface-job/1",
//    "tables": {name: {"measure": [[role, text, width, flags, w, h], ...], "metrics": {role: [ascent, x]},
//                      "ink": [[role, text, first, last], ...]}},
//    "cases": [{"id": ..., "surface": "popup" | "menu" | "tip" | "card" | "icon" | ..., "table": name, ...}, ...]}
//
// and the answer, written to CODEX_AR_RENDER_OUT (or the job's path with ".out.json"), is the plan dump: for every case
// its plan as JSON - every rectangle, every text run with its role, colour and alignment, every target - under the
// Python's own keys, or the error that stopped it. Text is measured from the job's table (TableTextCalc), so a plan is
// the reference's exactly when the arithmetic is, whatever fonts the machine has (comparison A,
// tests/test_surface_parity.py). Nothing here shows, posts or starts anything.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace CodexAutoResume
{
    internal static partial class SurfaceRender
    {
        /// The variable that names a job.
        internal const string JobVariable = "CODEX_AR_RENDER_PLAN";
        /// The variable that names where the answer goes.
        internal const string OutVariable = "CODEX_AR_RENDER_OUT";
        internal const string Format = "car-surface-job/1";

        /// The host's Main asks this first: the exit code of the job CODEX_AR_RENDER_PLAN names, or null when none does.
        internal static int? Run()
        {
            string job = Environment.GetEnvironmentVariable(JobVariable);
            if (string.IsNullOrEmpty(job)) return null;
            string output = Environment.GetEnvironmentVariable(OutVariable);
            return RunJob(job, string.IsNullOrEmpty(output) ? job + ".out.json" : output);
        }

        /// One job from `jobPath` into `outPath`: 0 when every case was laid out, 1 when any case failed (its error is
        /// in the answer), 2 when the job could not be read at all.
        internal static int RunJob(string jobPath, string outPath)
        {
            Dictionary<string, object> job;
            try
            {
                job = (Dictionary<string, object>)Json.Parse(File.ReadAllText(jobPath, new UTF8Encoding(false)));
                if ((job["format"] as string) != Format) throw new FormatException("not a " + Format + " job");
            }
            catch (Exception exc)
            {
                Write(outPath, new Dictionary<string, object> { { "error", exc.GetType().Name + ": " + exc.Message } });
                return 2;
            }
            var tables = new Dictionary<string, TableTextCalc>();
            object tableValue;
            if (job.TryGetValue("tables", out tableValue) && tableValue != null)
                foreach (KeyValuePair<string, object> pair in (Dictionary<string, object>)tableValue)
                {
                    var table = (Dictionary<string, object>)pair.Value;
                    tables[pair.Key] = new TableTextCalc(Field(table, "measure") as List<object>,
                                                         Field(table, "metrics") as Dictionary<string, object>,
                                                         Field(table, "ink") as List<object>);
                }
            var answers = new List<object>();
            bool failed = false;
            foreach (object entry in (List<object>)job["cases"])
            {
                var task = (Dictionary<string, object>)entry;
                var answer = new Dictionary<string, object>();
                answer["id"] = Field(task, "id");
                try
                {
                    answer["plan"] = Dump(Case(task, tables));
                }
                catch (Exception exc)
                {
                    failed = true;
                    answer["error"] = exc.GetType().Name + ": " + exc.Message;
                }
                answers.Add(answer);
            }
            Write(outPath, new Dictionary<string, object> { { "format", Format }, { "cases", answers } });
            return failed ? 1 : 0;
        }

        private static void Write(string path, Dictionary<string, object> value)
        {
            File.WriteAllText(path, Json.Write(value), new UTF8Encoding(false));
        }

        internal static object Field(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) ? value : null;
        }

        private static double Number(Dictionary<string, object> map, string key)
        {
            return (double)map[key];
        }

        private static SurfaceText Measure(Dictionary<string, object> task, Dictionary<string, TableTextCalc> tables,
                                           string locale)
        {
            object name = Field(task, "table");
            if (name == null) return null;
            return new SurfaceText(tables[(string)name], locale);
        }

        /// One case's plan (or plans), as the surface's own layout makes it.
        private static object Case(Dictionary<string, object> task, Dictionary<string, TableTextCalc> tables)
        {
            string surface = (string)task["surface"];
            string locale = Field(task, "locale") as string;
            SurfaceText measure = Measure(task, tables, locale);
            switch (surface)
            {
                case "popup":
                    return PopupLayout.Plan((Dictionary<string, object>)task["vm"], Number(task, "scale"), locale, measure);
                case "menu":
                    return Menu(task, locale, measure);
                case "tip":
                    return Tip(task, locale, measure);
                case "place":
                    return Place(task);
                case "popup_motion":
                    return PopupMotionCase(task);
                case "card":
                    return Card(task, measure);
                case "card_room":
                    return CardRoom(task);
                case "card_life":
                    return CardLife(task);
                case "icon":
                    return Icon(task);
                case "paint":
                    return Paint(task, tables);
                case "shape":
                    return ShapeCase(task);
                case "gdip":
                    return GdipCase(task);
                case "elevation":
                    return ElevationCase(task);
                case "days":
                    return DaysCase(task);
                case "pixels":
                    return PixelsCase(task);
                case "drawn":
                    return DrawnCase(task);
                case "cards":
                    return CardsCase(task);
                case "bidi":
                    return ((List<object>)task["texts"]).ConvertAll(text => (object)SurfaceBidi.FirstStrong((string)text));
            }
            object more;
            if (WindowCase(surface, task, tables, out more)) return more;
            throw new NotSupportedException("no surface " + surface);
        }

        private static int? Index(object value)
        {
            return value == null ? (int?)null : (int)(double)value;
        }

        private static int[] Ints(object value)
        {
            var list = (List<object>)value;
            var ints = new int[list.Count];
            for (int i = 0; i < ints.Length; i++) ints[i] = (int)(double)list[i];
            return ints;
        }

        /// The menu: numbered first when the entries are a row's (menu_numbered), laid out (and mirrored), placed at
        /// each point and beside each box asked, and its keys and its screen reader's children.
        private static Dictionary<string, object> Menu(Dictionary<string, object> task, string locale, SurfaceText measure)
        {
            var entries = (List<object>)task["entries"];
            var result = new Dictionary<string, object>();
            if (SurfaceMath.Truthy(Field(task, "numbered")))
            {
                var actions = new Dictionary<int, object>();
                entries = MenuPlan.Numbered(entries, actions);
                var listed = new List<object>();
                foreach (KeyValuePair<int, object> pair in actions) listed.Add(new List<object> { pair.Key, pair.Value });
                result["numbered"] = Dump(entries);
                result["actions"] = Dump(listed);
            }
            object most = Field(task, "max_width");
            SurfacePlan plan = MenuPlan.Plan(entries, Number(task, "scale"), locale, measure, Index(most));
            result["plan"] = plan;
            var places = new List<object>();
            foreach (object entry in (List<object>)Field(task, "places") ?? new List<object>())
            {
                var pair = (List<object>)entry;
                places.Add(MenuPlan.Place(plan, Ints(pair[0]), Ints(pair[1])));
            }
            result["places"] = places;
            var besides = new List<object>();
            foreach (object entry in (List<object>)Field(task, "besides") ?? new List<object>())
            {
                var pair = (List<object>)entry;
                besides.Add(MenuPlan.Beside(plan, Ints(pair[0]), Ints(pair[1])));
            }
            result["besides"] = besides;
            var steps = new List<object>();
            foreach (object current in (List<object>)Field(task, "currents") ?? new List<object>())
                steps.Add(new List<object> { MenuPlan.Step(entries, Index(current)), MenuPlan.Step(entries, Index(current), true) });
            result["steps"] = steps;
            result["ends"] = new List<object> { MenuPlan.End(entries), MenuPlan.End(entries, true) };
            var letters = new List<object>();
            foreach (object entry in (List<object>)Field(task, "letters") ?? new List<object>())
            {
                var pair = (List<object>)entry;
                KeyValuePair<int?, bool> found = MenuPlan.Letter(entries, Index(pair[0]), pair[1] as string);
                letters.Add(new List<object> { found.Key, found.Value });
            }
            result["letters"] = letters;
            result["accessible"] = MenuPlan.AccessibleItems(plan, Index(Field(task, "selected")),
                                                            Field(task, "strings") as Dictionary<string, object>);
            return result;
        }

        private static int[] IntsOrNull(object value)
        {
            return value == null ? null : Ints(value);
        }

        /// The tip card: its plan (measured, mirrored right to left), its words, and the box it stands beside for each
        /// (icon, point, cursor) asked.
        private static Dictionary<string, object> Tip(Dictionary<string, object> task, string locale, SurfaceText measure)
        {
            SurfacePlan plan = TipPlan.Plan((Dictionary<string, object>)task["parts"], Field(task, "light"), Number(task, "scale"),
                                            locale, Field(task, "day") as string, measure);
            var anchors = new List<object>();
            foreach (object entry in (List<object>)Field(task, "anchors") ?? new List<object>())
            {
                var three = (List<object>)entry;
                anchors.Add(TipPlan.Anchor(IntsOrNull(three[0]), IntsOrNull(three[1]), IntsOrNull(three[2])));
            }
            return new Dictionary<string, object> { { "plan", plan }, { "text", TipPlan.TipText(plan) }, { "anchors", anchors } };
        }

        /// The popup's placement: (x, y, edge) for each (size, work, monitor, icon, cursor, gap) asked, and the hit test
        /// and focus order over the targets given.
        private static Dictionary<string, object> Place(Dictionary<string, object> task)
        {
            var places = new List<object>();
            foreach (object entry in (List<object>)task["places"])
            {
                var six = (List<object>)entry;
                string edge;
                int[] at = PopupPlace.Place(Ints(six[0]), Ints(six[1]), Ints(six[2]), IntsOrNull(six[3]), IntsOrNull(six[4]),
                                            (int)(double)six[5], out edge);
                places.Add(new List<object> { at[0], at[1], edge });
            }
            var targets = new List<KeyValuePair<object, int[]>>();
            foreach (object entry in (List<object>)task["targets"])
            {
                var pair = (List<object>)entry;
                targets.Add(new KeyValuePair<object, int[]>(TargetOf(pair[0]), Ints(pair[1])));
            }
            var hits = new List<object>();
            foreach (object entry in (List<object>)task["points"])
            {
                var point = (List<object>)entry;
                hits.Add(PopupPlace.HitTest(targets, (int)(double)point[0], (int)(double)point[1]));
            }
            List<object> order = PopupPlace.FocusOrder(targets);
            var focus = new List<object>();
            foreach (object current in (List<object>)task["currents"])
                focus.Add(new List<object> { PopupPlace.NextFocus(order, TargetOf(current)),
                                             PopupPlace.NextFocus(order, TargetOf(current), true) });
            return new Dictionary<string, object> { { "places", places }, { "hits", hits }, { "order", order }, { "focus", focus } };
        }

        /// A target as JSON says one ([name] or [name, key]); anything else as it is.
        internal static object TargetOf(object value)
        {
            var list = value as List<object>;
            if (list == null || list.Count == 0 || !(list[0] is string)) return value;
            return list.Count == 1 ? new SurfaceTarget((string)list[0]) : new SurfaceTarget((string)list[0], list[1]);
        }

        /// The popup's motion arithmetic over the moments asked: the light per state, design and reduce, the opening,
        /// the closing, the faces, the glides.
        private static Dictionary<string, object> PopupMotionCase(Dictionary<string, object> task)
        {
            var moments = (List<object>)task["moments"];
            var halos = new List<object>();
            foreach (object state in (List<object>)task["states"])
                foreach (object design in (List<object>)task["designs"])
                    foreach (bool reduced in new[] { false, true })
                        foreach (object moment in moments)
                        {
                            LightFrame frame = PopupMotion.Halo((string)state, (double)moment, reduced, (string)design);
                            halos.Add(frame == null ? null : frame.ToMap());
                        }
            var openings = new List<object>();
            var closings = new List<object>();
            var faces = new List<object>();
            var glides = new List<object>();
            foreach (object moment in moments)
            {
                int[] opening = PopupMotion.Opening((double)moment, 8);
                openings.Add(new List<object> { opening[0], opening[1], opening[2] == 1 });
                int[] closing = PopupMotion.Closing((double)moment, 200);
                closings.Add(new List<object> { closing[0], closing[1] == 1 });
                double[] face = PopupMotion.FaceAmount(5.0, 80, (double)moment);
                faces.Add(new List<object> { face[0], face[1] == 1.0 });
                double[] amount = PopupMotion.GlideAmount(new Glide(10.0, 0.25, 1.0), (double)moment);
                glides.Add(new List<object> { amount[0], amount[1] == 1.0 });
            }
            var seen = new Dictionary<object, bool> { { "a", true }, { "b", false }, { "c", true }, { "d", false } };
            var previous = new Dictionary<object, bool> { { "a", false }, { "b", false }, { "c", true } };
            var running = new Dictionary<object, Glide> { { "a", new Glide(0.0, 0.0, 1.0) }, { "c", new Glide(0.0, 1.0, 0.0) } };
            var next = new List<object>();
            foreach (object moment in moments)
                foreach (bool animate in new[] { true, false })
                    foreach (bool opened in new[] { true, false })
                    {
                        var made = new Dictionary<string, object>();
                        foreach (KeyValuePair<object, Glide> pair in PopupMotion.NextGlides(seen, opened ? previous : null, running,
                                                                                         (double)moment, animate))
                            made[(string)pair.Key] = new List<object> { pair.Value.Started, pair.Value.Begin, pair.Value.End };
                        next.Add(made);
                    }
            var lengths = new List<object>();
            foreach (string before in new[] { "rest", "hover", "pressed", "busy" })
                foreach (string after in new[] { "rest", "hover", "pressed", "busy" })
                    lengths.Add(PopupMotion.FaceLength(before, after));
            return new Dictionary<string, object> { { "halos", halos }, { "openings", openings }, { "closings", closings },
                                                    { "faces", faces }, { "glides", glides }, { "next", next },
                                                    { "lengths", lengths } };
        }

        /// The card: its plan, and the arithmetic round it (the stack, the floating shadow, the text size) over the
        /// inputs asked.
        private static Dictionary<string, object> Card(Dictionary<string, object> task, SurfaceText measure)
        {
            var result = new Dictionary<string, object>();
            result["plan"] = CardPlan.Layout((Dictionary<string, object>)task["vm"], Number(task, "scale"), measure);
            return result;
        }

        private static List<object> Shadows(List<FloatShadow> shadows)
        {
            var listed = new List<object>();
            foreach (FloatShadow s in shadows) listed.Add(new List<object> { s.Dx, s.Dy, s.Blur, s.Colour, s.Alpha });
            return listed;
        }

        /// The card's floating shadows per theme and design, at each depth, and their levels and margins; the stack's
        /// places; the text size it fits.
        private static Dictionary<string, object> CardRoom(Dictionary<string, object> task)
        {
            var result = new Dictionary<string, object>();
            var shadows = new List<object>();
            foreach (object theme in (List<object>)task["themes"])
                foreach (object design in (List<object>)task["designs"])
                {
                    List<FloatShadow> found = CardPlan.FloatShadows((string)theme, (string)design);
                    var at = new List<object>();
                    foreach (object depth in (List<object>)task["depths"]) at.Add(Shadows(CardPlan.ShadowAt(found, (double)depth)));
                    var margins = new List<object>();
                    foreach (object scale in (List<object>)task["scales"]) margins.Add(CardPlan.ShadowMargin(found, (double)scale));
                    shadows.Add(new Dictionary<string, object> { { "shadows", Shadows(found) }, { "at", at }, { "margins", margins } });
                }
            result["shadows"] = shadows;
            var levels = new List<object>();
            foreach (object depth in (List<object>)task["depths"]) levels.Add(CardPlan.DepthLevel((double)depth));
            result["levels"] = levels;
            var stacks = new List<object>();
            foreach (object entry in (List<object>)task["stacks"])
            {
                var five = (List<object>)entry;
                var sizes = new List<int[]>();
                foreach (object size in (List<object>)five[0]) sizes.Add(Ints(size));
                string edge;
                List<int[]> positions = CardPlan.StackPositions(sizes, Ints(five[1]), Ints(five[2]), IntsOrNull(five[3]), 12, 10, out edge);
                stacks.Add(new List<object> { positions, edge });
            }
            result["stacks"] = stacks;
            var fits = new List<object>();
            foreach (object entry in (List<object>)task["fits"])
            {
                var three = (List<object>)entry;
                fits.Add(CardPlan.Fitting((double)three[0], IntsOrNull(three[1]), three[2]));
            }
            result["fits"] = fits;
            var holds = new List<object>();
            foreach (object value in (List<object>)task["holds"]) holds.Add(CardPlan.HoldFor(value));
            result["holds"] = holds;
            var rises = new List<object>();
            foreach (object edge in (List<object>)task["edges"]) rises.Add(CardPlan.RiseVector(edge as string));
            result["rises"] = rises;
            return result;
        }

        private static Dictionary<string, object> FrameOf(CardFrame frame)
        {
            return new Dictionary<string, object> { { "alpha", frame.Alpha }, { "offset", frame.Offset }, { "scale", frame.Scale },
                                                    { "depth", frame.Depth } };
        }

        /// A card's life replayed step by step: each step's answer, and the motion's state after it.
        private static List<object> CardLife(Dictionary<string, object> task)
        {
            var answers = new List<object>();
            CardMotion motion = null;
            foreach (object entry in (List<object>)task["steps"])
            {
                var step = (List<object>)entry;
                string verb = (string)step[0];
                double now = step.Count > 1 && step[1] is double ? (double)step[1] : 0.0;
                object answer = null;
                switch (verb)
                {
                    case "new":
                        motion = new CardMotion(now, step[2] is string && (string)step[2] == "inf" ? double.PositiveInfinity : (double)step[2],
                                                (bool)step[3], IntsOrNull(step[4]));
                        break;
                    case "frame": answer = FrameOf(motion.Frame(now)); break;
                    case "pause": motion.Pause(now, (bool)step[2]); break;
                    case "retire": motion.Retire(now, (bool)step[2]); break;
                    case "move": motion.MoveTo(now, Ints(step[2]), (double)step[3]); break;
                    case "place": answer = motion.Place(now); break;
                    case "moving": answer = motion.Moving(now); break;
                    case "wait":
                        double? wait = motion.WaitMs(now);
                        answer = wait.HasValue ? (object)wait.Value : null;
                        break;
                    case "restart": motion.Restart(now); break;
                    case "delay": motion.Delay(now); break;
                    case "entrance": answer = FrameOf(CardPlan.Entrance(now, (bool)step[2])); break;
                    case "leaving": answer = CardPlan.Leaving(now, (double)step[2], (bool)step[3], (double)step[4]); break;
                    default: throw new NotSupportedException(verb);
                }
                answers.Add(new List<object> { answer, motion == null ? null : (object)motion.Phase,
                                               motion == null ? null : (object)motion.Since,
                                               motion == null ? null : (object)motion.HoldLeft,
                                               motion == null ? null : (object)motion.FromAlpha,
                                               motion == null ? null : (object)motion.ExitMs,
                                               motion == null ? null : (object)motion.Paused,
                                               motion == null ? null : (object)motion.Final });
            }
            return answers;
        }

        private static string Digest(byte[] bytes)
        {
            using (var sha = System.Security.Cryptography.SHA256.Create())
            {
                var text = new StringBuilder();
                foreach (byte b in sha.ComputeHash(bytes)) text.Append(b.ToString("x2"));
                return text.ToString();
            }
        }

        /// The icon's motion: (position, level), the next frame's wait and the turn per state, moment, fine and reduce;
        /// the head's colours per state and level; and the frames' pixels per size and fine, as digests.
        private static Dictionary<string, object> Icon(Dictionary<string, object> task)
        {
            var frames = new List<object>();
            foreach (object state in (List<object>)task["states"])
                foreach (object fine in (List<object>)task["fines"])
                    foreach (bool reduced in new[] { false, true })
                        foreach (object moment in (List<object>)task["moments"])
                        {
                            string s = (string)state;
                            double at = (double)moment;
                            int steps = (int)(double)fine;
                            frames.Add(new List<object> { TrayMotion.Frame(s, at, reduced, steps),
                                                          TrayMotion.FrameMs(s, at, reduced, steps),
                                                          TrayMotion.Turn(s, at) });
                        }
            var colours = new List<object>();
            foreach (object state in (List<object>)task["states"])
            {
                int[] head = TrayMotion.HeadColour((string)state);
                var levels = new List<object>();
                for (int level = -1; level <= TrayMotion.Levels; level++) levels.Add(TrayMotion.LevelColour(head, level));
                colours.Add(new List<object> { head, levels, TrayMotion.BrandState((string)state) });
            }
            var pictures = new List<object>();
            foreach (object size in (List<object>)task["sizes"])
                foreach (object fine in (List<object>)task["fines"])
                {
                    var made = new IconFrames((int)(double)size, (int)(double)fine, Field(task, "look") as string);
                    var composed = new List<object>();
                    foreach (object state in (List<object>)task["states"])
                        for (int position = 0; position < made.Count; position += (int)(double)task["stride"])
                            composed.Add(Digest(made.Compose(position, TrayMotion.LevelColour(TrayMotion.HeadColour((string)state), position % 24))));
                    pictures.Add(new List<object> { Digest(made.Ground), composed });
                }
            var allowed = new List<object>();
            for (int bits = 0; bits < 64; bits++)
                allowed.Add(TrayMotion.MotionAllowed((bits & 1) != 0, (bits & 2) != 0, (bits & 4) != 0, (bits & 8) != 0,
                                                     (bits & 16) != 0, (bits & 32) == 0));
            var lights = new List<object>();
            foreach (object word in (List<object>)task["words"]) lights.Add(TrayMotion.ForLight(word as string));
            return new Dictionary<string, object> { { "frames", frames }, { "colours", colours }, { "pictures", pictures },
                                                    { "allowed", allowed }, { "lights", lights } };
        }

        /// What every item of a plan is painted with in each look asked - theme, design, High Contrast - by the
        /// renderer's own rules: the corner, the text's and the chip's colour, a button's face in each state.
        private static Dictionary<string, object> Paint(Dictionary<string, object> task, Dictionary<string, TableTextCalc> tables)
        {
            var inner = (Dictionary<string, object>)task["of"];
            object made = Case(inner, tables);
            var map = made as Dictionary<string, object>;
            SurfacePlan plan = map != null ? (SurfacePlan)map["plan"] : (SurfacePlan)made;
            object system = Field(task, "system");
            if (system != null)
            {
                SurfaceRenderer.SystemColours = new Dictionary<string, int[]>();
                foreach (KeyValuePair<string, object> pair in (Dictionary<string, object>)system)
                    SurfaceRenderer.SystemColours[pair.Key] = Ints(pair.Value);
            }
            var looks = new List<object>();
            foreach (object entry in (List<object>)task["looks"])
            {
                var three = (List<object>)entry;
                var renderer = new SurfaceRenderer { Theme = (string)three[0], Design = (string)three[1], Contrast = (bool)three[2] };
                var items = new List<object>();
                foreach (PlanItem item in plan.Items)
                {
                    var paint = new Dictionary<string, object>();
                    if (item.ContainsKey("radius") || item.ContainsKey("corner")) paint["corner"] = renderer.Corner(item, plan.Scale);
                    string kind = item.Kind;
                    if (kind == "text") paint["colour"] = renderer.Rgb((string)item["colour"]);
                    if (kind == "chip") paint["tone"] = renderer.Rgb((string)item["tone"]);
                    if (kind == "button")
                    {
                        var faces = new List<object>();
                        foreach (string state in new[] { "rest", "hover", "pressed", "busy" }) faces.Add(renderer.FaceColours(item, state));
                        paint["faces"] = faces;
                        paint["lifted"] = SurfaceRenderer.Lifted(item, null);
                    }
                    items.Add(paint);
                }
                looks.Add(new Dictionary<string, object> {
                    { "items", items }, { "depth", renderer.Depth() }, { "smoothing", renderer.Smoothing() },
                    { "control", renderer.ControlRadius(plan.Scale) }, { "canvas", renderer.Rgb("canvas") },
                    { "focus", renderer.Argb("focus") }, { "ink", renderer.ColorRef("ink") } });
            }
            SurfaceRenderer.SystemColours = null;
            return new Dictionary<string, object> { { "looks", looks } };
        }

        private static List<object> Segments(List<ShapeSegment> segments)
        {
            var listed = new List<object>();
            foreach (ShapeSegment segment in segments)
            {
                if (segment.Kind == "arc")
                    listed.Add(new List<object> { "arc", segment.Points[0], segment.Radius, segment.Start, segment.Sweep });
                else
                {
                    var one = new List<object> { segment.Kind };
                    foreach (double[] point in segment.Points) one.Add(point);
                    listed.Add(one);
                }
            }
            return listed;
        }

        /// brand/shape.py over the boxes asked: each outline, its flattened points, and the signed distance and
        /// inside test at each point asked.
        private static Dictionary<string, object> ShapeCase(Dictionary<string, object> task)
        {
            var outlines = new List<object>();
            var flats = new List<object>();
            var distances = new List<object>();
            var insides = new List<object>();
            foreach (object entry in (List<object>)task["boxes"])
            {
                var box = (List<object>)entry;
                var rect = ((List<object>)box[0]).ConvertAll(value => (double)value).ToArray();
                double radius = (double)box[1], smoothing = (double)box[2];
                List<ShapeSegment> outline = SurfaceShape.Outline(rect, radius, smoothing);
                outlines.Add(Segments(outline));
                flats.Add(SurfaceShape.Flatten(outline, 8));
                double halfWidth = (rect[2] - rect[0]) / 2.0, halfHeight = (rect[3] - rect[1]) / 2.0;
                var distance = new List<object>();
                var inside = new List<object>();
                foreach (object point in (List<object>)task["points"])
                {
                    var xy = (List<object>)point;
                    double x = (double)xy[0], y = (double)xy[1];
                    distance.Add(SurfaceShape.Distance(x, y, halfWidth, halfHeight, radius, smoothing));
                    inside.Add(SurfaceShape.Inside(x + rect[0] + halfWidth, y + rect[1] + halfHeight, rect, radius, smoothing));
                }
                distances.Add(distance);
                insides.Add(inside);
            }
            var designs = new List<object>();
            foreach (string design in SurfaceTheme.Designs) designs.Add(SurfaceShape.DesignSmoothing(design));
            return new Dictionary<string, object> { { "outlines", outlines }, { "flats", flats }, { "distances", distances },
                                                    { "insides", insides }, { "designs", designs } };
        }

        private static double[] Doubles(object value)
        {
            return ((List<object>)value).ConvertAll(entry => (double)entry).ToArray();
        }

        private static List<double[]> PointList(object value)
        {
            return ((List<object>)value).ConvertAll(entry => Doubles(entry));
        }

        private static uint Colour(object value)
        {
            return (uint)(double)value;
        }

        /// The painter's calls replayed into an offscreen canvas, in the order the script gives them: the pixels'
        /// digest, and how many GDI+ objects were left after the painter closed (0, or a leak).
        private static Dictionary<string, object> GdipCase(Dictionary<string, object> task)
        {
            SurfaceGdip.Acquire();
            try
            {
                using (var canvas = new SurfaceCanvas())
                {
                    var size = Ints(task["size"]);
                    canvas.Ensure(size[0], size[1]);
                    canvas.Smoothing = (double)task["smoothing"];
                    int before = SurfaceGdip.GdipObjects;
                    int format = (int)(double)task["format"];
                    using (var paint = new SurfacePainter(canvas, format))
                    {
                        if (SurfaceMath.Truthy(Field(task, "keep_solids"))) paint.KeepSolids();
                        foreach (object entry in (List<object>)task["calls"])
                        {
                            var call = (List<object>)entry;
                            switch ((string)call[0])
                            {
                                case "fill_round": paint.FillRound(Doubles(call[1]), (double)call[2], Colour(call[3])); break;
                                case "stroke_round": paint.StrokeRound(Doubles(call[1]), (double)call[2], Colour(call[3]), (double)call[4]); break;
                                case "fill_circle": paint.FillCircle((double)call[1], (double)call[2], (double)call[3], Colour(call[4])); break;
                                case "fill_polygon": paint.FillPolygon(PointList(call[1]), Colour(call[2])); break;
                                case "fill_ellipse": paint.FillEllipse((double)call[1], (double)call[2], (double)call[3], (double)call[4], Colour(call[5])); break;
                                case "stroke_lines": paint.StrokeLines(PointList(call[1]), Colour(call[2]), (double)call[3]); break;
                                case "clip_round": paint.ClipRound(Doubles(call[1]), (double)call[2]); break;
                                case "clip_rect": paint.ClipRect(Doubles(call[1])); break;
                                case "clip_none": paint.ClipNone(); break;
                                case "fade": paint.Fade(Doubles(call[1]), (double)call[2], (double)call[3], Ints(call[4])); break;
                                case "arc": paint.Arc((double)call[1], (double)call[2], (double)call[3], (double)call[4], (double)call[5], Colour(call[6]), (double)call[7]); break;
                                case "glow": paint.Glow((double)call[1], (double)call[2], (double)call[3], PointList(call[4]), Ints(call[5]), (double)call[6]); break;
                                default: throw new NotSupportedException((string)call[0]);
                            }
                        }
                    }
                    int left = SurfaceGdip.GdipObjects - before;
                    return new Dictionary<string, object> { { "pixels", Digest(canvas.Pixels()) }, { "left", left } };
                }
            }
            finally
            {
                SurfaceGdip.Release();
            }
        }

        /// The shadows' masks in the order asked (the order matters: a well reuses its turned twin), each as its size,
        /// centre, extent and the coverage's digest; brand's recipes per theme and design; shadow_step.
        private static Dictionary<string, object> ElevationCase(Dictionary<string, object> task)
        {
            var masks = new List<object>();
            foreach (object entry in (List<object>)task["masks"])
            {
                var ask = (List<object>)entry;
                object smoothing = ask[ask.Count - 1];
                double? smooth = smoothing == null ? (double?)null : (double)smoothing;
                ShadowMask mask = (string)ask[0] == "lift"
                    ? SurfaceElevation.LiftCoverage((int)(double)ask[1], (int)(double)ask[2], (double)ask[3], (double)ask[4], smooth)
                    : SurfaceElevation.WellCoverage((int)(double)ask[1], (int)(double)ask[2], (double)ask[3], (double)ask[4],
                                                    (double)ask[5], (double)ask[6], smooth);
                masks.Add(new List<object> { mask.Width, mask.Height, mask.Centre, mask.Extent, Digest(mask.Coverage) });
            }
            var recipes = new List<object>();
            foreach (string recipe in new[] { "card", "control", "inset", "tile" })
                foreach (string theme in SurfaceTheme.Themes)
                    foreach (string design in SurfaceTheme.Designs)
                    {
                        var listed = new List<object>();
                        foreach (SurfaceShadow shadow in SurfaceElevation.RecipeShadows(recipe, theme, design))
                            listed.Add(new List<object> { shadow.Dx, shadow.Dy, shadow.Blur, shadow.Token, shadow.Alpha, shadow.Inset });
                        recipes.Add(listed);
                    }
            var steps = new List<object>();
            foreach (object value in (List<object>)task["steps"]) steps.Add(SurfaceElevation.ShadowStep((double)value));
            var grounds = new List<object>();
            foreach (string theme in SurfaceTheme.Themes)
                foreach (string design in SurfaceTheme.Designs) grounds.Add(SurfaceTheme.Hex(SurfaceElevation.TileGround(theme, design)));
            return new Dictionary<string, object> { { "masks", masks }, { "recipes", recipes }, { "steps", steps }, { "grounds", grounds } };
        }

        private static List<object> Shapes(List<DayShape> shapes)
        {
            var listed = new List<object>();
            foreach (DayShape shape in shapes) listed.Add(new List<object> { shape.Kind, shape.Numbers, shape.Colour, shape.Opacity });
            return listed;
        }

        /// A day's scene and specks at each moment asked (scene_frame, speck_frame with and without `within`), the
        /// specks' reach, and the icon's mark at each point asked (mark_colour).
        private static Dictionary<string, object> DaysCase(Dictionary<string, object> task)
        {
            string look = (string)task["look"];
            var scenes = new List<object>();
            var specks = new List<object>();
            foreach (object entry in (List<object>)task["moments"])
            {
                double ms = (double)entry;
                scenes.Add(Shapes(SurfaceDays.SceneFrame(look, ms)));
                var at = new List<object> { Shapes(SurfaceDays.SpeckFrame(look, ms)) };
                foreach (object within in (List<object>)task["within"]) at.Add(Shapes(SurfaceDays.SpeckFrame(look, ms, Doubles(within))));
                specks.Add(at);
            }
            var marks = new List<object>();
            foreach (object entry in (List<object>)task["points"])
            {
                double[] point = Doubles(entry);
                marks.Add(SurfaceDays.MarkColour(look, point[0], point[1]));
            }
            var paths = new List<object>();
            foreach (object entry in (List<object>)task["paths"])
            {
                var ask = (List<object>)entry;
                paths.Add(SurfaceDays.PathPoints((string)ask[0], (int)(double)ask[1]));
            }
            return new Dictionary<string, object> { { "scenes", scenes }, { "specks", specks }, { "reach", SurfaceDays.SpeckReach(look) },
                                                    { "marks", marks }, { "paths", paths } };
        }

        private static LightFrame FrameFrom(object value)
        {
            var map = value as Dictionary<string, object>;
            if (map == null) return null;
            object arc = Field(map, "arc");
            return new LightFrame { Dim = (double)map["dim"], Opacity = (double)map["opacity"], Spread = (double)map["spread"],
                                    Arc = arc == null ? (double?)null : (double)arc };
        }

        /// A view drawn into memory by the renderer's own fonts, step after step as the popup draws it - whole frames
        /// with a hover, a press, a focus, glides and faces part way, the light alone, the day alone, the seventh
        /// press's sweep - each step's pixels by digest; the plan its fonts laid out; and how many GDI+ objects were
        /// left once the renderer closed (Renderer.draw, draw_halo, draw_scene; comparison A's pixel half).
        private static Dictionary<string, object> PixelsCase(Dictionary<string, object> task)
        {
            object system = Field(task, "system");
            SurfaceRenderer.SystemColours = null;
            if (system != null)
            {
                SurfaceRenderer.SystemColours = new Dictionary<string, int[]>();
                foreach (KeyValuePair<string, object> pair in (Dictionary<string, object>)system)
                    SurfaceRenderer.SystemColours[pair.Key] = Ints(pair.Value);
            }
            SurfaceFonts.Pinned = Field(task, "pinned") as string;
            int before = SurfaceGdip.GdipObjects;
            var digests = new List<object>();
            SurfacePlan plan;
            try
            {
                using (SurfaceRenderer renderer = SurfaceRenderer.Open())
                {
                    var look = (List<object>)task["look"];
                    renderer.Theme = (string)look[0];
                    renderer.Design = (string)look[1];
                    renderer.Contrast = (bool)look[2];
                    renderer.Lone = (bool)task["lone"];
                    renderer.Letters = Field(task, "letters") as string;
                    plan = renderer.Layout((Dictionary<string, object>)task["vm"], Number(task, "scale"), (string)task["locale"]);
                    foreach (object entry in (List<object>)task["steps"])
                    {
                        var step = (Dictionary<string, object>)entry;
                        switch ((string)step["do"])
                        {
                            case "draw":
                            {
                                var glides = new Dictionary<object, double>();
                                foreach (object glide in (List<object>)step["glides"])
                                {
                                    var pair = (List<object>)glide;
                                    glides[TargetOf(pair[0])] = (double)pair[1];
                                }
                                var faces = new Dictionary<object, ButtonFace>();
                                foreach (object face in (List<object>)step["faces"])
                                {
                                    var four = (List<object>)face;
                                    faces[TargetOf(four[0])] = new ButtonFace(Ints(four[1]), Ints(four[2]), (double)four[3]);
                                }
                                renderer.Draw(plan, FrameFrom(Field(step, "frame")), TargetOf(Field(step, "hover")), TargetOf(Field(step, "pressed")),
                                              TargetOf(Field(step, "focus")), glides, (double)step["scene_ms"], faces);
                                break;
                            }
                            case "halo":
                                renderer.DrawHalo(plan, FrameFrom(Field(step, "frame")));
                                break;
                            case "scene":
                                renderer.DrawScene(plan, (double)step["ms"]);
                                break;
                            case "still":
                            {
                                object[] still = SurfaceLayers.CardStill(renderer, plan);
                                using (var layers = new CardLayers(IntPtr.Zero))
                                {
                                    layers.Shade(renderer, plan);
                                    digests.Add(new List<object> { still[0], still[1], Digest((byte[])still[2]), layers.Margin,
                                                                   layers.Shadows.Count > 0 ? Digest(layers.Picture.Pixels()) : null });
                                }
                                continue;
                            }
                            case "sweep":
                                renderer.SweepMs = (double)step["ms"];
                                renderer.DrawHalo(plan, FrameFrom(Field(step, "frame")));
                                renderer.SweepMs = null;
                                break;
                            default:
                                throw new NotSupportedException((string)step["do"]);
                        }
                        SurfaceNative.GdiFlush();
                        digests.Add(new List<object> { Digest(renderer.Canvas.Pixels()), renderer.HaloRows });
                    }
                }
            }
            finally
            {
                SurfaceFonts.Pinned = null;
                SurfaceRenderer.SystemColours = null;
            }
            return new Dictionary<string, object> { { "plan", plan }, { "pixels", digests }, { "left", SurfaceGdip.GdipObjects - before } };
        }

        /// The icon's menu (draw_menu at each selection asked) or its card (draw_tip, then draw_tip_light at each further
        /// frame) drawn by the renderer's own fonts: the plan, each picture's digest, and the GDI+ objects left.
        private static Dictionary<string, object> DrawnCase(Dictionary<string, object> task)
        {
            object system = Field(task, "system");
            SurfaceRenderer.SystemColours = null;
            if (system != null)
            {
                SurfaceRenderer.SystemColours = new Dictionary<string, int[]>();
                foreach (KeyValuePair<string, object> pair in (Dictionary<string, object>)system)
                    SurfaceRenderer.SystemColours[pair.Key] = Ints(pair.Value);
            }
            SurfaceFonts.Pinned = Field(task, "pinned") as string;
            int before = SurfaceGdip.GdipObjects;
            var digests = new List<object>();
            SurfacePlan plan;
            try
            {
                using (SurfaceRenderer renderer = SurfaceRenderer.Open())
                {
                    var look = (List<object>)task["look"];
                    renderer.Theme = (string)look[0];
                    renderer.Design = (string)look[1];
                    renderer.Contrast = (bool)look[2];
                    renderer.Letters = Field(task, "letters") as string;
                    string locale = (string)task["locale"];
                    double scale = Number(task, "scale");
                    if ((string)task["what"] == "menu")
                    {
                        plan = renderer.MenuLayout((List<object>)task["entries"], scale, locale, Index(Field(task, "max_width")));
                        foreach (object selected in (List<object>)task["selected"])
                            digests.Add(Digest(renderer.DrawMenu(plan, Index(selected)).Pixels()));
                    }
                    else
                    {
                        string day = SurfaceRenderer.TipDay(Field(task, "day") as string, renderer.Contrast, renderer.Design);
                        plan = renderer.TipLayout((Dictionary<string, object>)task["parts"], Field(task, "light"), scale, locale, day);
                        var frames = (List<object>)task["frames"];
                        digests.Add(Digest(renderer.DrawTip(plan, FrameFrom(frames[0])).Pixels()));
                        for (int i = 1; i < frames.Count; i++) digests.Add(Digest(renderer.DrawTipLight(plan, FrameFrom(frames[i])).Pixels()));
                    }
                }
            }
            finally
            {
                SurfaceFonts.Pinned = null;
                SurfaceRenderer.SystemColours = null;
            }
            return new Dictionary<string, object> { { "plan", plan }, { "pixels", digests }, { "left", SurfaceGdip.GdipObjects - before } };
        }

        /// The notification card offscreen: the corner's coverage at the radii asked, or one card's life step by step -
        /// each layer's digest, the frame's key and margin, the light's breath, a hover drawn again.
        private static object CardsCase(Dictionary<string, object> task)
        {
            object corners = Field(task, "corners");
            if (corners != null)
            {
                var found = new List<object>();
                foreach (object entry in (List<object>)corners)
                {
                    var pair = (List<object>)entry;
                    byte[][] rows = CardCorner.Coverage((double)pair[0], (double)pair[1]);
                    var whole = new List<byte>();
                    foreach (byte[] row in rows) whole.AddRange(row);
                    found.Add(Digest(whole.ToArray()));
                }
                return found;
            }
            object system = Field(task, "system");
            SurfaceRenderer.SystemColours = null;
            if (system != null)
            {
                SurfaceRenderer.SystemColours = new Dictionary<string, int[]>();
                foreach (KeyValuePair<string, object> pair in (Dictionary<string, object>)system)
                    SurfaceRenderer.SystemColours[pair.Key] = Ints(pair.Value);
            }
            SurfaceFonts.Pinned = Field(task, "pinned") as string;
            int before = SurfaceGdip.GdipObjects;
            var steps = new List<object>();
            try
            {
                using (var card = new NoticeCard(null, (Dictionary<string, object>)task["vm"], (string)task["title"], (bool)task["stays"],
                                                 (double)task["hold"], 0, (double)task["dpi"], Ints(task["work"]),
                                                 (Dictionary<string, object>)task["drawn"], false, Field(task, "letters") as string))
                {
                    double entrance = (double)task["entrance"];
                    foreach (double moment in new[] { 100.0, entrance })
                    {
                        Dictionary<string, object> painted = card.Paint(moment);
                        var key = new List<object>();
                        foreach (string part in ((string)painted["key"]).Split(',')) key.Add(double.Parse(part, System.Globalization.CultureInfo.InvariantCulture));
                        steps.Add(new List<object> { Digest(card.Body.Pixels()), Digest(card.Shadow.Pixels()), key, painted["margin"] });
                    }
                    card.DrawLight(card.Born + 1700);
                    steps.Add(new List<object> { Digest(card.Image.Pixels), Digest(card.Body.Pixels()) });
                    card.Hover = TargetOf(Field(task, "hover"));
                    card.Redraw();
                    card.Paint(entrance + 50);
                    string first = Digest(card.Body.Pixels());
                    bool breathed = card.Breathe(2900);
                    steps.Add(new List<object> { first, breathed, Digest(card.Body.Pixels()) });
                }
            }
            finally
            {
                SurfaceFonts.Pinned = null;
                SurfaceRenderer.SystemColours = null;
            }
            return new Dictionary<string, object> { { "steps", steps }, { "left", SurfaceGdip.GdipObjects - before } };
        }

        // ----------------------------------------------------------------------------- the dump

        /// Any plan value as Json.Write takes it: numbers as doubles, arrays and tuples as lists, a plan as the Python's
        /// dictionary.
        internal static object Dump(object value)
        {
            if (value == null || value is string || value is bool || value is double) return value;
            if (value is int) return (double)(int)value;
            if (value is long) return (double)(long)value;
            if (value is uint) return (double)(uint)value;
            if (value is float) return (double)(float)value;
            if (value is int?) return (double)((int?)value).Value;
            if (value is double?) return ((double?)value).Value;
            if (value is CardFrame) return Dump(FrameOf((CardFrame)value));
            var target = value as SurfaceTarget;
            if (target != null) return Dump(target.ToList());
            var plan = value as SurfacePlan;
            if (plan != null) return DumpPlan(plan);
            var map = value as IDictionary<string, object>;
            if (map != null)
            {
                var dumped = new Dictionary<string, object>();
                foreach (KeyValuePair<string, object> pair in map) dumped[pair.Key] = Dump(pair.Value);
                return dumped;
            }
            if (value is KeyValuePair<object, int[]>)
            {
                var pair = (KeyValuePair<object, int[]>)value;
                return new List<object> { Dump(pair.Key), Dump(pair.Value) };
            }
            var list = value as IEnumerable;
            if (list != null)
            {
                var dumped = new List<object>();
                foreach (object entry in list) dumped.Add(Dump(entry));
                return dumped;
            }
            throw new FormatException("cannot dump a " + value.GetType().Name);
        }

        private static Dictionary<string, object> DumpPlan(SurfacePlan plan)
        {
            var dumped = new Dictionary<string, object>();
            dumped["size"] = Dump(plan.Size);
            dumped["card"] = Dump(plan.Card);
            dumped["items"] = Dump(plan.Items);
            dumped["targets"] = Dump(plan.Targets);
            dumped["scale"] = plan.Scale;
            if (plan.Rows != null) dumped["rows"] = Dump(plan.Rows);
            if (plan.Rtl.HasValue) dumped["rtl"] = plan.Rtl.Value;
            return dumped;
        }
    }
}

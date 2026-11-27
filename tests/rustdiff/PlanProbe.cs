// The plan proxy's entry into the C# host's surfaces (S6.4f, P6-DESIGN 3.4 "drawn"): compiled with gui/host.sources'
// [contract], [surface] and [generated] files by tests/rustdiff/planproxy.py, never part of the product. It reads one
// question per line on standard input and answers each on one line of standard output, until the input ends:
//
//   {"op": "render", "tables": {...}, "case": {...}}  the render mode itself (SurfaceRender.RunJob) on a one-case job: the
//                                                     case's plan dump, exactly as tests/test_surface_parity.py reads it
//   {"op": <name>, ...}                               one of the surfaces' own functions the render mode runs only over
//                                                     comparison A's fixed matrix (TrayMotion, PopupMotion, PopupPlace,
//                                                     SurfaceElevation), on the arguments a test hands in
//
// and answers {"ok": value} or {"error": "<class>: <message>"}. It makes no window, loads no DLL, draws nothing on a screen
// and starts nothing.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace CodexAutoResume
{
    internal static class PlanProbeDriver
    {
        private static string folder;

        private static int Main(string[] args)
        {
            folder = Path.Combine(Path.GetTempPath(), "car-plan-probe-" + System.Diagnostics.Process.GetCurrentProcess().Id);
            Directory.CreateDirectory(folder);
            var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
            var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { NewLine = "\n", AutoFlush = true };
            string line;
            try
            {
                while ((line = input.ReadLine()) != null)
                {
                    if (line.Trim().Length == 0) continue;
                    string answer;
                    try
                    {
                        var call = (Dictionary<string, object>)Json.Parse(line);
                        answer = Json.Write(new Dictionary<string, object> { { "ok", Answer((string)call["op"], call) } });
                    }
                    catch (Exception exc)
                    {
                        answer = Json.Write(new Dictionary<string, object> { { "error", exc.GetType().Name + ": " + exc.Message } });
                    }
                    output.WriteLine(answer);
                }
            }
            finally
            {
                try { Directory.Delete(folder, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            }
            return 0;
        }

        private static object F(Dictionary<string, object> call, string name) { return SurfaceRender.Field(call, name); }

        private static double D(Dictionary<string, object> call, string name) { return (double)call[name]; }

        private static int I(Dictionary<string, object> call, string name) { return (int)(double)call[name]; }

        private static bool B(Dictionary<string, object> call, string name) { return Equals(F(call, name), true); }

        private static int[] Ints(object value)
        {
            if (value == null) return null;
            var list = (List<object>)value;
            var ints = new int[list.Count];
            for (int i = 0; i < ints.Length; i++) ints[i] = (int)(double)list[i];
            return ints;
        }

        private static double? Maybe(object value) { return value == null ? (double?)null : (double)value; }

        private static List<KeyValuePair<object, int[]>> Targets(object value)
        {
            var targets = new List<KeyValuePair<object, int[]>>();
            foreach (object entry in (List<object>)value)
            {
                var pair = (List<object>)entry;
                targets.Add(new KeyValuePair<object, int[]>(SurfaceRender.TargetOf(pair[0]), Ints(pair[1])));
            }
            return targets;
        }

        private static Dictionary<object, bool> Switches(object value)
        {
            if (value == null) return null;
            var table = new Dictionary<object, bool>();
            foreach (object entry in (List<object>)value)
            {
                var pair = (List<object>)entry;
                table[SurfaceRender.TargetOf(pair[0])] = Equals(pair[1], true);
            }
            return table;
        }

        private static Glide GlideOf(object value)
        {
            var three = (List<object>)value;
            return new Glide((double)three[0], (double)three[1], (double)three[2]);
        }

        private static object Mask(ShadowMask mask)
        {
            var coverage = new List<object>(mask.Coverage.Length);
            foreach (byte level in mask.Coverage) coverage.Add((double)level);
            return new Dictionary<string, object> { { "key", mask.Key }, { "width", (double)mask.Width },
                                                    { "height", (double)mask.Height }, { "centre", SurfaceRender.Dump(mask.Centre) },
                                                    { "extent", (double)mask.Extent }, { "coverage", coverage } };
        }

        private static List<object> FloatList(List<FloatShadow> shadows)
        {
            var listed = new List<object>();
            foreach (FloatShadow s in shadows) listed.Add(new List<object> { s.Dx, s.Dy, s.Blur, s.Colour, s.Alpha });
            return listed;
        }

        private static List<FloatShadow> FloatsOf(object value)
        {
            var shadows = new List<FloatShadow>();
            foreach (object entry in (List<object>)value)
            {
                var five = (List<object>)entry;
                shadows.Add(new FloatShadow((double)five[0], (double)five[1], (double)five[2], (string)five[3], (double)five[4]));
            }
            return shadows;
        }

        private static object Render(Dictionary<string, object> call)
        {
            string job = Path.Combine(folder, "job.json"), found = Path.Combine(folder, "out.json");
            var task = new Dictionary<string, object>((Dictionary<string, object>)call["case"]);
            task["id"] = "case";
            File.WriteAllText(job, Json.Write(new Dictionary<string, object> {
                { "format", SurfaceRender.Format }, { "tables", F(call, "tables") ?? new Dictionary<string, object>() },
                { "cases", new List<object> { task } } }), new UTF8Encoding(false));
            if (File.Exists(found)) File.Delete(found);
            SurfaceRender.RunJob(job, found);
            var answer = (Dictionary<string, object>)Json.Parse(File.ReadAllText(found, new UTF8Encoding(false)));
            object error;
            if (answer.TryGetValue("error", out error)) throw new InvalidDataException((string)error);
            var only = (Dictionary<string, object>)((List<object>)answer["cases"])[0];
            if (only.TryGetValue("error", out error)) throw new InvalidDataException((string)error);
            return only["plan"];
        }

        private static object Answer(string op, Dictionary<string, object> call)
        {
            if (op == "render") return Render(call);
            // ------------------------------------------------------------- the icon (gui/TrayMotion.cs)
            if (op == "icon_frame")
                return SurfaceRender.Dump(TrayMotion.Frame((string)call["state"], D(call, "elapsed"), B(call, "reduced"), I(call, "fine")));
            if (op == "icon_frame_ms")
                return SurfaceRender.Dump(TrayMotion.FrameMs((string)call["state"], D(call, "elapsed"), B(call, "reduced"), I(call, "fine")));
            if (op == "icon_turn") return SurfaceRender.Dump(TrayMotion.Turn((string)call["state"], D(call, "elapsed")));
            if (op == "icon_brand_state") return TrayMotion.BrandState((string)call["state"]);
            if (op == "icon_head_colour") return SurfaceRender.Dump(TrayMotion.HeadColour((string)call["state"]));
            if (op == "icon_level_colour")
                return SurfaceRender.Dump(TrayMotion.LevelColour(Ints(call["colour"]), (int)D(call, "level")));
            if (op == "icon_motion_allowed")
                return TrayMotion.MotionAllowed(B(call, "reduced"), B(call, "contrast"), B(call, "battery_saver"), B(call, "locked"),
                                                B(call, "hidden"), B(call, "frames"));
            // ------------------------------------------------------------- the popup's motion (gui/PopupMotion.cs)
            if (op == "halo")
            {
                LightFrame frame = PopupMotion.Halo((string)call["state"], D(call, "elapsed"), B(call, "reduced"), (string)call["design"]);
                return frame == null ? null : SurfaceRender.Dump(frame.ToMap());
            }
            if (op == "animates") return PopupMotion.Animates((string)call["state"], B(call, "reduced"));
            if (op == "opening") return SurfaceRender.Dump(PopupMotion.Opening(D(call, "elapsed"), I(call, "rise")));
            if (op == "closing") return SurfaceRender.Dump(PopupMotion.Closing(D(call, "elapsed"), I(call, "alpha")));
            if (op == "face_amount")
                return SurfaceRender.Dump(PopupMotion.FaceAmount(D(call, "started"), D(call, "length"), D(call, "now")));
            if (op == "face_length") return (double)PopupMotion.FaceLength((string)call["before"], (string)call["after"]);
            if (op == "mixed") return SurfaceRender.Dump(PopupMotion.Mixed(Ints(call["one"]), Ints(call["other"]), D(call, "amount")));
            if (op == "glide_amount") return SurfaceRender.Dump(PopupMotion.GlideAmount(GlideOf(call["glide"]), D(call, "now")));
            if (op == "next_glides")
            {
                var running = new Dictionary<object, Glide>();
                foreach (object entry in (List<object>)call["glides"])
                {
                    var pair = (List<object>)entry;
                    running[SurfaceRender.TargetOf(pair[0])] = GlideOf(pair[1]);
                }
                var made = new List<object>();
                foreach (KeyValuePair<object, Glide> pair in PopupMotion.NextGlides(Switches(call["seen"]), Switches(F(call, "previous")),
                                                                                 running, D(call, "now"), B(call, "animate")))
                    made.Add(new List<object> { SurfaceRender.Dump(pair.Key),
                                                new List<object> { pair.Value.Started, pair.Value.Begin, pair.Value.End } });
                return made;
            }
            // ------------------------------------------------------------- where it goes (gui/PopupPlace.cs)
            if (op == "taskbar_edge") return PopupPlace.TaskbarEdge(Ints(call["work"]), Ints(call["monitor"]), Ints(F(call, "anchor")));
            if (op == "place")
            {
                string edge;
                int[] at = PopupPlace.Place(Ints(call["size"]), Ints(call["work"]), Ints(call["monitor"]), Ints(F(call, "icon")),
                                            Ints(F(call, "cursor")), I(call, "gap"), out edge);
                return new List<object> { (double)at[0], (double)at[1], edge };
            }
            if (op == "hit_test") return SurfaceRender.Dump(PopupPlace.HitTest(Targets(call["targets"]), I(call, "x"), I(call, "y")));
            if (op == "focus_order") return SurfaceRender.Dump(PopupPlace.FocusOrder(Targets(call["targets"])));
            if (op == "next_focus")
            {
                var order = new List<object>();
                foreach (object entry in (List<object>)call["order"]) order.Add(SurfaceRender.TargetOf(entry));
                return SurfaceRender.Dump(PopupPlace.NextFocus(order, SurfaceRender.TargetOf(F(call, "current")), B(call, "backwards")));
            }
            // ------------------------------------------------------------- the lifts and wells (gui/SurfaceElevation.cs)
            if (op == "lift_coverage")
                return Mask(SurfaceElevation.LiftCoverage(I(call, "width"), I(call, "height"), D(call, "radius"), D(call, "blur"),
                                                          Maybe(F(call, "smoothing"))));
            if (op == "well_coverage")
                return Mask(SurfaceElevation.WellCoverage(I(call, "width"), I(call, "height"), D(call, "radius"), D(call, "blur"),
                                                          D(call, "dx"), D(call, "dy"), Maybe(F(call, "smoothing"))));
            if (op == "shadow_step") return (double)SurfaceElevation.ShadowStep(D(call, "value"));
            if (op == "recipe_shadows")
            {
                var listed = new List<object>();
                foreach (SurfaceShadow s in SurfaceElevation.RecipeShadows((string)call["recipe"], (string)call["theme"], (string)call["design"]))
                    listed.Add(new List<object> { s.Dx, s.Dy, s.Blur, s.Token, s.Alpha, s.Inset });
                return listed;
            }
            if (op == "tile_ground") return SurfaceTheme.Hex(SurfaceElevation.TileGround((string)call["theme"], (string)call["design"]));
            if (op == "share_columns") return SurfaceRender.Dump(PopupLayout.ShareColumns(I(call, "available"), Ints(call["needs"])));
            // ------------------------------------------------------------- the notification card (gui/CardPlan.cs)
            if (op == "entrance") return SurfaceRender.Dump(CardPlan.Entrance(D(call, "elapsed"), B(call, "reduced")));
            if (op == "leaving")
                return CardPlan.Leaving(D(call, "elapsed"), D(call, "start_alpha"), B(call, "reduced"), D(call, "duration"));
            if (op == "rise_vector") return SurfaceRender.Dump(CardPlan.RiseVector(F(call, "edge") as string));
            if (op == "hold_ms") return CardPlan.HoldFor(F(call, "duration"));
            if (op == "stack_direction")
                return (double)CardPlan.StackDirection((string)call["edge"], I(call, "y"), I(call, "height"), Ints(call["work"]));
            if (op == "stack_positions")
            {
                var sizes = new List<int[]>();
                foreach (object size in (List<object>)call["sizes"]) sizes.Add(Ints(size));
                string edge;
                List<int[]> positions = CardPlan.StackPositions(sizes, Ints(call["work"]), Ints(call["monitor"]), Ints(F(call, "anchor")),
                                                                I(call, "gap"), I(call, "spacing"), out edge);
                return new List<object> { SurfaceRender.Dump(positions), edge };
            }
            if (op == "float_shadows") return FloatList(CardPlan.FloatShadows((string)call["theme"], (string)call["design"]));
            if (op == "shadow_at") return FloatList(CardPlan.ShadowAt(FloatsOf(call["shadows"]), D(call, "depth")));
            if (op == "depth_level") return (double)CardPlan.DepthLevel(D(call, "depth"));
            if (op == "shadow_margin") return (double)CardPlan.ShadowMargin(FloatsOf(call["shadows"]), D(call, "scale"));
            throw new NotSupportedException("no op " + op);
        }
    }
}

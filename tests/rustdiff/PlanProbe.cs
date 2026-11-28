// The plan proxy's entry into the C# host's surfaces (S6.4f, P6-DESIGN 3.4 "drawn"): compiled with gui/host.sources'
// [contract], [surface] and [generated] files by tests/rustdiff/planproxy.py, never part of the product. It reads one
// question per line on standard input and answers each on one line of standard output, until the input ends:
//
//   {"op": "render", "tables": {...}, "case": {...}}  the render mode itself (SurfaceRender.RunJob) on a one-case job: the
//                                                     case's plan dump, exactly as tests/test_surface_parity.py reads it
//   {"op": <name>, ...}                               one of the surfaces' own functions the render mode runs only over
//                                                     comparison A's fixed matrix (TrayMotion, PopupMotion, PopupPlace,
//                                                     SurfaceElevation), on the arguments a test hands in
//   {"op": "layout_kept" | "renderer_*", ...}         (S6.4f2) a plan laid out from a measure table, or by a renderer's
//                                                     own fonts, kept under a handle so a renderer kept the same way
//                                                     draws it (Renderer.draw, draw_halo, draw_scene, layers.card_still);
//                                                     each picture written as raw BGRA in the probe's own folder and
//                                                     answered by its path; and notice_card.corner_coverage (CardCorner)
//   {"op": "renderer_images" | "plan_from_dict" | "layers_*" | "renderer_tip_*" | "tip_place" | ...}
//                                                     (S6.4f3) what a test reads of a renderer's own state (its kept
//                                                     shadow images and ground key, the GDI+ count), a plan of the
//                                                     test's own, a draw without its words or with stood-in specks,
//                                                     the shadow window's layers (CardLayers, no window), the icon's
//                                                     card (TipLayout, DrawTip, DrawTipLight) and its place
//
// and answers {"ok": value} or {"error": "<class>: <message>"}. It makes no window, draws nothing on a screen and starts
// nothing; it draws into memory only, with this machine's fonts (GDI and GDI+, as the render mode's pictures are made).
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace CodexAutoResume
{
    internal static class PlanProbeDriver
    {
        private static string folder;
        private static StreamReader input;
        private static StreamWriter output;
        private static readonly Dictionary<string, byte[]> composed = new Dictionary<string, byte[]>();

        /// A callable the test handed in, asked back over the same pipe while a question is being answered: one line
        /// {"ask": name, "args": [...]} out, one line {"answer": value} or {"raise": "<class>: <message>"} back.
        private static object AskBack(string name, params object[] args)
        {
            output.WriteLine(Json.Write(new Dictionary<string, object> { { "ask", name }, { "args", new List<object>(args) } }));
            var found = (Dictionary<string, object>)Json.Parse(input.ReadLine());
            object raised;
            if (found.TryGetValue("raise", out raised)) throw new AskBackFailed((string)raised);
            return found["answer"];
        }

        private sealed class AskBackFailed : Exception
        {
            internal AskBackFailed(string message) : base(message) { }
        }

        /// The test's `lacks(face, text)` asked back, or null when it handed none (every face taken as whole).
        private static Func<string, string, string> Lacks(Dictionary<string, object> call)
        {
            if (!B(call, "lacks")) return null;
            return (face, text) => (string)AskBack("lacks", face, text);
        }

        private static List<object> Levels(byte[] bytes)
        {
            var levels = new List<object>(bytes.Length);
            foreach (byte level in bytes) levels.Add((double)level);
            return levels;
        }

        private static int Main(string[] args)
        {
            folder = Path.Combine(Path.GetTempPath(), "car-plan-probe-" + System.Diagnostics.Process.GetCurrentProcess().Id);
            Directory.CreateDirectory(folder);
            input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
            output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { NewLine = "\n", AutoFlush = true };
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

        // ------------------------------------------------------------- objects kept between questions (plans, renderers)
        private static readonly Dictionary<int, object> kept = new Dictionary<int, object>();
        private static int nextHandle = 1, written;

        private static double Keep(object value)
        {
            int handle = nextHandle++;
            kept[handle] = value;
            return handle;
        }

        private static T Kept<T>(Dictionary<string, object> call, string key) where T : class
        {
            object value;
            if (!kept.TryGetValue(I(call, key), out value) || !(value is T))
                throw new KeyNotFoundException(key + " names no " + typeof(T).Name);
            return (T)value;
        }

        /// The renderer the call names, in the look the caller's renderer has when it calls (its theme, design, High
        /// Contrast, lone and sweep are attributes the Python test sets on its renderer).
        private static SurfaceRenderer Look(Dictionary<string, object> call)
        {
            SurfaceRenderer renderer = Kept<SurfaceRenderer>(call, "renderer");
            var look = F(call, "look") as Dictionary<string, object>;
            if (look != null)
            {
                renderer.Theme = (string)look["theme"];
                renderer.Design = (string)look["design"];
                renderer.Contrast = SurfaceMath.Truthy(look["contrast"]);
                renderer.Lone = SurfaceMath.Truthy(look["lone"]);
                object sweep = SurfaceRender.Field(look, "sweep_ms");
                renderer.SweepMs = sweep == null ? (double?)null : (double)sweep;
            }
            if (call.ContainsKey("letters")) renderer.Letters = F(call, "letters") as string;
            // The face the test stands in for Windows' UI font (fonts.windows_ui_face, or a message_face it patched),
            // as a render job stands one in: SurfaceFonts.Pinned, read when the fonts are made.
            if (call.ContainsKey("pinned")) SurfaceFonts.Pinned = F(call, "pinned") as string;
            return renderer;
        }

        private static LightFrame FrameOf(object value)
        {
            var map = value as Dictionary<string, object>;
            if (map == null) return null;
            object arc = SurfaceRender.Field(map, "arc");
            return new LightFrame { Dim = (double)map["dim"], Opacity = (double)map["opacity"], Spread = (double)map["spread"],
                                    Arc = arc == null ? (double?)null : (double)arc };
        }

        /// A picture as a file in the probe's folder (raw BGRA, top row first), answered by its path.
        private static object Picture(byte[] bgra, int width, int height)
        {
            string path = Path.Combine(folder, "picture-" + (written++).ToString("D6") + ".bgra");
            File.WriteAllBytes(path, bgra);
            return new Dictionary<string, object> { { "file", path }, { "bytes", (double)bgra.Length }, { "width", (double)width },
                                                    { "height", (double)height } };
        }

        private static object Rows(SurfaceRenderer renderer)
        {
            return SurfaceRender.Dump(renderer.HaloRows);
        }

        private static object KeptPlan(SurfacePlan plan)
        {
            return new Dictionary<string, object> { { "plan", Keep(plan) }, { "dump", SurfaceRender.Dump(plan) } };
        }

        /// The popup's and the card's plan from a measure table, kept so a renderer can draw it; the renderer's own
        /// questions (Renderer: open, use, measure, lines, fonts, layout, draw, draw_halo, draw_scene, pixels,
        /// halo_rows, face_colours, close; layers.card_still); the card's corner (notice_card.corner_coverage). False
        /// when `op` is none of them.
        private static bool Drawn(string op, Dictionary<string, object> call, out object answer)
        {
            answer = null;
            switch (op)
            {
                case "layout_kept":
                {
                    string locale = F(call, "locale") as string;
                    var text = new SurfaceText(new TableTextCalc(F(call, "measure") as List<object>, null, null), locale);
                    var vm = (Dictionary<string, object>)call["vm"];
                    answer = KeptPlan((string)call["surface"] == "card" ? CardPlan.Layout(vm, D(call, "scale"), text)
                                                                        : PopupLayout.Plan(vm, D(call, "scale"), locale, text));
                    return true;
                }
                case "renderer_open":
                {
                    // S6.4f3: with the C#'s own first look (theme, design, High Contrast, lone, sweep), which a test's
                    // renderer starts from as the Python's starts from its own.
                    SurfaceRenderer made = SurfaceRenderer.Open();
                    answer = new Dictionary<string, object> { { "renderer", Keep(made) }, { "theme", made.Theme }, { "design", made.Design },
                                                              { "contrast", made.Contrast }, { "lone", made.Lone },
                                                              { "sweep_ms", made.SweepMs.HasValue ? (object)made.SweepMs.Value : null } };
                    return true;
                }
                case "renderer_close":
                {
                    SurfaceRenderer renderer = Kept<SurfaceRenderer>(call, "renderer");
                    kept.Remove(I(call, "renderer"));
                    renderer.Dispose();
                    return true;
                }
                case "renderer_use":
                    Look(call).Use((string)call["locale"], D(call, "scale"));
                    return true;
                case "renderer_measure":
                    answer = SurfaceRender.Dump(Look(call).Text.Measure((string)call["role"], F(call, "text") as string, I(call, "width"),
                                                                         B(call, "wrap")));
                    return true;
                case "renderer_lines":
                    answer = Look(call).Text.Lines((string)call["role"], F(call, "text") as string, I(call, "width"));
                    return true;
                case "renderer_fonts":
                {
                    SurfaceFontSet fonts = Kept<SurfaceRenderer>(call, "renderer").Fonts;
                    if (fonts == null) return true;
                    var faces = new Dictionary<string, object>();
                    foreach (KeyValuePair<string, string> pair in fonts.Faces) faces[pair.Key] = pair.Value;
                    answer = new Dictionary<string, object> { { "locale", fonts.Locale }, { "scale", fonts.Scale }, { "faces", faces } };
                    return true;
                }
                case "renderer_layout":
                    answer = KeptPlan(Look(call).Layout((Dictionary<string, object>)call["vm"], D(call, "scale"), (string)call["locale"]));
                    return true;
                case "renderer_draw":
                {
                    SurfaceRenderer renderer = Look(call);
                    var glides = new Dictionary<object, double>();
                    foreach (object entry in (List<object>)call["glides"])
                    {
                        var pair = (List<object>)entry;
                        glides[SurfaceRender.TargetOf(pair[0])] = (double)pair[1];
                    }
                    var faces = new Dictionary<object, ButtonFace>();
                    foreach (object entry in (List<object>)call["faces"])
                    {
                        var four = (List<object>)entry;
                        faces[SurfaceRender.TargetOf(four[0])] = new ButtonFace(Ints(four[1]), Ints(four[2]), (double)four[3]);
                    }
                    SurfacePlan plan = Kept<SurfacePlan>(call, "plan");
                    // S6.4f3: drawn without its words when the test stood a no-op in for the renderer's _text.
                    if (call.ContainsKey("words") && !B(call, "words")) plan = Wordless(plan);
                    WithSpecks(F(call, "specks"), plan, () => renderer.Draw(plan, FrameOf(F(call, "frame")), SurfaceRender.TargetOf(F(call, "hover")),
                                                                         SurfaceRender.TargetOf(F(call, "pressed")), SurfaceRender.TargetOf(F(call, "focus")),
                                                                         glides, D(call, "scene_ms"), faces));
                    answer = Rows(renderer);
                    return true;
                }
                case "renderer_draw_halo":
                {
                    SurfaceRenderer renderer = Look(call);
                    renderer.DrawHalo(Kept<SurfacePlan>(call, "plan"), FrameOf(F(call, "frame")), B(call, "restore"));
                    answer = Rows(renderer);
                    return true;
                }
                case "renderer_draw_scene":
                {
                    SurfaceRenderer renderer = Look(call);
                    SurfacePlan plan = Kept<SurfacePlan>(call, "plan");
                    WithSpecks(F(call, "specks"), plan, () => renderer.DrawScene(plan, D(call, "ms")));
                    return true;
                }
                case "renderer_canvas":
                {
                    SurfaceCanvas canvas = Kept<SurfaceRenderer>(call, "renderer").Canvas;
                    answer = new List<object> { (double)canvas.Width, (double)canvas.Height };
                    return true;
                }
                case "renderer_halo_rows":
                    answer = Rows(Kept<SurfaceRenderer>(call, "renderer"));
                    return true;
                case "renderer_pixels":
                {
                    SurfaceRenderer renderer = Kept<SurfaceRenderer>(call, "renderer");
                    SurfaceNative.GdiFlush();
                    answer = Picture(renderer.Canvas.Pixels(), renderer.Canvas.Width, renderer.Canvas.Height);
                    return true;
                }
                case "renderer_face_colours":
                {
                    SurfacePlan plan = Kept<SurfacePlan>(call, "plan");
                    answer = SurfaceRender.Dump(Look(call).FaceColours(plan.Items[I(call, "index")], (string)call["state"]));
                    return true;
                }
                case "renderer_card_still":
                {
                    object pad = F(call, "pad");
                    object[] still = SurfaceLayers.CardStill(Look(call), Kept<SurfacePlan>(call, "plan"),
                                                             pad == null ? (int?)null : (int)(double)pad);
                    answer = Picture((byte[])still[2], (int)still[0], (int)still[1]);
                    return true;
                }
                case "icon_frames_new":
                {
                    var frames = new IconFrames(I(call, "size"), I(call, "fine"), F(call, "look") as string);
                    answer = new Dictionary<string, object> { { "frames", Keep(frames) }, { "ground", Levels(frames.Ground) },
                                                              { "count", (double)frames.Count },
                                                              { "budget", (double)TrayMotion.BuildBudgetMs } };
                    return true;
                }
                case "icon_frames_heads":
                {
                    // The head positions' boxes and samples are the C#'s own private table (IconFrames.heads), read as
                    // it is: a test reads them only to know where a head can draw.
                    var frames = Kept<IconFrames>(call, "frames");
                    var field = typeof(IconFrames).GetField("heads", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    var heads = (List<KeyValuePair<int[], int[][][]>>)field.GetValue(frames);
                    var listed = new List<object>();
                    foreach (KeyValuePair<int[], int[][][]> head in heads)
                        listed.Add(new List<object> { SurfaceRender.Dump(head.Key), SurfaceRender.Dump(head.Value) });
                    answer = listed;
                    return true;
                }
                case "icon_frames_mark":
                {
                    // The pixels a day's mark covers, the C#'s own private table (IconFrames.mark, y * size + x), as
                    // [x, y, hits, red, green, blue] each.
                    var frames = Kept<IconFrames>(call, "frames");
                    var field = typeof(IconFrames).GetField("mark", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    var listed = new List<object>();
                    foreach (KeyValuePair<int, int[]> pair in (Dictionary<int, int[]>)field.GetValue(frames))
                        listed.Add(new List<object> { (double)(pair.Key % frames.Size), (double)(pair.Key / frames.Size), (double)pair.Value[0],
                                                      (double)pair.Value[1], (double)pair.Value[2], (double)pair.Value[3] });
                    answer = listed;
                    return true;
                }
                case "icon_frames_compose":
                {
                    var frames = Kept<IconFrames>(call, "frames");
                    int[] head = Ints(call["head"]);
                    byte[] made = frames.Compose(I(call, "position"), head);
                    // Whether the C# answered from its store: the same array it answered last time for this key.
                    int count = frames.Count, at = ((I(call, "position") % count) + count) % count;
                    string key = I(call, "frames") + "|" + at + "," + head[0] + "," + head[1] + "," + head[2];
                    byte[] before;
                    bool kept = composed.TryGetValue(key, out before) && ReferenceEquals(before, made);
                    composed[key] = made;
                    answer = new Dictionary<string, object> { { "pixels", Levels(made) }, { "kept", kept } };
                    return true;
                }
                case "constant":
                {
                    // The host's own value of a constant a picture's plan is held to (the twins of
                    // tests/test_host_tray_story.py): the popup's one-shot glide frame and the hover card's gap.
                    string name = (string)call["name"];
                    if (name == "glide_frame_ms") answer = (double)PopupMotion.GlideFrameMs;
                    else if (name == "tip_gap") answer = (double)TipPlan.TipGap;
                    else throw new KeyNotFoundException(name);
                    return true;
                }
                case "message_face":
                    answer = SurfaceFonts.UiFace();
                    return true;
                case "font_faces":
                {
                    var faces = SurfaceFonts.FontFaces(F(call, "locale") as string, F(call, "system") as string, Lacks(call),
                                                       F(call, "letters") as string);
                    answer = new List<object>(faces.ConvertAll(face => (object)face));
                    return true;
                }
                case "font_candidates":
                {
                    var found = new List<object>();
                    foreach (KeyValuePair<string, int> pair in SurfaceFonts.FontCandidates(F(call, "locale") as string, I(call, "weight"),
                                                                                         F(call, "system") as string, Lacks(call),
                                                                                         F(call, "letters") as string))
                        found.Add(new List<object> { pair.Key, (double)pair.Value });
                    answer = found;
                    return true;
                }
                case "theme_choice":
                    answer = SurfaceTheme.ThemeChoice(F(call, "value"));
                    return true;
                case "effective_theme":
                    answer = SurfaceTheme.EffectiveTheme(F(call, "choice"), F(call, "light") as bool?);
                    return true;
                case "appearance":
                    answer = SurfaceTheme.Appearance(F(call, "choice"), F(call, "light") as bool?, B(call, "contrast"));
                    return true;
                case "design_choice":
                    answer = SurfaceTheme.DesignChoice(F(call, "value"));
                    return true;
                case "set_reduce_motion":
                    SurfaceTheme.SetReduceMotion(F(call, "value"));
                    return true;
                case "set_theme":
                    SurfaceTheme.SetTheme(F(call, "value"));
                    return true;
                case "set_design":
                    SurfaceTheme.SetDesign(F(call, "value"));
                    return true;
                case "theme_setting":
                    answer = SurfaceTheme.ThemeSetting;
                    return true;
                case "design_setting":
                    answer = SurfaceTheme.DesignSetting;
                    return true;
                case "adopt_settings":
                    SurfaceTheme.AdoptSettings(F(call, "values"));
                    return true;
                case "reduced_motion":
                    answer = SurfaceTheme.ReducedMotion();
                    return true;
                case "corner_coverage":
                {
                    var rows = new List<object>();
                    foreach (byte[] row in CardCorner.Coverage(D(call, "radius"), Maybe(F(call, "smoothing"))))
                    {
                        var levels = new List<object>(row.Length);
                        foreach (byte level in row) levels.Add((double)level);
                        rows.Add(levels);
                    }
                    answer = rows;
                    return true;
                }
            }
            return false;
        }

        // ------------------------------------------------------------- S6.4f3: what a test reads of a renderer's own state
        /// One handle per C# object: the same object asked twice answers the same handle, so the Python side can hand
        /// back the same Python object where the C# answered the same one (`is` holds exactly where it holds here).
        private sealed class SameObject : IEqualityComparer<object>
        {
            public new bool Equals(object one, object other) { return ReferenceEquals(one, other); }
            public int GetHashCode(object value) { return System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(value); }
        }

        private static readonly Dictionary<object, double> handles = new Dictionary<object, double>(new SameObject());

        private static double Same(object value)
        {
            double handle;
            if (!handles.TryGetValue(value, out handle)) handle = handles[value] = Keep(value);
            return handle;
        }

        private const System.Reflection.BindingFlags Private = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
        private const System.Reflection.BindingFlags PrivateStatic = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static;

        /// A private field of the C#'s own, read as it is (the renderer's kept images and ground key: a test reads them only
        /// to see what is kept, never to change it).
        private static object FieldOf(object owner, string name)
        {
            var field = owner.GetType().GetField(name, Private);
            if (field == null) throw new MissingFieldException(owner.GetType().Name, name);
            return field.GetValue(owner);
        }

        private static object Image(SurfaceShadowImage image)
        {
            return new Dictionary<string, object> { { "image", Same(image) }, { "width", (double)image.Width }, { "height", (double)image.Height } };
        }

        /// A plan a test built itself (a dict of its own, or one of the host's it changed after): the C#'s SurfacePlan of
        /// the same fields, its targets as SurfaceTarget, a rectangle of whole numbers as int[] (as the layouts make it).
        private static SurfacePlan PlanOf(Dictionary<string, object> map)
        {
            var plan = new SurfacePlan { Size = Ints(map["size"]), Scale = (double)map["scale"], Card = Ints(F(map, "card")) };
            foreach (object entry in (F(map, "items") as List<object>) ?? new List<object>())
            {
                var item = new PlanItem();
                foreach (KeyValuePair<string, object> pair in (Dictionary<string, object>)entry)
                    item[pair.Key] = pair.Key == "target" ? SurfaceRender.TargetOf(pair.Value)
                                   : pair.Key == "rect" && Whole(pair.Value) ? (object)Ints(pair.Value) : pair.Value;
                plan.Items.Add(item);
            }
            plan.Targets = TargetPairs(F(map, "targets")) ?? new List<KeyValuePair<object, int[]>>();
            plan.Rows = TargetPairs(F(map, "rows"));
            object rtl = F(map, "rtl");
            plan.Rtl = map.ContainsKey("rtl") ? SurfaceMath.Truthy(rtl) : (bool?)null;
            return plan;
        }

        private static bool Whole(object value)
        {
            var list = value as List<object>;
            if (list == null) return false;
            foreach (object each in list) if (!(each is double) || (double)each != Math.Floor((double)each)) return false;
            return true;
        }

        private static List<KeyValuePair<object, int[]>> TargetPairs(object value)
        {
            return value == null ? null : Targets(value);
        }

        /// The plan a renderer call names: the kept one by its handle.
        private static SurfacePlan PlanNamed(Dictionary<string, object> call)
        {
            return Kept<SurfacePlan>(call, "plan");
        }

        /// The plan drawn without its words (a test that stands a no-op in for the renderer's _text): the same plan less its
        /// lines of text, which only the words and the card-alone seal read.
        private static SurfacePlan Wordless(SurfacePlan plan)
        {
            SurfacePlan copy = plan.Copy();
            copy.Items = copy.Items.FindAll(item => item.Kind != "text");
            return copy;
        }

        /// `draw` with the day's specks as a test stood them in for brand.speck_frame: "none" (a speck_frame that answers
        /// nothing) empties the looks' specks, "unculled" (one that answers every speck whatever band is asked) makes every
        /// speck reach every band; null draws as the product does. SurfaceDays' own tables, put back after.
        private static T WithSpecks<T>(object mode, SurfacePlan plan, Func<T> draw)
        {
            if (mode == null) return draw();
            var specks = (Dictionary<string, List<DayElement>>)typeof(SurfaceDays).GetField("Specks", PrivateStatic).GetValue(null);
            var reaches = (Dictionary<string, List<double[]>>)typeof(SurfaceDays).GetField("Reaches", PrivateStatic).GetValue(null);
            var saved = new List<object[]>();
            foreach (PlanItem item in plan.Items)
            {
                if (item.Kind != "scene") continue;
                string look = (string)item["scene"];
                List<DayElement> elements = SurfaceDays.SpeckElements(look);
                List<double[]> reach = SurfaceDays.SpeckReach(look);
                saved.Add(new object[] { look, elements, reach });
                if ((string)mode == "none")
                {
                    specks[look] = new List<DayElement>();
                    reaches[look] = new List<double[]>();
                }
                else if ((string)mode == "unculled")
                {
                    var every = new List<double[]>();
                    foreach (DayElement element in elements) every.Add(new[] { double.NegativeInfinity, double.PositiveInfinity });
                    reaches[look] = every;
                }
                else if ((string)mode == "scenegone")
                {
                    // for the mutation checks only: a look whose scene the host cannot draw
                    var scenes = (Dictionary<string, List<DayElement>>)typeof(SurfaceDays).GetField("Scenes", PrivateStatic).GetValue(null);
                    scenes[look] = null;
                }
                else throw new ArgumentException("no speck mode " + mode);
            }
            try { return draw(); }
            finally
            {
                var scenes = (Dictionary<string, List<DayElement>>)typeof(SurfaceDays).GetField("Scenes", PrivateStatic).GetValue(null);
                foreach (object[] kept in saved)
                {
                    specks[(string)kept[0]] = (List<DayElement>)kept[1];
                    reaches[(string)kept[0]] = (List<double[]>)kept[2];
                    if ((string)mode == "scenegone") scenes.Remove((string)kept[0]);
                }
            }
        }

        private static List<object> FloatsList(List<FloatShadow> shadows) { return FloatList(shadows); }

        /// S6.4f3's questions: the GDI+ count, a renderer's kept images and ground key, a plan of the test's own, the
        /// shadow window's layers, the icon's card renderer and its place. False when `op` is none of them.
        private static bool Further(string op, Dictionary<string, object> call, out object answer)
        {
            answer = null;
            switch (op)
            {
                case "gdiplus_objects":
                    answer = (double)SurfaceGdip.GdipObjects;
                    return true;
                case "renderer_images":
                {
                    var images = (Dictionary<string, SurfaceShadowImage>)FieldOf(Kept<SurfaceRenderer>(call, "renderer"), "images");
                    var listed = new List<object>();
                    foreach (KeyValuePair<string, SurfaceShadowImage> pair in images)
                    {
                        var one = (Dictionary<string, object>)Image(pair.Value);
                        one["key"] = pair.Key;
                        listed.Add(one);
                    }
                    answer = listed;
                    return true;
                }
                case "renderer_image":
                {
                    var mask = (Dictionary<string, object>)call["mask"];
                    var levels = (List<object>)mask["coverage"];
                    var coverage = new byte[levels.Count];
                    for (int i = 0; i < coverage.Length; i++) coverage[i] = (byte)(double)levels[i];
                    var made = new ShadowMask { Key = (string)mask["key"], Width = (int)(double)mask["width"], Height = (int)(double)mask["height"],
                                                Extent = (int)(double)mask["extent"], Centre = Ints(mask["centre"]), Coverage = coverage };
                    var six = (List<object>)call["shadow"];
                    var shadow = new SurfaceShadow { Dx = (double)six[0], Dy = (double)six[1], Blur = (double)six[2], Token = (string)six[3],
                                                     Alpha = (double)six[4], Inset = Equals(six[5], true) };
                    SurfaceRenderer renderer = Look(call);
                    var method = typeof(SurfaceRenderer).GetMethod("Image", Private);
                    answer = Image((SurfaceShadowImage)method.Invoke(renderer, new object[] { made, shadow }));
                    return true;
                }
                case "image_pixels":
                {
                    var image = Kept<SurfaceShadowImage>(call, "image");
                    answer = Picture((byte[])FieldOf(image, "pixels"), image.Width, image.Height);
                    return true;
                }
                case "renderer_ground_key":
                    answer = FieldOf(Kept<SurfaceRenderer>(call, "renderer"), "groundKey");
                    return true;
                case "plan_from_dict":
                    answer = Keep(PlanOf((Dictionary<string, object>)call["plan"]));
                    return true;
                case "layers_open":
                    answer = Keep(new CardLayers(IntPtr.Zero));
                    return true;
                case "layers_shade":
                {
                    var layers = Kept<CardLayers>(call, "layers");
                    bool changed = layers.Shade(Look(call), PlanNamed(call));
                    answer = new Dictionary<string, object> { { "changed", changed }, { "margin", (double)layers.Margin },
                                                              { "shadows", FloatsList(layers.Shadows) } };
                    return true;
                }
                case "layers_canvas":
                {
                    var layers = Kept<CardLayers>(call, "layers");
                    answer = new List<object> { (double)layers.Picture.Width, (double)layers.Picture.Height };
                    return true;
                }
                case "layers_pixels":
                {
                    var layers = Kept<CardLayers>(call, "layers");
                    SurfaceNative.GdiFlush();
                    answer = Picture(layers.Picture.Pixels(), layers.Picture.Width, layers.Picture.Height);
                    return true;
                }
                case "layers_images":
                    answer = (double)Kept<CardLayers>(call, "layers").Images.Count;
                    return true;
                case "layers_drop_images":
                {
                    // CardLayers' own way to let its images go is its Dispose (close); the Python's _drop_images is the
                    // same loop over the same table, without the window.
                    var layers = Kept<CardLayers>(call, "layers");
                    foreach (SurfaceShadowImage image in layers.Images.Values) image.Dispose();
                    layers.Images.Clear();
                    return true;
                }
                case "layers_close":
                {
                    var layers = Kept<CardLayers>(call, "layers");
                    kept.Remove(I(call, "layers"));
                    layers.Dispose();
                    return true;
                }
                case "renderer_tip_layout":
                    answer = KeptPlan(Look(call).TipLayout((Dictionary<string, object>)call["parts"], F(call, "light"), D(call, "scale"),
                                                           (string)call["locale"], F(call, "day") as string));
                    return true;
                case "renderer_metrics":
                    answer = SurfaceRender.Dump(Look(call).Text.Calc.Metrics((string)call["role"]));
                    return true;
                case "renderer_ink":
                    answer = SurfaceRender.Dump(Look(call).Text.Calc.Ink((string)call["role"], F(call, "text") as string));
                    return true;
                case "renderer_draw_tip":
                {
                    SurfaceRenderer renderer = Look(call);
                    SurfacePlan plan = PlanNamed(call);
                    WithSpecks(F(call, "specks"), plan, () => renderer.DrawTip(plan, FrameOf(F(call, "frame"))));
                    answer = Rows(renderer);
                    return true;
                }
                case "renderer_draw_tip_light":
                {
                    SurfaceRenderer renderer = Look(call);
                    renderer.DrawTipLight(PlanNamed(call), FrameOf(F(call, "frame")), B(call, "restore"));
                    answer = Rows(renderer);
                    return true;
                }
                case "tip_day":
                    answer = SurfaceRenderer.TipDay(F(call, "look") as string, B(call, "contrast"), F(call, "design") as string);
                    return true;
                case "tip_place":
                    answer = SurfaceRender.Dump(TipCard.TipPlace(PlanNamed(call), Ints(call["work"]), Ints(call["monitor"]), Ints(F(call, "box"))));
                    return true;
            }
            return false;
        }

        private static object Answer(string op, Dictionary<string, object> call)
        {
            object drawn;
            if (Further(op, call, out drawn)) return drawn;
            if (Drawn(op, call, out drawn)) return drawn;
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
            if (op == "premultiply")
            {
                var bytes = new List<byte>();
                foreach (object level in (List<object>)call["pixels"]) bytes.Add((byte)(double)level);
                byte[] made = CardCorner.Premultiply(bytes.ToArray(), I(call, "width"), I(call, "height"), D(call, "radius"), I(call, "top"),
                                                     Maybe(F(call, "smoothing")));
                var listed = new List<object>(made.Length);
                foreach (byte level in made) listed.Add((double)level);
                return listed;
            }
            // ------------------------------------------------------------- the type and the colours (SurfaceFonts, SurfaceTheme)
            if (op == "role_size") return (double)SurfaceFonts.RoleSize((string)call["role"], (string)call["locale"]);
            if (op == "contrast_colour") return SurfaceTheme.ContrastColour((string)call["token"]);
            throw new NotSupportedException("no op " + op);
        }
    }
}

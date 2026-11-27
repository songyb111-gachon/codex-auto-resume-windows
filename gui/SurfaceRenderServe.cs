// Codex Auto Resume - the render mode as a picture maker: the surfaces' own drawing calls, asked one at a time, and
// every picture written as premultiplied BGRA (v0.6.27, S6.3f; P6-DESIGN 3.2, comparisons B and C).
//
// A job with "serve": true is not a list of cases: the render mode reads one call per line (JSON) from its standard
// input and answers each on its standard output, one line each, until the input ends. The calls are the ones the
// reference's picture makers make of its renderers - build/make_screenshots.py's surface functions and
// build/motion_{popup,tip,card}.py, retargeted through build/surface_render.py - on objects this side keeps:
//
//   open_renderer {theme, design, contrast, lone, letters}           -> {"renderer": h}       (popup.Renderer / TipRenderer)
//   (every call on a renderer may name theme, design, contrast, lone and letters again: the look it is drawn in)
//   layout {renderer, vm, scale, locale}                              -> {"plan": h, "dump"}  (Renderer.layout)
//   tip_layout {renderer, parts, light, scale, locale, day}           -> {"plan": h, "dump"}  (TipRenderer.tip_layout)
//   draw {renderer, plan, frame, hover, pressed, focus, glides, scene_ms, faces}             (Renderer.draw)
//   draw_halo / draw_tip / draw_tip_light {renderer, plan, frame}     -> {"rows"}
//   face_colours {renderer, plan, index, state}                       -> [fill, edge]         (Renderer.face_colours)
//   pixels {renderer}                                                 -> a picture             (canvas.pixels())
//   card_still {renderer, plan, pad}                                  -> a picture             (layers.card_still)
//   open_card {vm, title, stays, hold, now, dpi, work, drawn, letters} -> {"card": h, ...}    (Card(..., windows=False))
//   card_motion {card, born, hold, place, leave}                      (CardMotion(born, hold), move_to, retire; born)
//   card_set {card, hover, pressed, breathed, edge} / card_redraw / card_light {card, ms} / card_paint {card, ms}
//   card_layers {card}                                                -> {"body", "shadow"} pictures
//   close {handle}; objects                                           -> GDI+ objects alive
//
// A picture is written to the job's "frames" folder as raw premultiplied BGRA, top row first, and answered as
// {"file", "bytes", "digest", "width", "height"}. The job's "pinned" names the UI face (make_screenshots.pinned_face).
// Nothing here shows, posts or starts anything; no window is made.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace CodexAutoResume
{
    internal static partial class SurfaceRender
    {
        /// Serves `job`'s calls from `input` to `output` until the input ends; the number of calls answered.
        internal static int Serve(Dictionary<string, object> job, TextReader input, TextWriter output)
        {
            string folder = (string)job["frames"];
            Directory.CreateDirectory(folder);
            SurfaceFonts.Pinned = Field(job, "pinned") as string;
            var session = new ServeSession(folder);
            int served = 0;
            try
            {
                string line;
                while ((line = input.ReadLine()) != null)
                {
                    if (line.Trim().Length == 0) continue;
                    var answer = new Dictionary<string, object>();
                    try
                    {
                        var call = (Dictionary<string, object>)Json.Parse(line);
                        answer["id"] = Field(call, "id");
                        answer["ok"] = Dump(session.Call((string)call["call"], Field(call, "args") as Dictionary<string, object>
                                                                               ?? new Dictionary<string, object>()));
                    }
                    catch (Exception exc)
                    {
                        answer["error"] = exc.GetType().Name + ": " + exc.Message;
                    }
                    output.WriteLine(Json.Write(answer));
                    output.Flush();
                    served += 1;
                }
            }
            finally
            {
                session.Dispose();
                SurfaceFonts.Pinned = null;
            }
            return served;
        }

        private sealed class ServeSession : IDisposable
        {
            private readonly string folder;
            private readonly Dictionary<int, object> objects = new Dictionary<int, object>();
            private int next = 1, written;

            internal ServeSession(string folder) { this.folder = folder; }

            private int Keep(object value)
            {
                int handle = next++;
                objects[handle] = value;
                return handle;
            }

            private T Get<T>(Dictionary<string, object> args, string key) where T : class
            {
                object value;
                if (!objects.TryGetValue((int)(double)args[key], out value) || !(value is T))
                    throw new KeyError(key + " is no " + typeof(T).Name);
                return (T)value;
            }

            private Dictionary<string, object> Picture(byte[] bgra, int? width = null, int? height = null)
            {
                string path = Path.Combine(folder, (written++).ToString("D6") + ".bgra");
                File.WriteAllBytes(path, bgra);
                return new Dictionary<string, object>
                {
                    { "file", path }, { "bytes", bgra.Length }, { "digest", Digest(bgra) },
                    { "width", width.HasValue ? (object)width.Value : null }, { "height", height.HasValue ? (object)height.Value : null },
                };
            }

            /// The renderer's look as the caller's renderer has it when it calls (theme, design, contrast, lone, letters are
            /// attributes the reference's picture makers set on their renderer): each one the call names.
            private SurfaceRenderer Look(Dictionary<string, object> args)
            {
                SurfaceRenderer renderer = Get<SurfaceRenderer>(args, "renderer");
                if (args.ContainsKey("theme")) renderer.Theme = (string)args["theme"];
                if (args.ContainsKey("design")) renderer.Design = (string)args["design"];
                if (args.ContainsKey("contrast")) renderer.Contrast = SurfaceMath.Truthy(args["contrast"]);
                if (args.ContainsKey("lone")) renderer.Lone = SurfaceMath.Truthy(args["lone"]);
                if (args.ContainsKey("letters")) renderer.Letters = args["letters"] as string;
                return renderer;
            }

            private static Dictionary<object, double> Glides(object value)
            {
                var glides = new Dictionary<object, double>();
                foreach (object entry in (value as List<object>) ?? new List<object>())
                {
                    var pair = (List<object>)entry;
                    glides[TargetOf(pair[0])] = (double)pair[1];
                }
                return glides;
            }

            private static Dictionary<object, ButtonFace> Faces(object value)
            {
                var faces = new Dictionary<object, ButtonFace>();
                foreach (object entry in (value as List<object>) ?? new List<object>())
                {
                    var four = (List<object>)entry;
                    faces[TargetOf(four[0])] = new ButtonFace(Ints(four[1]), Ints(four[2]), (double)four[3]);
                }
                return faces;
            }

            internal object Call(string name, Dictionary<string, object> args)
            {
                if (name == "open_renderer")
                {
                    SurfaceRenderer renderer = SurfaceRenderer.Open();
                    renderer.Theme = (string)args["theme"];
                    renderer.Design = (string)args["design"];
                    renderer.Contrast = SurfaceMath.Truthy(Field(args, "contrast"));
                    renderer.Lone = SurfaceMath.Truthy(Field(args, "lone"));
                    renderer.Letters = Field(args, "letters") as string;
                    return new Dictionary<string, object> { { "renderer", Keep(renderer) } };
                }
                if (name == "layout")
                {
                    SurfacePlan plan = Look(args).Layout((Dictionary<string, object>)args["vm"],
                                                                                     (double)args["scale"], (string)args["locale"]);
                    return new Dictionary<string, object> { { "plan", Keep(plan) }, { "dump", plan } };
                }
                if (name == "tip_layout")
                {
                    SurfaceRenderer renderer = Look(args);
                    SurfacePlan plan = renderer.TipLayout((Dictionary<string, object>)args["parts"], Field(args, "light"),
                                                          (double)args["scale"], (string)args["locale"], Field(args, "day") as string);
                    return new Dictionary<string, object> { { "plan", Keep(plan) }, { "dump", plan } };
                }
                if (name == "draw")
                {
                    SurfaceRenderer renderer = Look(args);
                    object scene = Field(args, "scene_ms");
                    renderer.Draw(Get<SurfacePlan>(args, "plan"), FrameFrom(Field(args, "frame")), TargetOf(Field(args, "hover")),
                                  TargetOf(Field(args, "pressed")), TargetOf(Field(args, "focus")), Glides(Field(args, "glides")),
                                  scene == null ? 0.0 : (double)scene, Faces(Field(args, "faces")));
                    return null;
                }
                if (name == "draw_halo" || name == "draw_tip" || name == "draw_tip_light")
                {
                    SurfaceRenderer renderer = Look(args);
                    SurfacePlan plan = Get<SurfacePlan>(args, "plan");
                    LightFrame frame = FrameFrom(Field(args, "frame"));
                    if (name == "draw_halo") renderer.DrawHalo(plan, frame);
                    else if (name == "draw_tip") renderer.DrawTip(plan, frame);
                    else renderer.DrawTipLight(plan, frame);
                    return new Dictionary<string, object> { { "rows", renderer.HaloRows } };
                }
                if (name == "face_colours")
                {
                    SurfacePlan plan = Get<SurfacePlan>(args, "plan");
                    return Look(args).FaceColours(plan.Items[(int)(double)args["index"]], (string)args["state"]);
                }
                if (name == "pixels")
                {
                    SurfaceRenderer renderer = Get<SurfaceRenderer>(args, "renderer");
                    SurfaceNative.GdiFlush();
                    return Picture(renderer.Canvas.Pixels());
                }
                if (name == "card_still")
                {
                    object pad = Field(args, "pad");
                    object[] still = SurfaceLayers.CardStill(Look(args), Get<SurfacePlan>(args, "plan"),
                                                             pad == null ? (int?)null : (int)(double)pad);
                    return Picture((byte[])still[2], (int)still[0], (int)still[1]);
                }
                if (name == "open_card")
                {
                    var card = new NoticeCard(null, (Dictionary<string, object>)args["vm"], PopupWords.Str(Field(args, "title")),
                                              Equals(Field(args, "stays"), true), (double)args["hold"], (double)args["now"],
                                              (double)args["dpi"], Ints(args["work"]), (Dictionary<string, object>)args["drawn"], false,
                                              Field(args, "letters") as string);
                    return new Dictionary<string, object>
                    {
                        { "card", Keep(card) }, { "size", card.Size }, { "margin", card.Margin }, { "plan", card.Plan },
                        { "vm", card.Vm },
                    };
                }
                if (name == "card_motion")
                {
                    NoticeCard card = Get<NoticeCard>(args, "card");
                    double born = (double)args["born"];
                    var motion = new CardMotion(born, (double)args["hold"]);
                    motion.MoveTo(born, Ints(args["place"]));
                    object leave = Field(args, "leave");
                    if (leave != null) motion.Retire((double)leave);
                    card.Motion = motion;
                    card.Born = born;
                    return null;
                }
                if (name == "card_set")
                {
                    NoticeCard card = Get<NoticeCard>(args, "card");
                    if (args.ContainsKey("hover")) card.Hover = TargetOf(args["hover"]);
                    if (args.ContainsKey("pressed")) card.Pressed = TargetOf(args["pressed"]);
                    if (args.ContainsKey("breathed")) card.Breathed = (double)args["breathed"];
                    if (args.ContainsKey("edge")) card.Edge = (string)args["edge"];
                    return null;
                }
                if (name == "card_redraw")
                {
                    Get<NoticeCard>(args, "card").Redraw();
                    return null;
                }
                if (name == "card_light")
                {
                    NoticeCard card = Get<NoticeCard>(args, "card");
                    card.DrawLight((double)args["ms"]);
                    int[] rows = card.Renderer.HaloRows;
                    int row = card.Size[0] * 4;
                    var band = new byte[(rows[1] - rows[0]) * row];
                    Array.Copy(card.Image.Pixels, rows[0] * row, band, 0, band.Length);
                    return new Dictionary<string, object> { { "rows", rows }, { "band", Picture(band, card.Size[0], rows[1] - rows[0]) } };
                }
                if (name == "card_paint")
                {
                    NoticeCard card = Get<NoticeCard>(args, "card");
                    Dictionary<string, object> painted = card.Paint((double)args["ms"]);
                    return new Dictionary<string, object>
                    {
                        { "frame", FrameOf((CardFrame)painted["frame"]) }, { "x", painted["x"] }, { "y", painted["y"] },
                        { "margin", painted["margin"] }, { "key", painted["key"] }, { "gone", card.Motion.Gone },
                    };
                }
                if (name == "card_layers")
                {
                    NoticeCard card = Get<NoticeCard>(args, "card");
                    SurfaceNative.GdiFlush();
                    return new Dictionary<string, object>
                    {
                        { "body", Picture(card.Body.Pixels(), card.Body.Width, card.Body.Height) },
                        { "shadow", Picture(card.Shadow.Pixels(), card.Shadow.Width, card.Shadow.Height) },
                    };
                }
                if (name == "close")
                {
                    int handle = (int)(double)args["handle"];
                    object value;
                    if (objects.TryGetValue(handle, out value))
                    {
                        objects.Remove(handle);
                        var disposable = value as IDisposable;
                        if (disposable != null) disposable.Dispose();
                    }
                    return null;
                }
                if (name == "objects") return SurfaceGdip.GdipObjects;
                throw new NotSupportedException(name);
            }

            public void Dispose()
            {
                foreach (object value in objects.Values)
                {
                    var disposable = value as IDisposable;
                    if (disposable != null) disposable.Dispose();
                }
                objects.Clear();
            }
        }

        /// A handle that names nothing of the kind asked for.
        private sealed class KeyError : Exception
        {
            internal KeyError(string message) : base(message) { }
        }
    }
}

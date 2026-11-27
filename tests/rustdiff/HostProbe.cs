// The test-side entry of the C# host's surfaces (S6.4): compiled with gui/host.sources' [contract], [surface] and [generated]
// files by tests/rustdiff/surfacehost.py, never part of the product. Where CODEX_AR_HOST_CALL names a call, it answers the
// call's one question of the surfaces' own code and writes the answer to CODEX_AR_HOST_OUT; with none it is the render mode
// (SurfaceRender.Run), as build/surface_render.py's driver is. It makes no window and loads no DLL.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace CodexAutoResume
{
    internal static class HostProbeDriver
    {
        private static int Main(string[] args)
        {
            if (Environment.GetEnvironmentVariable("CODEX_AR_HOST_SERVE") == "1") return Serve();
            string callFile = Environment.GetEnvironmentVariable("CODEX_AR_HOST_CALL");
            if (string.IsNullOrEmpty(callFile)) return SurfaceRender.Run() ?? 2;
            string answer;
            try
            {
                var call = (Dictionary<string, object>)Json.Parse(File.ReadAllText(callFile, Encoding.UTF8));
                answer = Json.Write(new Dictionary<string, object> { { "ok", Answer((string)call["call"], call) } });
            }
            catch (Exception exc)
            {
                answer = Json.Write(new Dictionary<string, object> { { "error", exc.GetType().Name + ": " + exc.Message } });
            }
            File.WriteAllText(Environment.GetEnvironmentVariable("CODEX_AR_HOST_OUT"), answer, new UTF8Encoding(false));
            return 0;
        }

        /// One call per line on standard input, one answer per line on standard output, until the input ends: the same
        /// questions, asked of one process (a test asks hundreds).
        private static int Serve()
        {
            var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
            var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { NewLine = "\n", AutoFlush = true };
            string line;
            while ((line = input.ReadLine()) != null)
            {
                string answer;
                try
                {
                    var call = (Dictionary<string, object>)Json.Parse(line);
                    answer = Json.Write(new Dictionary<string, object> { { "ok", Answer((string)call["call"], call) } });
                }
                catch (Exception exc)
                {
                    answer = Json.Write(new Dictionary<string, object> { { "error", exc.GetType().Name + ": " + exc.Message } });
                }
                output.WriteLine(answer);
            }
            return 0;
        }

        /// The render mode's `tray_words` case (gui/SurfaceRenderWindows.cs TrayWordsCase), asked of TrayWords alone: the icon's
        /// words from a snapshot, and what a failed cast says.
        private static object TrayWords_(Dictionary<string, object> call)
        {
            var snapshot = SurfaceRender.Field(call, "snapshot") as Dictionary<string, object>;
            var strings = (Dictionary<string, object>)call["strings"];
            double now = (double)call["now"];
            string edition = SurfaceRender.Field(call, "edition") as string;
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

        /// A value as Json.Write takes it: numbers as doubles, whatever their C# type.
        private static object Plain(object value)
        {
            if (value is int || value is long || value is uint || value is short || value is byte) return Convert.ToDouble(value);
            var map = value as Dictionary<string, object>;
            if (map != null)
            {
                var copy = new Dictionary<string, object>();
                foreach (KeyValuePair<string, object> pair in map) copy[pair.Key] = Plain(pair.Value);
                return copy;
            }
            var list = value as List<object>;
            if (list != null) return list.ConvertAll(Plain);
            return value;
        }

        /// One question by its name. An if-chain, not a string switch: a switch of six or more strings compiles to a hash
        /// table the build cannot make the same twice (S6.3d takes them out of the host; the probe is kept the same way).
        private static object Answer(string name, Dictionary<string, object> call)
        {
            if (name == "tray_words") return TrayWords_(call);
            if (name == "icon_state")
                // tray.icon_state: a failure reported is "failed"; else the popup's word for the snapshot, as the icon's state
                return call["failed"] is bool && (bool)call["failed"] ? "failed"
                    : TrayMotion.ForLight(TipCard.SnapshotActivity(SurfaceRender.Field(call, "snapshot") as Dictionary<string, object>,
                                                                    (double)call["now"], call["attention"] is bool && (bool)call["attention"]));
            if (name == "menu_items")
                return Plain(TrayIcon.MenuItems(SurfaceRender.Field(call, "snapshot") as Dictionary<string, object>,
                                                SurfaceRender.Field(call, "strings") as Dictionary<string, object>,
                                                (double)call["now"], call["pending"] is bool && (bool)call["pending"],
                                                call["armed"] as string, call["popup"] is bool && (bool)call["popup"]));
            if (name == "tray_joined") return TrayWords.Joined(PartsOf((Dictionary<string, object>)call["parts"]));
            if (name == "placement") return Placement(call);
            if (name == "overflow")
                return TrayPlace.OverflowOpen(new FakeWindows
                {
                    Windows = (List<object>)call["windows"], Fail = call["fail"] is bool && (bool)call["fail"],
                });
            if (name == "card_layers") return CardLayers(call);
            throw new ArgumentException("no call " + name);
        }

        /// A notification card made with no window (NoticeCard's `windows: false`, as the render mode's `cards` case makes
        /// it), its layers settled - the body at full size, the shadow at the deepest level, through PaintLayers - and
        /// dumped: the body's and the shadow's BGRA pixels, base64. `whole` is the shadow of a second card whose image says
        /// nothing is wholly opaque, so CutUnderBody finds no pixel to clear: the shadow as it is stamped, before the cut
        /// (tests/test_card_shadow_under_body.py's `cut=False`). The stamp reads only the card's size and corner, never the
        /// image, so nothing else of it differs.
        private static object CardLayers(Dictionary<string, object> call)
        {
            var work = new List<int>();
            foreach (object each in (List<object>)call["work"]) work.Add((int)(double)each);
            var answer = new Dictionary<string, object>();
            for (int pass = 0; pass < 2; pass++)
            {
                using (var card = new NoticeCard(null, (Dictionary<string, object>)call["vm"], (string)call["title"],
                                                 call["stays"] is bool && (bool)call["stays"], (double)call["hold"], 0,
                                                 (double)call["dpi"], work.ToArray(), (Dictionary<string, object>)call["drawn"], false,
                                                 SurfaceRender.Field(call, "letters") as string))
                {
                    if (pass == 1)
                    {
                        byte[] pixels = card.Image.Pixels;
                        for (int at = 3; at < pixels.Length; at += 4)
                            if (pixels[at] == 0xFF) pixels[at] = 0xFE;
                    }
                    card.PaintLayers(CardFrame.Settled);
                    if (pass == 1)
                    {
                        answer["whole"] = Convert.ToBase64String(card.Shadow.Pixels());
                        continue;
                    }
                    answer["size"] = new List<object> { (double)card.Size[0], (double)card.Size[1] };
                    answer["margin"] = (double)card.Margin;
                    answer["shadows"] = (double)card.Shadows.Count;
                    answer["body"] = Convert.ToBase64String(card.Body.Pixels());
                    answer["cut"] = Convert.ToBase64String(card.Shadow.Pixels());
                    answer["shadow_size"] = new List<object> { (double)card.Shadow.Width, (double)card.Shadow.Height };
                }
            }
            return answer;
        }

        /// HKEY_CURRENT_USER as IconPlacement reads it, as tests/test_tray_icon_motion.py's FakeRegistry is: {key path: {value
        /// name: value}}, what was read, and a failure on request ("subkeys" or "value").
        private sealed class FakeKeys : ICurrentUserKeys
        {
            internal Dictionary<string, object> Keys = new Dictionary<string, object>();
            internal string Fail;
            internal readonly List<object> Reads = new List<object>();

            public List<string> Subkeys(string path)
            {
                Reads.Add(new List<object> { "subkeys", path });
                if (Fail == "subkeys") throw new IOException("no such key");
                bool found = Keys.ContainsKey(path);
                var names = new List<string>();
                foreach (string key in Keys.Keys)
                {
                    if (!key.StartsWith(path + "\\", StringComparison.Ordinal)) continue;
                    found = true;
                    string rest = key.Substring(path.Length + 1);
                    if (rest.IndexOf((char)92) < 0) names.Add(rest);
                }
                if (!found) throw new FileNotFoundException(path);
                names.Sort(StringComparer.Ordinal);
                return names;
            }

            public object Value(string path, string name)
            {
                Reads.Add(new List<object> { "value", path, name });
                if (Fail == "value") throw new IOException("cannot read");
                object key;
                if (!Keys.TryGetValue(path, out key)) return null;
                object value;
                return ((Dictionary<string, object>)key).TryGetValue(name, out value) ? value : null;
            }
        }

        /// user32 and dwmapi as OverflowOpen asks them (tests/test_tray_overflow_open.py's FakeWindows): [class, visible,
        /// cloaked] per window in z-order; a failing FindWindowEx on request.
        private sealed class FakeWindows : IOverflowWindows
        {
            internal List<object> Windows;
            internal bool Fail;

            public IntPtr FindWindowEx(IntPtr after, string className)
            {
                if (Fail) throw new IOException("FindWindowExW");
                int start = after == IntPtr.Zero ? 0 : (int)after - 100 + 1;
                for (int index = start; index < Windows.Count; index++)
                    if ((string)((List<object>)Windows[index])[0] == className) return new IntPtr(100 + index);
                return IntPtr.Zero;
            }

            public bool IsWindowVisible(IntPtr hwnd) { return (bool)((List<object>)Windows[(int)hwnd - 100])[1]; }

            public int Cloaked(IntPtr hwnd, out uint value)
            {
                value = (bool)((List<object>)Windows[(int)hwnd - 100])[2] ? 1u : 0u;
                return 0;
            }
        }

        /// IconPlacement over a run of steps: each sets the clock and the registry, asks `Overflowed` and reports its answer
        /// and every read it made, in order.
        private static object Placement(Dictionary<string, object> call)
        {
            var keys = new FakeKeys { Fail = call["fail"] as string };
            double now = 0;
            var folders = (Dictionary<string, object>)call["folders"];
            var placement = new IconPlacement((string)call["executable"], (int)(double)call["uid"], keys,
                                              guid => folders.ContainsKey(guid) ? folders[guid] as string : null, () => now);
            var answers = new List<object>();
            foreach (object each in (List<object>)call["steps"])
            {
                var step = (Dictionary<string, object>)each;
                now = (double)step["clock"];
                keys.Keys = (Dictionary<string, object>)step["keys"];
                keys.Reads.Clear();
                answers.Add(new Dictionary<string, object> { { "answer", placement.Overflowed() }, { "reads", new List<object>(keys.Reads) } });
            }
            return answers;
        }

        /// The icon card's parts as the reference's dictionary holds them: title, edition, (text, counts) pieces, meter rows.
        private static TrayWords.Parts PartsOf(Dictionary<string, object> json)
        {
            var parts = new TrayWords.Parts { Title = (string)json["title"], Edition = json["edition"] as string };
            foreach (object each in (List<object>)json["line"])
            {
                var piece = (List<object>)each;
                parts.Line.Add(new TrayWords.Piece { Text = (string)piece[0], Counts = piece[1] is bool && (bool)piece[1] });
            }
            foreach (object each in (List<object>)json["meter"]) parts.Meter.Add((Dictionary<string, object>)each);
            return parts;
        }
    }
}

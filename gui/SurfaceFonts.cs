// Codex Auto Resume - which face each script is drawn in, and how a line of it is measured (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/fonts.py (the roles, the faces per script, the Windows face per
// language, the GDI fonts), of the part of win/typeface.py those read (Windows' UI font, which glyphs a face has, and
// whether a face is installed), and of the popup renderer's measuring (Renderer.lines and Renderer.measure,
// ui/popup/renderer.py) with the tip's two font questions (TipRenderer.metrics and TipRenderer.ink, ui/tray/tipcard.py).
//
// Every measure comes down to one call, DrawTextW with DT_CALCRECT on a DC holding a role's font, and the tip's two to
// GetTextMetricsW and GetGlyphOutlineW. ITextCalc is that seam: GdiTextCalc asks GDI, as the Python does; TableTextCalc
// answers from a table a render job carries (P6-DESIGN 3.3, comparison A), so a plan is laid out exactly without the
// machine's fonts. The Korean line breaking above the call is the same code for both.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;

namespace CodexAutoResume
{
    /// The few questions a layout asks of a font, each answered for one popup font role.
    internal interface ITextCalc
    {
        /// DrawTextW(dc, text, -1, (0, 0, width, 0), flags) with DT_CALCRECT: the rectangle's (width, height).
        int[] Calc(string role, string text, int width, uint flags);

        /// (ascent, x-height) of the role's font in device pixels (TipRenderer.metrics).
        double[] Metrics(string role);

        /// (first, last): the text's first letter's left side bearing and its last letter's right one (TipRenderer.ink).
        int[] Ink(string role, string text);
    }

    internal static class SurfaceFonts
    {
        /// The face Windows sets each script language in (win/typeface.py SCRIPT_FACES).
        internal static readonly Dictionary<string, string> ScriptFaces = new Dictionary<string, string> {
            { "ko", "Malgun Gothic" }, { "ja", "Yu Gothic UI" }, { "zh-CN", "Microsoft YaHei UI" },
            { "zh-TW", "Microsoft JhengHei UI" }, { "th", "Leelawadee UI" } };

        internal const string OnEveryWindows = "Segoe UI";

        /// Font roles: size in px at 96 DPI and weight (fonts.ROLES), in the Python's order.
        internal static readonly string[] RoleNames = { "title", "state", "label", "value", "name", "chip", "body", "small", "button" };

        internal static int RoleBase(string role)
        {
            if (role == "title") return 15;
            if (role == "state") return Brand.TypeBody;
            if (role == "label") return Brand.TypeSmall;
            if (role == "value") return Brand.TypeHeading;
            if (role == "name") return Brand.TypeBody;
            if (role == "chip") return Brand.TypeSmall;
            if (role == "body") return Brand.TypeBody;
            if (role == "small") return Brand.TypeSmall;
            if (role == "button") return Brand.TypeBody;
            throw new KeyNotFoundException(role);
        }

        internal static int RoleWeight(string role)
        {
            if (role == "title" || role == "value" || role == "name" || role == "chip" || role == "button") return 600;
            if (role == "state" || role == "label" || role == "body" || role == "small") return 400;
            throw new KeyNotFoundException(role);
        }

        /// Ideographic and Hangul text at 11-12 px loses strokes; these scripts get one pixel more (role_size).
        internal static int RoleSize(string role, string locale)
        {
            int size = RoleBase(role);
            bool dense = locale == "ko" || locale == "ja" || locale == "zh-CN" || locale == "zh-TW";
            return dense && size <= 12 ? size + 1 : size;
        }

        /// The typefaces to try for a locale, best first, the last on every Windows (font_faces). `system` is Windows'
        /// UI font (null or blank: it could not be asked); `lacks(face, text)` which of the locale's `letters` a face
        /// has no glyph for, or null to take every face as whole.
        internal static List<string> FontFaces(string locale, string system, Func<string, string, string> lacks, string letters)
        {
            string own;
            if (locale != null && ScriptFaces.TryGetValue(locale, out own)) return new List<string> { own, OnEveryWindows };
            if (lacks != null && FaceFor(system, letters, lacks) != system) return new List<string> { OnEveryWindows };
            var faces = new List<string>();
            foreach (string face in new[] { system, "Segoe UI Variable Text" })
            {
                if (face == null || face.Trim().Length == 0) continue;
                if (face.ToLowerInvariant() == OnEveryWindows.ToLowerInvariant()) break;
                bool known = false;
                foreach (string have in faces) if (have.ToLowerInvariant() == face.ToLowerInvariant()) known = true;
                if (!known) faces.Add(face);
            }
            faces.Add(OnEveryWindows);
            return faces;
        }

        /// (face, weight) pairs to try for one font role, best first (font_candidates).
        internal static List<KeyValuePair<string, int>> FontCandidates(string locale, int weight, string system,
                                                                      Func<string, string, string> lacks, string letters)
        {
            List<string> faces = FontFaces(locale, system, lacks, letters);
            var found = new List<KeyValuePair<string, int>>();
            if (weight < 600)
            {
                foreach (string face in faces) found.Add(Pair(face, 400));
                return found;
            }
            if (locale == "ja")
            {
                found.Add(Pair("Yu Gothic UI Semibold", 400)); found.Add(Pair("Yu Gothic UI", 600));
                found.Add(Pair("Segoe UI Semibold", 400)); found.Add(Pair("Segoe UI", 600));
                return found;
            }
            if (locale != null && ScriptFaces.ContainsKey(locale))
            {
                found.Add(Pair(faces[0], 700)); found.Add(Pair("Segoe UI Semibold", 400)); found.Add(Pair("Segoe UI", 600));
                return found;
            }
            for (int i = 0; i < faces.Count - 1; i++)
            {
                string face = faces[i], lower = face.ToLowerInvariant();
                bool segoe = lower.StartsWith("segoe ui", StringComparison.Ordinal) && !lower.EndsWith("semibold", StringComparison.Ordinal);
                found.Add(segoe ? Pair(face + " Semibold", 400) : Pair(face, 700));
            }
            found.Add(Pair("Segoe UI Semibold", 400)); found.Add(Pair("Segoe UI", 600));
            return found;
        }

        private static KeyValuePair<string, int> Pair(string face, int weight)
        {
            return new KeyValuePair<string, int>(face, weight);
        }

        // ------------------------------------------------------------------------- win/typeface.py's part

        /// The face `text` is set in when Windows' UI font is `face` (typeface.face_for).
        internal static string FaceFor(string face, string text, Func<string, string, string> lacks)
        {
            if (face == null || face.Trim().Length == 0 || face.Trim().ToLowerInvariant() == OnEveryWindows.ToLowerInvariant()
                || string.IsNullOrEmpty(text))
                return face;
            return lacks(face, text).Length > 0 && lacks(OnEveryWindows, text).Length == 0 ? OnEveryWindows : face;
        }

        /// Every character of `texts` that is drawn, once each, sorted (typeface.letters): less white space, the
        /// characters past the first plane, and the control and format characters.
        internal static string Letters(IEnumerable<object> texts)
        {
            var found = new SortedSet<char>();
            foreach (object value in texts)
            {
                string text = value as string;
                if (text == null) continue;
                foreach (char c in text)
                {
                    if (char.IsSurrogate(c) || PopupWords.IsSpace(c)) continue;
                    UnicodeCategory kind = CharUnicodeInfo.GetUnicodeCategory(c);
                    if (kind == UnicodeCategory.Control || kind == UnicodeCategory.Format) continue;
                    found.Add(c);
                }
            }
            var letters = new StringBuilder();
            foreach (char c in found) letters.Append(c);
            return letters.ToString();
        }

        private static readonly object Lock = new object();
        private static readonly Dictionary<string, string> Lacking = new Dictionary<string, string>();
        private static readonly Dictionary<string, bool> Installed = new Dictionary<string, bool>();
        private const uint GGI_MARK_NONEXISTING_GLYPHS = 0x1;
        private const ushort NoGlyph = 0xFFFF;
        internal const string NoSuchFace = "CodexAutoResume No Such Face";

        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
        private static extern uint GetGlyphIndicesW(IntPtr dc, string text, int count, [Out] ushort[] glyphs, uint flags);

        /// The characters of `text` the face has no glyph of its own for (typeface.lacks); "" when Windows cannot be
        /// asked. Asked once per face and text.
        internal static string Lacks(string face, string text)
        {
            if (face == null || face.Trim().Length == 0 || string.IsNullOrEmpty(text)) return "";
            string key = face + "\u0000" + text;
            lock (Lock)
            {
                string missing;
                if (Lacking.TryGetValue(key, out missing)) return missing;
                missing = "";
                try
                {
                    IntPtr dc = SurfaceNative.CreateCompatibleDC(IntPtr.Zero);
                    if (dc != IntPtr.Zero)
                    {
                        try
                        {
                            IntPtr font = SurfaceNative.CreateFontW(-12, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, face);
                            if (font != IntPtr.Zero)
                            {
                                IntPtr previous = SurfaceNative.SelectObject(dc, font);
                                try
                                {
                                    var glyphs = new ushort[text.Length];
                                    if (GetGlyphIndicesW(dc, text, text.Length, glyphs, GGI_MARK_NONEXISTING_GLYPHS) != 0xFFFFFFFF)
                                    {
                                        var lacking = new StringBuilder();
                                        for (int i = 0; i < text.Length; i++) if (glyphs[i] == NoGlyph) lacking.Append(text[i]);
                                        missing = lacking.ToString();
                                    }
                                }
                                finally
                                {
                                    SurfaceNative.SelectObject(dc, previous);
                                    SurfaceNative.DeleteObject(font);
                                }
                            }
                        }
                        finally { SurfaceNative.DeleteDC(dc); }
                    }
                }
                catch (Exception) { missing = ""; }
                Lacking[key] = missing;
                return missing;
            }
        }

        /// The face GDI realizes for a name, at 12 px (typeface._realized, fonts._realized_face); "" when it makes none.
        internal static string Realized(IntPtr dc, string face)
        {
            IntPtr font = SurfaceNative.CreateFontW(-12, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, face);
            if (font == IntPtr.Zero) return "";
            IntPtr previous = SurfaceNative.SelectObject(dc, font);
            try
            {
                var buffer = new char[64];
                SurfaceNative.GetTextFaceW(dc, 64, buffer);
                int end = Array.IndexOf(buffer, '\0');
                return new string(buffer, 0, end < 0 ? buffer.Length : end);
            }
            finally
            {
                SurfaceNative.SelectObject(dc, previous);
                SurfaceNative.DeleteObject(font);
            }
        }

        private static string substitute;
        private static readonly Dictionary<string, bool> FaceCache = new Dictionary<string, bool>();

        /// Whether GDI has this face itself rather than a substitute for it (fonts._face_exists), asked once per face.
        internal static bool FaceExists(IntPtr dc, string face)
        {
            lock (Lock)
            {
                bool found;
                if (FaceCache.TryGetValue(face, out found)) return found;
                if (substitute == null) substitute = Realized(dc, NoSuchFace);
                string realized = Realized(dc, face);
                found = realized.Length > 0 && (realized.ToLowerInvariant() == face.ToLowerInvariant() || realized != substitute);
                FaceCache[face] = found;
                return found;
            }
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct LOGFONTW
        {
            internal int LfHeight, LfWidth, LfEscapement, LfOrientation, LfWeight;
            internal byte LfItalic, LfUnderline, LfStrikeOut, LfCharSet, LfOutPrecision, LfClipPrecision, LfQuality,
                          LfPitchAndFamily;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] internal string LfFaceName;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct NONCLIENTMETRICSW
        {
            internal uint CbSize;
            internal int IBorderWidth, IScrollWidth, IScrollHeight, ICaptionWidth, ICaptionHeight;
            internal LOGFONTW LfCaptionFont;
            internal int ISmCaptionWidth, ISmCaptionHeight;
            internal LOGFONTW LfSmCaptionFont;
            internal int IMenuWidth, IMenuHeight;
            internal LOGFONTW LfMenuFont, LfStatusFont, LfMessageFont;
            internal int IPaddedBorderWidth;
        }

        private const uint SPI_GETNONCLIENTMETRICS = 0x0029;

        [DllImport("user32.dll", EntryPoint = "SystemParametersInfoW", CharSet = CharSet.Unicode)]
        private static extern bool SystemParametersInfoMetrics(uint action, uint param, ref NONCLIENTMETRICSW value, uint winIni);

        /// The face of Windows' message font, or null when Windows cannot be asked (typeface.ui_face). Asked each time.
        internal static string UiFace()
        {
            try
            {
                var metrics = new NONCLIENTMETRICSW();
                metrics.CbSize = (uint)Marshal.SizeOf(typeof(NONCLIENTMETRICSW));
                if (!SystemParametersInfoMetrics(SPI_GETNONCLIENTMETRICS, metrics.CbSize, ref metrics, 0)) return null;
                string face = metrics.LfMessageFont.LfFaceName;
                return face != null && face.Trim().Length > 0 ? face : null;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// The face a picture stands in for Windows' UI font (fonts.windows_ui_face); null in the product, which asks
        /// Windows every time. Set by a render job only.
        internal static string Pinned { get; set; }
    }

    /// One locale's GDI fonts at one scale, a handle per role (fonts._Fonts). Owns every font it makes.
    internal sealed class SurfaceFontSet : IDisposable
    {
        internal readonly string Locale;
        internal readonly double Scale;
        internal readonly Dictionary<string, IntPtr> Handles = new Dictionary<string, IntPtr>();
        internal readonly Dictionary<string, string> Faces = new Dictionary<string, string>();

        /// `letters` is every character the locale's words draw (typeface.letters of its catalog), for the lacks rule.
        internal SurfaceFontSet(IntPtr dc, string locale, double scale, string letters)
        {
            Locale = locale;
            Scale = scale;
            string system = SurfaceFonts.Pinned ?? SurfaceFonts.UiFace();
            try
            {
                foreach (string role in SurfaceFonts.RoleNames)
                {
                    List<KeyValuePair<string, int>> candidates = SurfaceFonts.FontCandidates(
                        locale, SurfaceFonts.RoleWeight(role), system, SurfaceFonts.Lacks, letters);
                    KeyValuePair<string, int> chosen = candidates[candidates.Count - 1];
                    foreach (KeyValuePair<string, int> candidate in candidates)
                        if (SurfaceFonts.FaceExists(dc, candidate.Key)) { chosen = candidate; break; }
                    int height = -Math.Max(1, (int)Math.Round(SurfaceFonts.RoleSize(role, locale) * scale, MidpointRounding.ToEven));
                    IntPtr handle = SurfaceNative.CreateFontW(height, 0, 0, 0, chosen.Value, 0, 0, 0, 1, 0, 0, 5, 0, chosen.Key);
                    if (handle == IntPtr.Zero) throw new InvalidOperationException("CreateFontW");
                    Handles[role] = handle;
                    Faces[role] = chosen.Key;
                }
            }
            catch
            {
                Dispose();
                throw;
            }
        }

        public void Dispose()
        {
            foreach (IntPtr handle in Handles.Values) SurfaceNative.DeleteObject(handle);
            Handles.Clear();
        }
    }

    /// ITextCalc over GDI: a DC and a locale's fonts, as Renderer.measure and TipRenderer ask them.
    internal sealed class GdiTextCalc : ITextCalc
    {
        private readonly IntPtr dc;
        private readonly SurfaceFontSet fonts;

        internal GdiTextCalc(IntPtr dc, SurfaceFontSet fonts)
        {
            this.dc = dc;
            this.fonts = fonts;
        }

        public int[] Calc(string role, string text, int width, uint flags)
        {
            IntPtr previous = SurfaceNative.SelectObject(dc, fonts.Handles[role]);
            try
            {
                var rect = new SurfaceNative.RECT(0, 0, width, 0);
                SurfaceNative.DrawTextW(dc, text, -1, ref rect, flags);
                return new[] { rect.Right - rect.Left, rect.Bottom - rect.Top };
            }
            finally
            {
                SurfaceNative.SelectObject(dc, previous);
            }
        }

        private static SurfaceNative.MAT2 Identity()
        {
            var identity = new SurfaceNative.MAT2();
            identity.EM11.Value = 1;
            identity.EM22.Value = 1;
            return identity;
        }

        public double[] Metrics(string role)
        {
            IntPtr previous = SurfaceNative.SelectObject(dc, fonts.Handles[role]);
            try
            {
                SurfaceNative.TEXTMETRICW found;
                if (!SurfaceNative.GetTextMetricsW(dc, out found)) throw new InvalidOperationException("GetTextMetricsW");
                SurfaceNative.GLYPHMETRICS glyph;
                SurfaceNative.MAT2 identity = Identity();
                uint answer = SurfaceNative.GetGlyphOutlineW(dc, 'x', SurfaceNative.GGO_METRICS, out glyph, 0, IntPtr.Zero, ref identity);
                double xHeight = answer != SurfaceNative.GDI_ERROR && glyph.GmptGlyphOrigin.Y > 0 ? glyph.GmptGlyphOrigin.Y
                                                                                                 : found.TmAscent / 2.0;
                return new[] { (double)found.TmAscent, xHeight };
            }
            finally
            {
                SurfaceNative.SelectObject(dc, previous);
            }
        }

        public int[] Ink(string role, string text)
        {
            IntPtr previous = SurfaceNative.SelectObject(dc, fonts.Handles[role]);
            try
            {
                text = PyStrip(text ?? "");
                if (text.Length == 0) return new[] { 0, 0 };
                List<string> points = PopupWords.CodePoints(text);
                return new[] { Bearings(points[0])[0], Bearings(points[points.Count - 1])[1] };
            }
            finally
            {
                SurfaceNative.SelectObject(dc, previous);
            }
        }

        private int[] Bearings(string letter)
        {
            SurfaceNative.GLYPHMETRICS glyph;
            SurfaceNative.MAT2 identity = Identity();
            if (string.IsNullOrEmpty(letter)
                || SurfaceNative.GetGlyphOutlineW(dc, (uint)PopupWords.Code(letter), SurfaceNative.GGO_METRICS, out glyph, 0,
                                                  IntPtr.Zero, ref identity) == SurfaceNative.GDI_ERROR
                || glyph.GmBlackBoxX == 0)
                return new[] { 0, 0 };
            int left = glyph.GmptGlyphOrigin.X;
            return new[] { left, glyph.GmCellIncX - left - (int)glyph.GmBlackBoxX };
        }

        /// str.strip(): Python's spaces off both ends.
        internal static string PyStrip(string text)
        {
            List<string> points = PopupWords.CodePoints(text);
            int start = 0, end = points.Count;
            while (start < end && PopupWords.IsSpace(PopupWords.Code(points[start]))) start++;
            while (end > start && PopupWords.IsSpace(PopupWords.Code(points[end - 1]))) end--;
            var kept = new StringBuilder();
            for (int i = start; i < end; i++) kept.Append(points[i]);
            return kept.ToString();
        }
    }

    /// ITextCalc from the table a render job carries: every answer the reference's GDI gave, by its question. A
    /// question the table has no answer for is an error, never a guess, so a plan laid out from it is the reference's
    /// or nothing.
    internal sealed class TableTextCalc : ITextCalc
    {
        private readonly Dictionary<string, int[]> calcs = new Dictionary<string, int[]>();
        private readonly Dictionary<string, double[]> metrics = new Dictionary<string, double[]>();
        private readonly Dictionary<string, int[]> inks = new Dictionary<string, int[]>();

        private static string Key(params object[] parts)
        {
            var key = new StringBuilder();
            foreach (object part in parts) key.Append(Convert.ToString(part, CultureInfo.InvariantCulture)).Append('\u0001');
            return key.ToString();
        }

        /// `measure`: [[role, text, width, flags, w, h], ...]; `metrics`: {role: [ascent, x_height]}; `ink`:
        /// [[role, text, first, last], ...] - Json.Parse's values.
        internal TableTextCalc(List<object> measure, Dictionary<string, object> metricTable, List<object> ink)
        {
            if (measure != null)
                foreach (object entry in measure)
                {
                    var row = (List<object>)entry;
                    calcs[Key(row[0], row[1], (int)(double)row[2], (uint)(double)row[3])] =
                        new[] { (int)(double)row[4], (int)(double)row[5] };
                }
            if (metricTable != null)
                foreach (KeyValuePair<string, object> pair in metricTable)
                {
                    var row = (List<object>)pair.Value;
                    metrics[pair.Key] = new[] { (double)row[0], (double)row[1] };
                }
            if (ink != null)
                foreach (object entry in ink)
                {
                    var row = (List<object>)entry;
                    inks[Key(row[0], row[1])] = new[] { (int)(double)row[2], (int)(double)row[3] };
                }
        }

        public int[] Calc(string role, string text, int width, uint flags)
        {
            int[] found;
            if (calcs.TryGetValue(Key(role, text, width, flags), out found)) return found;
            throw new KeyNotFoundException("no measure for " + role + " " + width + " " + flags + " " + Json.Escape(text));
        }

        public double[] Metrics(string role)
        {
            double[] found;
            if (metrics.TryGetValue(role, out found)) return found;
            throw new KeyNotFoundException("no metrics for " + role);
        }

        public int[] Ink(string role, string text)
        {
            int[] found;
            if (inks.TryGetValue(Key(role, text), out found)) return found;
            throw new KeyNotFoundException("no ink for " + role + " " + Json.Escape(text));
        }
    }

    /// How a popup font role measures a text (Renderer.lines and Renderer.measure), over one ITextCalc.
    internal sealed class SurfaceText
    {
        internal readonly ITextCalc Calc;
        internal readonly string Locale;

        internal SurfaceText(ITextCalc calc, string locale)
        {
            Calc = calc;
            Locale = locale;
        }

        /// Text as it will wrap, with the breaks made explicit where GDI's would be wrong (Renderer.lines): Korean is
        /// broken at spaces only, measured by GDI itself; a word wider than the whole line is left to GDI.
        internal string Lines(string role, string text, int width)
        {
            if (string.IsNullOrEmpty(text) || Locale != "ko") return text;
            var lines = new List<string>();
            string line = "";
            foreach (string word in text.Split(' '))
            {
                string candidate = line.Length == 0 ? word : line + " " + word;
                if (line.Length == 0 || Measure(role, candidate, width, false)[0] <= width) line = candidate;
                else
                {
                    lines.Add(line);
                    line = word;
                }
            }
            lines.Add(line);
            foreach (string entry in lines)
                if (Measure(role, entry, width, false)[0] > width) return text;
            return string.Join("\n", lines.ToArray());
        }

        /// (width, height) of `text` in `role`: wrapped to `width` when `wrap`, on one line otherwise (Renderer.measure).
        internal int[] Measure(string role, string text, int width, bool wrap)
        {
            if (wrap) text = Lines(role, text, width);
            uint flags = SurfaceNative.DT_CALCRECT | SurfaceNative.DT_NOPREFIX
                       | (wrap ? (SurfaceNative.DT_WORDBREAK | SurfaceNative.DT_EDITCONTROL) : SurfaceNative.DT_SINGLELINE);
            return Calc.Calc(role, string.IsNullOrEmpty(text) ? " " : text, Math.Max(1, width), flags);
        }
    }
}

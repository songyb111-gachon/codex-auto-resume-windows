// Codex Auto Resume - the one renderer of the popup, the menu, the tip and the card (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/renderer.py's Renderer, call for call. This file holds its look half
// so far: the theme, the design and High Contrast as the renderer adopts them, the corners each design rounds by
// (_radii, _corner, _control_radius, smoothing, _depth), and every colour it paints with (_tokens, _rgb, _argb,
// _colorref, face_colours), each resolved by a token's name exactly as the Python resolves it. The drawing half
// (_ground, the lifts and wells, the switches, the meter, the buttons, the scene, the text and the halo, over
// SurfaceGdip.cs's flat GDI+ and DrawTextW) is the next step of S6.3; until it is here the render mode dumps plans and
// their paint, and draws no pixel (P6-DESIGN 3.3: comparison B is the main session's, once the drawing is ported).
using System;
using System.Collections.Generic;
using System.Drawing;

namespace CodexAutoResume
{
    internal sealed class SurfaceRenderer
    {
        /// The system colours High Contrast draws with, by name; null asks Windows (system_rgb). A render job sets a
        /// fixed table, so a plan's paint in High Contrast is the same on every machine.
        internal static Dictionary<string, int[]> SystemColours { get; set; }

        /// The theme: "light" or "dark", as the window resolved it.
        internal string Theme = "light";

        private string design = "soft";
        private bool contrast;

        /// The design: one of brand's designs, as the window adopted it.
        internal string Design
        {
            get { return design; }
            set { design = value; }
        }

        /// High Contrast: system colours, and no shadow, tint or glow.
        internal bool Contrast
        {
            get { return contrast; }
            set { contrast = value; }
        }

        /// The card alone (v0.6.24): transparent round it, no lift.
        internal bool Lone { get; set; }

        /// The theme the colours come from: brand's name for it, light for anything unknown (_theme).
        internal string ThemeName()
        {
            return Theme == "light" || Theme == "dark" ? Theme : "light";
        }

        /// The design the drawing follows: brand's name for it, Soft for anything unknown (_design).
        internal string DesignName()
        {
            return Array.IndexOf(SurfaceTheme.Designs, design) >= 0 ? design : Brand.DesignDefault;
        }

        /// Whether anything is drawn with depth: the design has it and High Contrast is off (_depth).
        internal bool Depth()
        {
            return !contrast && Brand.DesignDepth(DesignName());
        }

        /// How much this look smooths its corners: its design's, Soft's in High Contrast (smoothing).
        internal double Smoothing()
        {
            return Brand.DesignSmoothing(contrast ? Brand.DesignDefault : DesignName());
        }

        /// The design's corner radius for a role, in CSS px - Soft's in High Contrast (_radii).
        internal int Radius(string role)
        {
            return Brand.DesignRadius(contrast ? Brand.DesignDefault : DesignName(), role);
        }

        /// A laid-out item's corner in the design, in device px (_corner); an item that names no role keeps the
        /// radius it was laid out with.
        internal double Corner(PlanItem item, double scale)
        {
            object role = item.Get("corner");
            if (role == null) return Convert.ToDouble(item["radius"]);
            return SurfaceMath.Round(Radius((string)role) * scale);
        }

        /// A control's corner in the design, in device px (_control_radius).
        internal double ControlRadius(double scale)
        {
            return Radius("control") * scale;
        }

        /// A token's colour as (red, green, blue): its system colour in High Contrast, else the design's palette in
        /// the theme (_rgb).
        internal int[] Rgb(string token)
        {
            if (contrast)
            {
                string name = SurfaceTheme.ContrastColour(token);
                int[] found;
                if (SystemColours != null && SystemColours.TryGetValue(name, out found)) return found;
                return SurfaceTheme.SystemRgb(name);
            }
            return SurfaceTheme.Rgb(SurfaceTheme.Token(token, ThemeName(), DesignName()));
        }

        /// The token as the ARGB number GDI+ takes (_argb).
        internal uint Argb(string token, double alpha = 1.0)
        {
            int[] rgb = Rgb(token);
            return SurfaceNative.Pack(rgb[0], rgb[1], rgb[2], alpha);
        }

        /// The token as a COLORREF, for GDI's text (_colorref).
        internal uint ColorRef(string token)
        {
            int[] rgb = Rgb(token);
            return (uint)(rgb[0] | (rgb[1] << 8) | (rgb[2] << 16));
        }

        /// ((fill), (edge)) as (red, green, blue): what a button looks like in `state` (face_colours).
        internal int[][] FaceColours(PlanItem item, string state)
        {
            bool primary = SurfaceMath.Truthy(item["primary"]);
            string fill, edge;
            if (state == "busy") { fill = "surface"; edge = "line"; }
            else if (state == "pressed") { fill = primary ? "accent_pressed" : "inset"; edge = primary ? "accent" : "line"; }
            else if (state == "hover") { fill = primary ? "accent_hover" : "surface"; edge = primary ? "accent_hover" : "line"; }
            else { fill = primary ? "accent" : "raised"; edge = primary ? "accent" : "line"; }
            return new[] { Rgb(fill), Rgb(edge) };
        }

        /// A button stands on the card unless it is pressed or busy (_lifted).
        internal static bool Lifted(PlanItem item, object pressed)
        {
            return !SurfaceMath.Truthy(item["busy"]) && !Equals(pressed, item["target"]);
        }

        /// A reason chip's ground: its colour mixed CHIP_ALPHA of the way into the card's surface (CHIP_ALPHA).
        internal const double ChipAlpha = 0.12;
    }
}

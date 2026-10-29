// Codex Auto Resume - the window mirrored for a language written right to left (v0.6.20).
//
// Arabic and Hebrew read from the right. A window in either is mirrored: what stands at the left in every other
// language stands at the right - the columns of a table, the buttons of a row, a card's light and its words, a
// switch's knob, the scroll bar - and its words read right to left. A value written left to right inside them (an
// id, a version, a path, a time) keeps its own order: the text a window draws is filled with it embedded
// (l10n.embedded), never laid out by the sentence's direction.
//
// Measured in v0.6.11 (plans/v0611-sources/s2c_rtl_gaps.md), and why it is done by hand: Form.RightToLeftLayout
// mirrors only a form's direct children, and WS_EX_LAYOUTRTL on a control draws GDI+ text reversed in a
// double-buffered control - every control here is double-buffered. So the window sets RightToLeft on each form,
// which mirrors every table's columns, every flowing row and every anchor inside them, and each of its own layout
// engines and painters asks Mirror where a thing goes. In a language written left to right nothing of this is
// reached: every answer here is its argument unchanged, so that window is exactly what it was.
//
// The light still falls from the top left, as on the popup, the card and the panel: it is the room's light, not the
// reading direction (the decision recorded for the owner in v0.6.11). A check mark is not mirrored.

using System;
using System.Drawing;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal static class Mirror
    {
        /// Whether the window being built is mirrored: set as the settings window or the setup window takes its
        /// language, before anything is built, and read by every form made after it (Soft.TitleBar, which every
        /// window and dialog here calls) - a dialog is a window of its own, and does not inherit its owner's.
        internal static bool Window;

        /// Every language taken as written left to right, for the layout audit's comparison of a window laid out both
        /// ways (SettingsForm.MirrorAudit). Never set by the window itself.
        internal static bool Never;

        /// Whether `locale` - the language a window's words are in - is written right to left (l10n.RIGHT_TO_LEFT).
        internal static bool Language(string locale)
        {
            if (Never || string.IsNullOrEmpty(locale)) return false;
            string language = locale.Split('-', '_')[0].ToLowerInvariant();
            return language == "ar" || language == "he" || language == "iw";
        }

        /// Whether `control` is laid out and drawn mirrored: its window's RightToLeft, which a control inherits from
        /// what it stands in. Never true in a window that is not mirrored.
        internal static bool Of(Control control)
        {
            return control != null && control.RightToLeft == RightToLeft.Yes;
        }

        /// A form mirrored when the window being built is (Window): its RightToLeft, which every control in it then
        /// inherits. RightToLeftLayout stays off - it is the WS_EX_LAYOUTRTL route the measurement closed.
        internal static void Apply(Form form)
        {
            if (form == null || !Window) return;
            if (form.RightToLeft != RightToLeft.Yes) form.RightToLeft = RightToLeft.Yes;
        }

        /// Where something `width` wide that stands `x` from the left of a room `room` wide stands when `mirrored`:
        /// as far from the right.
        internal static int X(bool mirrored, int room, int x, int width)
        {
            return mirrored ? room - x - width : x;
        }

        internal static float X(bool mirrored, float room, float x, float width)
        {
            return mirrored ? room - x - width : x;
        }

        /// `box`, in a room `room` wide, mirrored across it when `mirrored`.
        internal static Rectangle Box(bool mirrored, int room, Rectangle box)
        {
            return mirrored ? new Rectangle(room - box.Right, box.Y, box.Width, box.Height) : box;
        }

        internal static RectangleF Box(bool mirrored, float room, RectangleF box)
        {
            return mirrored ? new RectangleF(room - box.Right, box.Y, box.Width, box.Height) : box;
        }

        /// `box` mirrored inside `within` (both in one control's coordinates) when `mirrored`.
        internal static Rectangle Within(bool mirrored, Rectangle within, Rectangle box)
        {
            return mirrored ? new Rectangle(within.Left + within.Right - box.Right, box.Y, box.Width, box.Height) : box;
        }

        /// Padding with its left and right swapped when `mirrored`.
        internal static Padding Sides(bool mirrored, Padding padding)
        {
            return mirrored ? new Padding(padding.Right, padding.Top, padding.Left, padding.Bottom) : padding;
        }

        /// TextRenderer's flags for words drawn mirrored: aligned to the other side (a centred line stays centred) and
        /// read right to left. Left to right, `flags` itself.
        internal static TextFormatFlags Words(bool mirrored, TextFormatFlags flags)
        {
            if (!mirrored) return flags;
            if ((flags & TextFormatFlags.HorizontalCenter) == 0)
            {
                // Left is no bit of its own (0): a line that is not aligned right is aligned left.
                if ((flags & TextFormatFlags.Right) != 0) flags &= ~TextFormatFlags.Right;
                else flags |= TextFormatFlags.Right;
            }
            return flags | TextFormatFlags.RightToLeft;
        }

        /// An alignment's left and right swapped when `mirrored`; a centred one is itself.
        internal static ContentAlignment Align(bool mirrored, ContentAlignment align)
        {
            if (!mirrored) return align;
            switch (align)
            {
                case ContentAlignment.TopLeft: return ContentAlignment.TopRight;
                case ContentAlignment.TopRight: return ContentAlignment.TopLeft;
                case ContentAlignment.MiddleLeft: return ContentAlignment.MiddleRight;
                case ContentAlignment.MiddleRight: return ContentAlignment.MiddleLeft;
                case ContentAlignment.BottomLeft: return ContentAlignment.BottomRight;
                case ContentAlignment.BottomRight: return ContentAlignment.BottomLeft;
                default: return align;
            }
        }

        /// Anchors with left and right swapped when `mirrored`, for a control placed by Windows' own layout in a
        /// container that is not a table or a flowing row - those mirror their anchors themselves.
        internal static AnchorStyles Anchor(bool mirrored, AnchorStyles anchor)
        {
            if (!mirrored) return anchor;
            bool left = (anchor & AnchorStyles.Left) != 0, right = (anchor & AnchorStyles.Right) != 0;
            anchor &= ~(AnchorStyles.Left | AnchorStyles.Right);
            if (left) anchor |= AnchorStyles.Right;
            if (right) anchor |= AnchorStyles.Left;
            return anchor;
        }
    }
}

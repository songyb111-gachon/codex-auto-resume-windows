// Codex Auto Resume - the window's right-click menus, in its own material (v0.6.18).
//
// Until v0.6.18 a row's menu was Windows' ToolStrip menu in the window's colours: a square window with Windows' square
// drop shadow, a band of tint under the item in hand. The owner asked for it in our design (2026-10-22). Now every menu
// the window opens is a card of the cards' own material - their ground, their radius, their hairline and in dark their
// one-pixel top light - lifted by the cards' own shadow, which spills outside the card over whatever is behind it, as
// the drop-down's list is (SoftDropList, gui/SoftCombo.cs). A child of a top-level window is clipped to itself, so the
// menu's window is layered with an alpha for every pixel (UpdateLayeredWindow): the card opaque, its shadow
// translucent, and nothing beyond. The item in hand rises as the list's item under the pointer does - a raised pill
// with the control's lift - its words in the ink; an item that cannot be used is in the secondary ink; the chosen one of
// a set is a dot in the accent; a line between groups is a hairline; a submenu's arrow is a chevron in the ink. Every
// size is the window's scale (Soft.Px), every colour the palette's (SoftMenuRenderer's colour table), the words the
// window's font, so a language's own face (Typeface.ForLanguage).
//
// Paint only. The items, their order, their words, what each one does, their keys and what a screen reader hears are
// Windows' ToolStrip's, as before. In High Contrast nothing of this applies: the menu is Windows' own, drawn by Windows'
// renderer in the colours the person chose (SoftMenuRenderer.For).

using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace CodexAutoResume
{
    /// A row's own menu (v0.6.11): the Pending list's - postpone the task, let a held one continue, how its conversation
    /// resumes. v0.6.18: a card of the cards' material (see the file's head). Every right-click menu of the window is one
    /// of these, and every submenu a SoftMenuDrop made by Branch.
    internal sealed class SoftMenu : ContextMenuStrip
    {
        private readonly SoftMenuLayer layer;

        internal SoftMenu()
        {
            layer = new SoftMenuLayer(this, PaintFace);
            SoftMenuRenderer.Dress(this);
            // v0.6.20: a menu is a window of its own; mirrored with the window it opens over (Mirror.Window), its items
            // laid out and their words drawn right to left by ToolStrip itself, and every submenu with it.
            if (Mirror.Window) RightToLeft = RightToLeft.Yes;
        }

        /// The card's layer, or null in High Contrast (for the tests).
        internal SoftMenuLayer Layer { get { return layer.On ? layer : null; } }

        /// A submenu drawn as its menu is.
        internal ToolStripMenuItem Branch(string text)
        {
            var item = new ToolStripMenuItem(text);
            item.DropDown = new SoftMenuDrop(Font);
            return item;
        }

        protected override CreateParams CreateParams
        {
            get { return layer == null ? base.CreateParams : layer.Adjust(base.CreateParams); }
        }

        protected override void OnItemAdded(ToolStripItemEventArgs e)
        {
            base.OnItemAdded(e);
            SoftMenuRenderer.Fit(e.Item);
        }

        // The items are laid out inside the card, and the window is the card with room for its shadow round it
        // (SoftMenuLayer.Inside, Outside). Not by Padding, which a drop-down menu sets itself for its check column.
        public override Rectangle DisplayRectangle
        {
            get { return layer == null ? base.DisplayRectangle : layer.Inside(base.DisplayRectangle); }
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            Size size = base.GetPreferredSize(proposedSize);
            return layer == null ? size : layer.Outside(size);
        }

        protected override void SetBoundsCore(int x, int y, int width, int height, BoundsSpecified specified)
        {
            var wanted = new Rectangle(x, y, width, height);
            Rectangle placed = layer == null ? wanted : layer.Place(wanted, specified);
            base.SetBoundsCore(placed.X, placed.Y, placed.Width, placed.Height, specified);
        }

        protected override void WndProc(ref Message m)
        {
            if (layer == null || !layer.Handle(ref m)) base.WndProc(ref m);
        }

        protected override void OnInvalidated(InvalidateEventArgs e)
        {
            base.OnInvalidated(e);
            if (layer != null) layer.Ask();
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            if (layer != null) layer.Ask();
        }

        protected override void OnVisibleChanged(EventArgs e)
        {
            base.OnVisibleChanged(e);
            if (layer == null) return;
            // Drawn as it opens; its picture let go as it closes (a row menu is filled anew each time it opens).
            if (Visible) layer.Open();
            else layer.Closed();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && layer != null) layer.Dispose();
            base.Dispose(disposing);
        }

        // What the menu draws of itself - the renderer's ground, its items and their words - into `g`.
        private void PaintFace(Graphics g, Rectangle whole)
        {
            // Not disposed: it was handed the Graphics, which is the caller's.
            var e = new PaintEventArgs(g, whole);
            OnPaintBackground(e);
            OnPaint(e);
        }
    }

    /// A submenu of a SoftMenu (Branch): the same card, the same renderer, the window's font.
    internal sealed class SoftMenuDrop : ToolStripDropDownMenu
    {
        private readonly SoftMenuLayer layer;

        internal SoftMenuDrop(Font font)
        {
            layer = new SoftMenuLayer(this, PaintFace);
            if (font != null) Font = font;
            SoftMenuRenderer.Dress(this);
        }

        internal SoftMenuLayer Layer { get { return layer.On ? layer : null; } }

        protected override CreateParams CreateParams
        {
            get { return layer == null ? base.CreateParams : layer.Adjust(base.CreateParams); }
        }

        protected override void OnItemAdded(ToolStripItemEventArgs e)
        {
            base.OnItemAdded(e);
            SoftMenuRenderer.Fit(e.Item);
        }

        // The items are laid out inside the card, and the window is the card with room for its shadow round it
        // (SoftMenuLayer.Inside, Outside). Not by Padding, which a drop-down menu sets itself for its check column.
        public override Rectangle DisplayRectangle
        {
            get { return layer == null ? base.DisplayRectangle : layer.Inside(base.DisplayRectangle); }
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            Size size = base.GetPreferredSize(proposedSize);
            return layer == null ? size : layer.Outside(size);
        }

        protected override void SetBoundsCore(int x, int y, int width, int height, BoundsSpecified specified)
        {
            var wanted = new Rectangle(x, y, width, height);
            Rectangle placed = layer == null ? wanted : layer.Place(wanted, specified);
            base.SetBoundsCore(placed.X, placed.Y, placed.Width, placed.Height, specified);
        }

        protected override void WndProc(ref Message m)
        {
            if (layer == null || !layer.Handle(ref m)) base.WndProc(ref m);
        }

        protected override void OnInvalidated(InvalidateEventArgs e)
        {
            base.OnInvalidated(e);
            if (layer != null) layer.Ask();
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            if (layer != null) layer.Ask();
        }

        protected override void OnVisibleChanged(EventArgs e)
        {
            base.OnVisibleChanged(e);
            if (layer == null) return;
            // Drawn as it opens; its picture let go as it closes (a row menu is filled anew each time it opens).
            if (Visible) layer.Open();
            else layer.Closed();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && layer != null) layer.Dispose();
            base.Dispose(disposing);
        }

        private void PaintFace(Graphics g, Rectangle whole)
        {
            // Not disposed: it was handed the Graphics, which is the caller's.
            var e = new PaintEventArgs(g, whole);
            OnPaintBackground(e);
            OnPaint(e);
        }
    }

    /// The menus' renderer (v0.6.18), one for every menu and submenu, and its colour table: every colour it draws is one
    /// of these, and every one of these is the palette's.
    internal sealed class SoftMenuRenderer : ToolStripRenderer
    {
        private static SoftMenuRenderer shared;

        /// The menus' one renderer; in High Contrast, Windows' own (ToolStripManager's), in the system's colours.
        internal static ToolStripRenderer For()
        {
            if (Palette.Contrast) return ToolStripManager.Renderer;
            if (shared == null) shared = new SoftMenuRenderer();
            return shared;
        }

        // ------------------------------------------------------------------ the colour table
        /// The card's ground.
        internal static Color Ground { get { return Palette.Card; } }
        /// The card's hairline, and the line between groups.
        internal static Color Rule { get { return Palette.Line; } }
        /// The item in hand: a raised pill, as the drop-down list's item under the pointer.
        internal static Color Hover { get { return Palette.Raised; } }
        /// An item's words, and a submenu's arrow.
        internal static Color Text { get { return Palette.Ink; } }
        /// The words and arrow of an item that cannot be used now.
        internal static Color Disabled { get { return Palette.Secondary; } }
        /// The dot of the chosen one of a set.
        internal static Color Chosen { get { return Palette.Accent; } }

        /// A menu or submenu set up for the card: this renderer, no image column, a check column for a set's dot, no
        /// square shadow of Windows' (the card draws its own), the card's padding with room for its shadow. In High
        /// Contrast only the renderer, which is Windows'.
        internal static void Dress(ToolStripDropDownMenu menu)
        {
            menu.ShowImageMargin = false;
            menu.ShowCheckMargin = true;
            // High Contrast: Windows' renderer, as a menu has it.
            if (Palette.Contrast) return;
            menu.Renderer = For();
            menu.DropShadowEnabled = false;
        }

        /// An item as tall as the list's pills: its words with the field's padding above and below. A line between
        /// groups keeps its own height.
        internal static void Fit(ToolStripItem item)
        {
            if (Palette.Contrast || item is ToolStripSeparator) return;
            int room = Soft.Px(Brand.SpaceXs);
            item.Padding = new Padding(item.Padding.Left, room, item.Padding.Right, room);
            item.Margin = new Padding(0, Soft.Px(1), 0, Soft.Px(1));
        }

        /// The item in hand on `strip` - under the pointer, or where the keyboard is - that can be used, or null.
        internal static ToolStripItem InHand(ToolStrip strip)
        {
            foreach (ToolStripItem item in strip.Items)
                if (item.Selected && item.Enabled && item.Available && !(item is ToolStripSeparator)) return item;
            return null;
        }

        /// The ground, and the pill the item in hand rises into with the control's lift round it. Drawn under every item
        /// rather than by the item itself, whose own drawing is clipped to its bounds: the lift reaches past them, as the
        /// list's does past its pill (ToolStrip lays each item over the ground it has drawn).
        protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e)
        {
            Graphics g = e.Graphics;
            using (var ground = new SolidBrush(Ground)) g.FillRectangle(ground, e.AffectedBounds);
            ToolStripItem held = InHand(e.ToolStrip);
            if (held == null) return;
            Rectangle pill = held.Bounds;
            float radius = Soft.PxF(Palette.RadiusSmall);
            Elevation.StampOuter(g, pill, "control", radius, e.AffectedBounds);
            Soft.Body(g, pill, radius, Hover, Rule, null);
        }

        // The card's edge is drawn by its layer (SoftMenuLayer.Render), round, with its shadow.
        protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e) { }

        protected override void OnRenderImageMargin(ToolStripRenderEventArgs e) { }

        // The item in hand's pill is under it already (OnRenderToolStripBackground): an item draws no ground of its own.
        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e) { }

        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
        {
            e.TextColor = e.Item.Enabled ? Text : Disabled;
            base.OnRenderItemText(e);
        }

        protected override void OnRenderArrow(ToolStripArrowRenderEventArgs e)
        {
            // A chevron in the ink, drawn round and at the window's scale: Windows' is a filled triangle in its own black.
            Rectangle box = e.ArrowRectangle;
            float half = Soft.PxF(3.5f);
            float cx = box.X + box.Width / 2f, cy = box.Y + box.Height / 2f;
            bool left = e.Direction == ArrowDirection.Left;
            Graphics g = e.Graphics;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var pen = new Pen(e.Item != null && !e.Item.Enabled ? Disabled : Text, Math.Max(1f, Soft.PxF(1.5f))))
            {
                pen.StartCap = LineCap.Round;
                pen.EndCap = LineCap.Round;
                pen.LineJoin = LineJoin.Round;
                float tip = left ? cx - half / 2f : cx + half / 2f, back = left ? cx + half / 2f : cx - half / 2f;
                g.DrawLines(pen, new[] { new PointF(back, cy - half), new PointF(tip, cy), new PointF(back, cy + half) });
            }
            g.Restore(state);
        }

        protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e)
        {
            // The chosen one of a set, as a dot in the accent: the menu's own tick is Windows' light glyph.
            Rectangle box = e.ImageRectangle;
            int size = Math.Max(Soft.Px(6), Math.Min(box.Width, box.Height) / 2);
            var dot = new Rectangle(box.X + (box.Width - size) / 2, box.Y + (box.Height - size) / 2, size, size);
            GraphicsState state = e.Graphics.Save();
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var fill = new SolidBrush(e.Item.Enabled ? Chosen : Disabled)) e.Graphics.FillEllipse(fill, dot);
            e.Graphics.Restore(state);
        }

        protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e)
        {
            int y = e.Item.Height / 2;
            int inset = Soft.Px(Brand.SpaceS);
            using (var rule = new SolidBrush(Rule))
                e.Graphics.FillRectangle(rule, inset, y, Math.Max(0, e.Item.Width - 2 * inset), Soft.Hairline);
        }
    }

    /// The card a menu is drawn as (v0.6.18): its window layered, what the menu draws of itself laid into a rounded card
    /// with the cards' shadow round it, and put on the screen with an alpha for every pixel. Off in High Contrast, where
    /// the menu is Windows' own.
    internal sealed class SoftMenuLayer : IDisposable
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct BitmapHeader
        {
            public int Size, Width, Height;
            public short Planes, BitCount;
            public int Compression, SizeImage, XPerMeter, YPerMeter, Used, Important;
        }

        [DllImport("user32.dll")]
        private static extern IntPtr GetDC(IntPtr window);

        [DllImport("user32.dll")]
        private static extern int ReleaseDC(IntPtr window, IntPtr dc);

        [DllImport("user32.dll")]
        private static extern bool ValidateRect(IntPtr window, IntPtr rect);

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateCompatibleDC(IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteDC(IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern IntPtr SelectObject(IntPtr dc, IntPtr item);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteObject(IntPtr item);

        [DllImport("gdi32.dll")]
        private static extern bool GdiFlush();

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapHeader header, int usage, out IntPtr bits,
                                                      IntPtr section, int offset);

        private const int WS_EX_LAYERED = 0x00080000;
        private const int CS_DROPSHADOW = 0x00020000;
        private const int WM_PAINT = 0x000F;
        private const int WM_ERASEBKGND = 0x0014;
        private const int WM_NCHITTEST = 0x0084;
        private const int HTTRANSPARENT = -1;

        private readonly ToolStripDropDown menu;
        private readonly Action<Graphics, Rectangle> paint;
        private readonly bool on;
        private bool asked, placing;
        private Bitmap image;
        // Windows' copy of the picture, kept for as long as it is the picture (Upload), so a frame of the fade costs one
        // UpdateLayeredWindow and no copy.
        private IntPtr dib, memory, previous;
        private int alpha = 255, rise;
        private Point home;
        private bool opening;
        private readonly Timer timer = new Timer();
        private readonly System.Diagnostics.Stopwatch clock = new System.Diagnostics.Stopwatch();

        internal SoftMenuLayer(ToolStripDropDown menu, Action<Graphics, Rectangle> paint)
        {
            this.menu = menu;
            this.paint = paint;
            on = !Palette.Contrast;
            timer.Interval = Motion.Interval;
            timer.Tick += delegate { Tick(); };
        }

        /// How opaque the whole card is, 0 to 255, and how far below its place it stands: the fade and rise it opens with (for the tests).
        internal int Alpha { get { return alpha; } }
        internal int Rise { get { return rise; } }

        /// Whether it is on its way in; its timer runs only then.
        internal bool Appearing { get { return timer.Enabled; } }

        /// The menu is on the screen (v0.6.23): drawn, fading in and rising into place, as the drop-down's list of the same
        /// material does (SoftDropList.Show, Tick). Immediate with motion reduced.
        internal void Open()
        {
            if (!on) return;
            timer.Stop();
            home = menu.Location;
            opening = Motion.AllowedPopup(menu);
            alpha = opening ? 0 : 255;
            rise = opening ? Soft.Px(Brand.SpaceXs) : 0;
            Render();
            if (!opening) return;
            clock.Reset();
            clock.Start();
            timer.Start();
        }

        private void Tick()
        {
            double t = clock.Elapsed.TotalMilliseconds / Math.Max(1, Motion.Duration);
            double eased = Motion.Ease(t);
            alpha = t >= 1.0 ? 255 : (int)Math.Round(255 * eased);
            rise = t >= 1.0 ? 0 : (int)Math.Round(Soft.Px(Brand.SpaceXs) * (1.0 - eased));
            if (t >= 1.0)
            {
                timer.Stop();
                opening = false;
            }
            if (!menu.IsDisposed && menu.IsHandleCreated) Blit();
        }

        /// The menu has left the screen: its picture stays a moment longer, fading out, on a window of its own that nothing
        /// can touch. A list that faded in leaves the same way (SoftDropList.FadeOut). Then the picture is let go.
        internal void Closed()
        {
            timer.Stop();
            opening = false;
            if (on && image != null && memory != IntPtr.Zero && Motion.AllowedPopup(menu))
            {
                var ghost = new SoftLayerFade(memory, dib, previous, new Rectangle(home.X, home.Y + rise, image.Width, image.Height), alpha);
                memory = dib = previous = IntPtr.Zero;
                ghost.Start();
            }
            Dispose();
        }

        /// Whether the menu is a card (not in High Contrast).
        internal bool On { get { return on; } }

        /// The room a menu's window keeps round its card for the shadow: the cards' own reach.
        internal static Padding Reach { get { return Palette.Contrast ? Padding.Empty : Elevation.Reach("card"); } }

        /// The room inside the card round its items.
        internal static int Pad { get { return Soft.Px(Brand.SpaceXs); } }

        /// `display`, where a drop-down menu would lay its items in a window of its own size, inside the card: less the
        /// shadow's reach and the card's padding on every side.
        internal Rectangle Inside(Rectangle display)
        {
            if (!on) return display;
            Padding reach = Reach;
            int pad = Pad;
            return new Rectangle(display.X + reach.Left + pad, display.Y + reach.Top + pad,
                                 Math.Max(0, display.Width - reach.Horizontal - 2 * pad),
                                 Math.Max(0, display.Height - reach.Vertical - 2 * pad));
        }

        /// The window for a menu that would be `size` on its own: that, with the card's padding and its shadow's reach.
        internal Size Outside(Size size)
        {
            if (!on) return size;
            Padding reach = Reach;
            return new Size(size.Width + reach.Horizontal + 2 * Pad, size.Height + reach.Vertical + 2 * Pad);
        }

        /// What was last drawn: the card and its shadow, premultiplied, the size of the menu's window (for the tests).
        internal Bitmap Image { get { return image; } }

        /// The card in the menu's window.
        internal Rectangle Card
        {
            get
            {
                Padding reach = Reach;
                return new Rectangle(reach.Left, reach.Top, Math.Max(0, menu.Width - reach.Horizontal),
                                     Math.Max(0, menu.Height - reach.Vertical));
            }
        }

        /// The window's styles: layered, and without Windows' square shadow.
        internal CreateParams Adjust(CreateParams cp)
        {
            if (!on) return cp;
            cp.ExStyle |= WS_EX_LAYERED;
            cp.ClassStyle &= ~CS_DROPSHADOW;
            return cp;
        }

        /// Where the menu's window goes when it is placed to be shown (`specified` has a location and it is not yet on
        /// screen): its card where Windows would have put the menu - at the pointer, or beside the item it opens from,
        /// whichever way Windows turned it to fit - and kept within the work area. Its size is its own.
        internal Rectangle Place(Rectangle wanted, BoundsSpecified specified)
        {
            if (!on || placing || menu.Visible || (specified & BoundsSpecified.Location) == 0) return wanted;
            placing = true;
            try { return Within(Shifted(wanted), Screen.FromRectangle(wanted).WorkingArea); }
            finally { placing = false; }
        }

        private Rectangle Shifted(Rectangle wanted)
        {
            Padding reach = Reach;
            ToolStripItem from = menu.OwnerItem;
            ToolStrip parent = from == null ? null : from.Owner;
            if (parent == null || !parent.IsHandleCreated)
            {
                // A menu of its own, at a point: its card's corner there, whichever corner Windows put at it.
                Point at = Cursor.Position;
                bool leftward = Math.Abs(wanted.Right - at.X) < Math.Abs(wanted.Left - at.X);
                bool upward = Math.Abs(wanted.Bottom - at.Y) < Math.Abs(wanted.Top - at.Y);
                return new Rectangle(wanted.X + (leftward ? reach.Right : -reach.Left),
                                     wanted.Y + (upward ? reach.Bottom : -reach.Top), wanted.Width, wanted.Height);
            }
            // A submenu: its card beside its parent's card, a hairline apart, its first item level with the item it
            // opens from - or its last, where Windows turned it upward.
            Rectangle item = parent.RectangleToScreen(from.Bounds);
            Rectangle outer = parent.Bounds;
            Padding theirs = Reach;
            int gap = Soft.Px(2);
            bool toLeft = wanted.Left < item.Left;
            int x = toLeft ? outer.Left + theirs.Left - gap - (wanted.Width - reach.Right)
                           : outer.Right - theirs.Right + gap - reach.Left;
            bool up = wanted.Top < item.Top - wanted.Height / 2;
            Rectangle inside = menu.DisplayRectangle;
            int y = up ? item.Bottom - inside.Bottom : item.Top - inside.Top;
            return new Rectangle(x, y, wanted.Width, wanted.Height);
        }

        // The card kept within `area`; its shadow may reach past it.
        private Rectangle Within(Rectangle window, Rectangle area)
        {
            Padding reach = Reach;
            var card = new Rectangle(window.X + reach.Left, window.Y + reach.Top, window.Width - reach.Horizontal,
                                     window.Height - reach.Vertical);
            int dx = 0, dy = 0;
            if (card.Right > area.Right) dx = area.Right - card.Right;
            if (card.Left + dx < area.Left) dx = area.Left - card.Left;
            if (card.Bottom > area.Bottom) dy = area.Bottom - card.Bottom;
            if (card.Top + dy < area.Top) dy = area.Top - card.Top;
            window.Offset(dx, dy);
            return window;
        }

        /// The window's messages the card answers itself: painting (it puts its picture on the screen instead) and a
        /// press on its shadow (let through to what is under it, which closes the menu as any press outside does).
        internal bool Handle(ref Message m)
        {
            if (!on) return false;
            if (m.Msg == WM_PAINT)
            {
                ValidateRect(m.HWnd, IntPtr.Zero);
                Render();
                m.Result = IntPtr.Zero;
                return true;
            }
            if (m.Msg == WM_ERASEBKGND)
            {
                m.Result = new IntPtr(1);
                return true;
            }
            if (m.Msg == WM_NCHITTEST)
            {
                long packed = m.LParam.ToInt64();
                var at = new Point(unchecked((short)(packed & 0xFFFF)), unchecked((short)((packed >> 16) & 0xFFFF)));
                Rectangle card = Card;
                card.Offset(menu.Bounds.Location);
                if (!card.Contains(at))
                {
                    m.Result = new IntPtr(HTTRANSPARENT);
                    return true;
                }
            }
            return false;
        }

        /// Draws again soon: what the menu draws changed (the item in hand, its size). Once for any number of asks.
        internal void Ask()
        {
            if (!on || asked || !menu.IsHandleCreated || menu.IsDisposed) return;
            asked = true;
            try { menu.BeginInvoke(new MethodInvoker(delegate { asked = false; Render(); })); }
            catch (Exception) { asked = false; }
        }

        /// Draws the card and its shadow again, and puts them on the screen.
        internal void Render()
        {
            if (!on || menu.IsDisposed || menu.Width <= 0 || menu.Height <= 0) return;
            var size = menu.Size;
            Rectangle body = Card;
            if (body.Width <= 0 || body.Height <= 0) return;
            float radius = Soft.PxF(Palette.RadiusCard);
            var next = new Bitmap(size.Width, size.Height, PixelFormat.Format32bppPArgb);
            using (Graphics g = Graphics.FromImage(next))
            {
                g.Clear(Color.Transparent);
                Elevation.StampOuter(g, body, "card", radius, new Rectangle(Point.Empty, size));
            }
            Lay(next, body, radius, Face(size));
            using (Graphics g = Graphics.FromImage(next))
            {
                int hairline = Soft.Hairline;
                // In dark, the card's one-pixel top light; then its hairline.
                Elevation.StampInner(g, Rectangle.Inflate(body, -hairline, -hairline), "card", radius - hairline, body);
                Soft.Edge(g, body, radius, SoftMenuRenderer.Rule, hairline);
            }
            if (image != null) image.Dispose();
            image = next;
            if (menu.IsHandleCreated)
            {
                if (!opening) home = menu.Location;
                Upload();
                Blit();
            }
        }

        // What the menu draws of itself, the size of its window, as opaque RGB: drawn into a device-independent bitmap of
        // Windows' own, where its words come out as the window draws them (on a GDI+ bitmap they came out heavier,
        // without ClearType - SoftDropList.Face).
        private int[] Face(Size size)
        {
            int width = size.Width, height = size.Height;
            var pixels = new int[width * height];
            var header = new BitmapHeader();
            header.Size = Marshal.SizeOf(typeof(BitmapHeader));
            header.Width = width;
            header.Height = -height;
            header.Planes = 1;
            header.BitCount = 24;
            IntPtr screen = GetDC(IntPtr.Zero);
            IntPtr bits, bitmap = IntPtr.Zero, dc = IntPtr.Zero, old = IntPtr.Zero;
            try
            {
                bitmap = CreateDIBSection(screen, ref header, 0, out bits, IntPtr.Zero, 0);
                if (bitmap == IntPtr.Zero || bits == IntPtr.Zero) return pixels;
                dc = CreateCompatibleDC(screen);
                old = SelectObject(dc, bitmap);
                using (Graphics f = Graphics.FromHdc(dc))
                {
                    using (var ground = new SolidBrush(SoftMenuRenderer.Ground)) f.FillRectangle(ground, 0, 0, width, height);
                    paint(f, new Rectangle(0, 0, width, height));
                }
                GdiFlush();
                int stride = (width * 3 + 3) & ~3;
                var row = new byte[stride];
                for (int y = 0; y < height; y++)
                {
                    Marshal.Copy(new IntPtr(bits.ToInt64() + (long)y * stride), row, 0, stride);
                    for (int x = 0; x < width; x++)
                        pixels[y * width + x] = (row[x * 3 + 2] << 16) | (row[x * 3 + 1] << 8) | row[x * 3];
                }
            }
            finally
            {
                if (dc != IntPtr.Zero)
                {
                    SelectObject(dc, old);
                    DeleteDC(dc);
                }
                if (bitmap != IntPtr.Zero) DeleteObject(bitmap);
                ReleaseDC(IntPtr.Zero, screen);
            }
            return pixels;
        }

        // The face laid into the rounded card pixel for pixel: whole inside the rounded edge, and over the shadow in
        // proportion to how much of each edge pixel the card covers (SoftDropList.Lay).
        private static void Lay(Bitmap target, Rectangle body, float radius, int[] face)
        {
            int stride = target.Width;
            using (var mask = new Bitmap(body.Width, body.Height, PixelFormat.Format32bppPArgb))
            {
                using (Graphics m = Graphics.FromImage(mask))
                {
                    m.Clear(Color.Transparent);
                    m.SmoothingMode = SmoothingMode.AntiAlias;
                    m.PixelOffsetMode = PixelOffsetMode.Half;
                    using (GraphicsPath path = Soft.Rounded(new Rectangle(0, 0, body.Width, body.Height), radius))
                    using (var brush = new SolidBrush(SoftMenuRenderer.Ground))
                        m.FillPath(brush, path);
                }
                var whole = new Rectangle(0, 0, body.Width, body.Height);
                BitmapData maskData = mask.LockBits(whole, ImageLockMode.ReadOnly, PixelFormat.Format32bppPArgb);
                BitmapData targetData = target.LockBits(body, ImageLockMode.ReadWrite, PixelFormat.Format32bppPArgb);
                try
                {
                    var maskRow = new int[body.Width];
                    var row = new int[body.Width];
                    for (int y = 0; y < body.Height; y++)
                    {
                        Marshal.Copy(new IntPtr(maskData.Scan0.ToInt64() + (long)y * maskData.Stride), maskRow, 0, body.Width);
                        IntPtr at = new IntPtr(targetData.Scan0.ToInt64() + (long)y * targetData.Stride);
                        Marshal.Copy(at, row, 0, body.Width);
                        for (int x = 0; x < body.Width; x++)
                        {
                            int cover = (maskRow[x] >> 24) & 255;
                            if (cover == 0) continue;
                            int over = face[(body.Y + y) * stride + body.X + x];
                            if (cover == 255)
                            {
                                row[x] = over | unchecked((int)0xFF000000);
                                continue;
                            }
                            int under = row[x], rest = 255 - cover;
                            int a = cover + (((under >> 24) & 255) * rest + 127) / 255;
                            int r = (((over >> 16) & 255) * cover + ((under >> 16) & 255) * rest + 127) / 255;
                            int gr = (((over >> 8) & 255) * cover + ((under >> 8) & 255) * rest + 127) / 255;
                            int b = ((over & 255) * cover + (under & 255) * rest + 127) / 255;
                            row[x] = (a << 24) | (r << 16) | (gr << 8) | b;
                        }
                        Marshal.Copy(row, 0, at, body.Width);
                    }
                }
                finally
                {
                    target.UnlockBits(targetData);
                    mask.UnlockBits(maskData);
                }
            }
        }

        private void ReleasePicture()
        {
            LayerBits.Release(memory, dib, previous);
            memory = dib = previous = IntPtr.Zero;
        }

        // The picture as Windows can lay it on the screen, once for each picture; a frame of the fade only lays it down again.
        private void Upload()
        {
            ReleasePicture();
            LayerBits.Upload(image, out dib, out memory, out previous);
        }

        // The picture laid on the screen, where the menu's window is, at the fade's alpha and rise.
        private void Blit()
        {
            if (memory == IntPtr.Zero || image == null) return;
            LayerBits.Lay(menu.Handle, memory, home.X, home.Y + rise, image.Width, image.Height, alpha);
        }

        public void Dispose()
        {
            timer.Stop();
            ReleasePicture();
            if (image != null) image.Dispose();
            image = null;
        }
    }

    /// A picture Windows can lay on a layered window (v0.6.23): premultiplied, top down, an alpha for every pixel, and the one
    /// call that lays it down at a place and an opacity. The menu's card, its last frame fading out, and the tooltip.
    internal static class LayerBits
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct NativePoint { public int X, Y; }

        [StructLayout(LayoutKind.Sequential)]
        private struct NativeSize { public int Width, Height; }

        [StructLayout(LayoutKind.Sequential, Pack = 1)]
        private struct Blend { public byte Op, Flags, Alpha, Format; }

        [StructLayout(LayoutKind.Sequential)]
        private struct BitmapHeader
        {
            public int Size, Width, Height;
            public short Planes, BitCount;
            public int Compression, SizeImage, XPerMeter, YPerMeter, Used, Important;
        }

        [DllImport("user32.dll")]
        private static extern bool UpdateLayeredWindow(IntPtr window, IntPtr target, ref NativePoint at, ref NativeSize size,
                                                       IntPtr source, ref NativePoint from, int key, ref Blend blend, int flags);

        [DllImport("user32.dll")]
        private static extern IntPtr GetDC(IntPtr window);

        [DllImport("user32.dll")]
        private static extern int ReleaseDC(IntPtr window, IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateCompatibleDC(IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteDC(IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern IntPtr SelectObject(IntPtr dc, IntPtr item);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteObject(IntPtr item);

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapHeader header, int usage, out IntPtr bits,
                                                      IntPtr section, int offset);

        private const int ULW_ALPHA = 2;

        internal static void Upload(Bitmap image, out IntPtr dib, out IntPtr memory, out IntPtr previous)
        {
            dib = memory = previous = IntPtr.Zero;
            int width = image.Width, height = image.Height;
            var header = new BitmapHeader();
            header.Size = Marshal.SizeOf(typeof(BitmapHeader));
            header.Width = width;
            header.Height = -height;
            header.Planes = 1;
            header.BitCount = 32;
            IntPtr screen = GetDC(IntPtr.Zero);
            try
            {
                IntPtr bits;
                IntPtr made = CreateDIBSection(screen, ref header, 0, out bits, IntPtr.Zero, 0);
                if (made == IntPtr.Zero || bits == IntPtr.Zero) return;
                dib = made;
                BitmapData data = image.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.ReadOnly, PixelFormat.Format32bppPArgb);
                try
                {
                    var row = new byte[width * 4];
                    for (int y = 0; y < height; y++)
                    {
                        Marshal.Copy(new IntPtr(data.Scan0.ToInt64() + (long)y * data.Stride), row, 0, row.Length);
                        Marshal.Copy(row, 0, new IntPtr(bits.ToInt64() + (long)y * width * 4), row.Length);
                    }
                }
                finally { image.UnlockBits(data); }
                memory = CreateCompatibleDC(screen);
                previous = SelectObject(memory, dib);
            }
            finally { ReleaseDC(IntPtr.Zero, screen); }
        }

        internal static void Lay(IntPtr window, IntPtr memory, int x, int y, int width, int height, int alpha)
        {
            var at = new NativePoint();
            at.X = x;
            at.Y = y;
            var size = new NativeSize();
            size.Width = width;
            size.Height = height;
            var from = new NativePoint();
            var blend = new Blend();
            blend.Alpha = (byte)Math.Max(0, Math.Min(255, alpha));
            blend.Format = 1;   // AC_SRC_ALPHA: every pixel's own alpha, premultiplied
            UpdateLayeredWindow(window, IntPtr.Zero, ref at, ref size, memory, ref from, 0, ref blend, ULW_ALPHA);
        }

        internal static void Release(IntPtr memory, IntPtr dib, IntPtr previous)
        {
            if (memory != IntPtr.Zero)
            {
                SelectObject(memory, previous);
                DeleteDC(memory);
            }
            if (dib != IntPtr.Zero) DeleteObject(dib);
        }
    }

    /// The last picture of a closed menu, fading out on a window of its own for brand's press time (v0.6.23): the menu's own
    /// window is already hidden by the time a menu knows it has closed. It takes no input - clicks and the pointer go through to
    /// what is under it - and disposes itself.
    internal sealed class SoftLayerFade : NativeWindow
    {
        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr window, int command);

        private const int WS_POPUP = unchecked((int)0x80000000);
        private const int WS_EX_LAYERED = 0x00080000, WS_EX_TRANSPARENT = 0x00000020, WS_EX_TOOLWINDOW = 0x00000080, WS_EX_NOACTIVATE = 0x08000000,
                          WS_EX_TOPMOST = 0x00000008;
        private const int SW_SHOWNOACTIVATE = 4;

        private readonly IntPtr memory, dib, previous;
        private readonly Rectangle bounds;
        private readonly int from;
        private readonly Timer timer = new Timer();
        private readonly System.Diagnostics.Stopwatch clock = new System.Diagnostics.Stopwatch();

        /// How many are on the screen (for the tests).
        internal static int Live;

        internal SoftLayerFade(IntPtr memory, IntPtr dib, IntPtr previous, Rectangle bounds, int alpha)
        {
            this.memory = memory;
            this.dib = dib;
            this.previous = previous;
            this.bounds = bounds;
            from = alpha;
            timer.Interval = Motion.Interval;
            timer.Tick += delegate { Tick(); };
        }

        internal void Start()
        {
            var cp = new CreateParams();
            cp.Caption = "";
            cp.X = bounds.X;
            cp.Y = bounds.Y;
            cp.Width = bounds.Width;
            cp.Height = bounds.Height;
            cp.Style = WS_POPUP;
            cp.ExStyle = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST;
            CreateHandle(cp);
            Live++;
            Lay(from);
            ShowWindow(Handle, SW_SHOWNOACTIVATE);
            clock.Start();
            timer.Start();
        }

        private void Tick()
        {
            double t = clock.Elapsed.TotalMilliseconds / Math.Max(1, Motion.Press);
            if (t >= 1.0)
            {
                timer.Stop();
                timer.Dispose();
                if (Handle != IntPtr.Zero) DestroyHandle();
                LayerBits.Release(memory, dib, previous);
                Live--;
                return;
            }
            Lay((int)Math.Round(from * (1.0 - Motion.Ease(t))));
        }

        private void Lay(int alpha)
        {
            LayerBits.Lay(Handle, memory, bounds.X, bounds.Y, bounds.Width, bounds.Height, alpha);
        }
    }
}

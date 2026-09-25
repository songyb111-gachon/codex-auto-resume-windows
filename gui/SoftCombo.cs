// Codex Auto Resume - the drop-down, and the list it opens.
//
// Its own file because it is two halves of one control and the largest of them: the field,
// and the list that opens under it as a window of its own.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    /// A drop-down that is a well, as the panel's select is. Its closed face is drawn here
    /// entirely - the ground behind its corners, the inset well, the chosen item, the chevron -
    /// and it is always one field high.
    ///
    /// The list it opens is its own (v0.6.5): a card of the cards' material floating just under it,
    /// the cards' soft shadow spilling outside the card (SoftDropList). Windows' list - square
    /// corners, a thin grey border, no shadow and a flat blue band - was the one part of the window
    /// drawn in another design, and the design is one. So what Windows' list did for it, it now does
    /// itself, and the tests hold it to each:
    ///   * it opens on a click, F4, Alt+Down, Alt+Up or Space, and on CB_SHOWDROPDOWN - DroppedDown,
    ///     and what UI Automation's Expand sends. Those are every way Windows' list could open, and all
    ///     of them are answered here, so Windows' list never appears; CB_GETDROPPEDSTATE answers for
    ///     this one;
    ///   * while it is open Up, Down, Home, End, Page Up and Page Down move the highlight, typing
    ///     finds the next item that starts with what was typed (TypeAhead), Enter, F4, Alt+Up,
    ///     Alt+Down, Space and Tab take the highlighted item, and Escape closes it as it was. A click
    ///     takes an item and the wheel scrolls a list longer than it shows;
    ///   * a click anywhere else closes it and goes no further, as the click that closes Windows' list
    ///     does; so does the window losing activation or moving, or the drop-down losing the focus,
    ///     moving or hiding;
    ///   * the focus stays on the drop-down throughout: the list never activates and never takes the
    ///     focus, so every key comes here;
    ///   * a screen reader hears it: the drop-down says it is expanded and has a popup, its one child is
    ///     the list and the list's children are its items, and as the highlight moves the drop-down's
    ///     window raises focus and selection events for the item with the list's own object id
    ///     (ListObjectId), which WM_GETOBJECT answers with the list. UI Automation - Narrator - reads it
    ///     as it reads a Win32 drop-down list, a combo box with its choice that it can expand and
    ///     collapse (UiaRoot), and hears the item the highlight is on (NotifyItem);
    ///   * taking an item sets SelectedIndex, so SelectedIndexChanged and every caller work as before,
    ///     and SelectionChangeCommitted is raised as a choice from the list raises it.
    internal sealed class SoftCombo : ComboBox
    {
        private const int WM_KEYDOWN = 0x0100;
        private const int WM_CHAR = 0x0102;
        private const int WM_SYSKEYDOWN = 0x0104;
        private const int WM_SYSCHAR = 0x0106;
        private const int WM_LBUTTONDOWN = 0x0201;
        private const int WM_LBUTTONDBLCLK = 0x0203;
        private const int WM_MOUSEWHEEL = 0x020A;
        private const int CB_SHOWDROPDOWN = 0x014F;
        private const int CB_GETDROPPEDSTATE = 0x0157;

        /// The object id a screen reader asks the drop-down's window for (WM_GETOBJECT) to reach its
        /// list; the focus and selection events for the list's items are raised with it.
        internal const int ListObjectId = 1;

        /// How long letters typed one after another make one search, in milliseconds.
        internal const int TypeAhead = 1000;

        private SoftDropList drop;
        private int highlight = -1;
        private bool keyboard;
        private string typed = "";
        private readonly System.Diagnostics.Stopwatch typing = new System.Diagnostics.Stopwatch();
        // The character a key this handled is followed by (Enter's, Escape's, Space's), which goes no further.
        private int swallow = -1;
        private DropFilter filter;
        private ListAccessible listObject;
        private readonly EventHandler closer;
        private readonly List<Control> watched = new List<Control>();
        private Form watchedForm;

        internal SoftCombo()
        {
            DrawMode = DrawMode.OwnerDrawFixed;
            DropDownStyle = ComboBoxStyle.DropDownList;
            FlatStyle = FlatStyle.Flat;
            BackColor = Palette.Raised;
            ForeColor = Palette.Ink;
            // How many items its list shows before it scrolls: every list in the window whole - the
            // longest, the Interface language, has ten choices.
            MaxDropDownItems = 12;
            closer = delegate { CloseList(); };
            Fit();
        }

        /// The height every SoftCombo has: the panel's field height.
        internal static int FieldHeight
        {
            get { return Soft.Px(Brand.FieldHeight); }
        }

        // A native drop-down list is its item height plus a frame of its own - six device pixels
        // at every scale, measured - and ignores any height it is given once it has a window. So
        // the height is set through the item height: from that frame before there is a window,
        // so the first layout is already right, then from the real frame once there is one, and
        // again whenever the font changes - which is when it used to grow past its row.
        //
        // Before there is a window the item height is only recorded, with the drop-down drawn as
        // a plain one for that moment. Set on an owner-drawn drop-down, ComboBox makes the window
        // there and then (UpdateItemHeight): every one had a window and a list window from its
        // constructor, in Settings sections nobody had opened, and the height it has before a
        // window was never measured. The window takes the recorded height when it is made.
        private const int Frame = 6;

        private void Fit()
        {
            if (!IsHandleCreated)
            {
                int item = Math.Max(1, FieldHeight - Frame);
                if (ItemHeight != item)
                {
                    DrawMode = DrawMode.Normal;
                    ItemHeight = item;
                    DrawMode = DrawMode.OwnerDrawFixed;
                }
                Height = FieldHeight;
                return;
            }
            int wanted = Math.Max(1, FieldHeight - (Height - ItemHeight));
            if (ItemHeight != wanted) ItemHeight = wanted;
        }

        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); Fit(); }
        protected override void OnHandleDestroyed(EventArgs e) { CloseList(); base.OnHandleDestroyed(e); }
        protected override void OnFontChanged(EventArgs e) { base.OnFontChanged(e); Fit(); Invalidate(); }

        /// The height it really has. The base class answers from the font alone - 33 for a
        /// 42-pixel owner-drawn combo at 150% - and a row measured from that cut the field's
        /// bottom edge off.
        public override Size GetPreferredSize(Size proposedSize)
        {
            return new Size(base.GetPreferredSize(proposedSize).Width, IsHandleCreated ? Height : FieldHeight);
        }

        // Without a window ComboBox holds a drop-down list to its font's height whatever height it
        // is given - 23 at 9 points, measured, in a constraint a subclass cannot change - so until
        // the window takes its height from the item height, the bounds are put back to a field's
        // height. Once there is a window they are left alone.
        protected override void SetBoundsCore(int x, int y, int width, int height, BoundsSpecified specified)
        {
            base.SetBoundsCore(x, y, width, height, specified);
            if (!IsHandleCreated && Height != FieldHeight) UpdateBounds(Left, Top, Width, FieldHeight);
        }

        protected override void OnSelectedIndexChanged(EventArgs e) { base.OnSelectedIndexChanged(e); Invalidate(); }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnDropDownClosed(EventArgs e) { base.OnDropDownClosed(e); Invalidate(); }
        protected override void OnResize(EventArgs e) { base.OnResize(e); Invalidate(); }

        protected override void Dispose(bool disposing)
        {
            if (disposing) CloseList();
            base.Dispose(disposing);
        }

        // ------------------------------------------------------------------ its own list

        /// Whether its list is open.
        internal bool Open { get { return drop != null; } }

        /// The item the highlight is on while the list is open: the one Enter takes.
        internal int Highlight { get { return highlight; } }

        /// Whether the highlight shows the focus ring: the list was opened, or moved, from the keyboard.
        /// Under the pointer the item there is raised instead.
        internal bool KeyboardCues { get { return keyboard; } }

        /// The open list, or null.
        internal SoftDropList DropList { get { return drop; } }

        protected override void WndProc(ref Message m)
        {
            if (IsHandleCreated && NativePaint.Handle(ref m, ClientSize, PaintFace)) return;
            if (ListMessage(ref m)) return;
            if (UiaRoot(ref m)) return;
            base.WndProc(ref m);
        }

        private const int WM_GETOBJECT = 0x003D;
        private const int UiaRootObjectId = -25;

        /// UI Automation asking the drop-down's window for a provider of its own (WM_GETOBJECT with
        /// UiaRootObjectId) is told there is none, as a Win32 drop-down list tells it, and reads the drop-down
        /// the way it reads every one of those: a combo box, its choice (the Selection pattern), expanded or
        /// collapsed, and Expand and Collapse - which send CB_SHOWDROPDOWN, answered here with this list.
        ///
        /// Left to ComboBox, .NET 4.8 answers it with a provider of its own around whatever accessible object
        /// the control has, and around ComboAccessible that provider says only "pane": no choice, no Expand or
        /// Collapse, no children - the control type and the patterns come from .NET's own ComboBox object,
        /// which a ControlAccessibleObject cannot supply (they are internal to WinForms). Narrator read every
        /// drop-down in the window as a pane it could not open (v0.6.5, measured with UI Automation against
        /// both builds; v0.6.4's was "combo box, Deutsch, collapsed"). A screen reader that reads MSAA still
        /// gets ComboAccessible (OBJID_CLIENT), and the items are announced to both kinds (NotifyItem).
        /// Compared on the low 32 bits: the id is a DWORD, which a caller may pass sign-extended or not.
        private bool UiaRoot(ref Message m)
        {
            if (m.Msg != WM_GETOBJECT || unchecked((int)m.LParam.ToInt64()) != UiaRootObjectId) return false;
            DefWndProc(ref m);
            return true;
        }

        /// Every message that would open Windows' own list, and the keys and the wheel while this one
        /// is open. True when it was answered here.
        private bool ListMessage(ref Message m)
        {
            int message = m.Msg;
            if (message == CB_SHOWDROPDOWN)
            {
                if (m.WParam != IntPtr.Zero) OpenList(false);
                else CloseList();
                m.Result = (IntPtr)1;
                return true;
            }
            if (message == CB_GETDROPPEDSTATE)
            {
                m.Result = (IntPtr)(Open ? 1 : 0);
                return true;
            }
            if (message == WM_LBUTTONDOWN || message == WM_LBUTTONDBLCLK)
            {
                if (!Focused) Focus();
                if (Open) CloseList();
                else OpenList(false);
                return true;
            }
            if (message == WM_MOUSEWHEEL && Open)
            {
                drop.Wheel(WheelDelta(m.WParam));
                m.Result = IntPtr.Zero;
                return true;
            }
            if (message == WM_KEYDOWN || message == WM_SYSKEYDOWN) return Key(ref m);
            if (message == WM_CHAR || message == WM_SYSCHAR)
            {
                int code = (int)(m.WParam.ToInt64() & 0xFFFF);
                bool swallowed = code == swallow;
                swallow = -1;
                if (swallowed) return true;
                if (message == WM_CHAR && Open)
                {
                    Typed((char)code);
                    return true;
                }
            }
            return false;
        }

        internal static int WheelDelta(IntPtr wParam)
        {
            return unchecked((short)((wParam.ToInt64() >> 16) & 0xFFFF));
        }

        private bool Key(ref Message m)
        {
            swallow = -1;
            Keys key = (Keys)(int)(m.WParam.ToInt64() & 0xFFFF);
            // The context bit, not ModifierKeys: it is what the message says, whatever the keyboard is doing now.
            bool alt = m.Msg == WM_SYSKEYDOWN && (m.LParam.ToInt64() & 0x20000000L) != 0;
            bool plain = m.Msg == WM_KEYDOWN && (ModifierKeys & (Keys.Control | Keys.Alt)) == Keys.None;
            if (!Open)
            {
                bool opens = (alt && (key == Keys.Down || key == Keys.Up)) || (plain && (key == Keys.F4 || key == Keys.Space));
                if (!opens) return false;
                if (key == Keys.Space) swallow = ' ';
                OpenList(true);
                return true;
            }
            if (alt)
            {
                if (key != Keys.Down && key != Keys.Up) return false;
                Pick(highlight);
                return true;
            }
            if (m.Msg != WM_KEYDOWN) return false;
            int page = Math.Max(1, drop.Rows - 1);
            if (key == Keys.Down) MoveHighlight(highlight + 1);
            else if (key == Keys.Up) MoveHighlight(highlight - 1);
            else if (key == Keys.Home) MoveHighlight(0);
            else if (key == Keys.End) MoveHighlight(Items.Count - 1);
            else if (key == Keys.PageDown) MoveHighlight(highlight + page);
            else if (key == Keys.PageUp) MoveHighlight(highlight - page);
            else if (key == Keys.Return)
            {
                swallow = '\r';
                Pick(highlight);
            }
            else if (key == Keys.Escape)
            {
                swallow = 27;
                CloseList();
            }
            else if (key == Keys.F4) Pick(highlight);
            else if (key == Keys.Space)
            {
                // A space inside a search is part of it ("Last 7 days"); otherwise it takes the item.
                if (Typing) return true;
                swallow = ' ';
                Pick(highlight);
            }
            else if (key != Keys.Left && key != Keys.Right) return false;
            return true;
        }

        // While the list is open the keys it answers are the drop-down's, never the window's: Escape does not
        // close a dialog, Enter does not press a default button.
        protected override bool IsInputKey(Keys keyData)
        {
            if (Open && (keyData & (Keys.Alt | Keys.Control)) == Keys.None)
            {
                Keys key = keyData & Keys.KeyCode;
                if (key == Keys.Up || key == Keys.Down || key == Keys.Home || key == Keys.End || key == Keys.PageUp ||
                    key == Keys.PageDown || key == Keys.Return || key == Keys.Escape || key == Keys.Space || key == Keys.F4)
                    return true;
            }
            return base.IsInputKey(keyData);
        }

        // Tab takes the highlighted item and moves on, as a select-only combo box's Tab does.
        protected override bool ProcessDialogKey(Keys keyData)
        {
            if (Open && (keyData & Keys.KeyCode) == Keys.Tab && (keyData & (Keys.Alt | Keys.Control)) == Keys.None)
                Pick(highlight);
            return base.ProcessDialogKey(keyData);
        }

        private bool Typing
        {
            get { return typed.Length > 0 && typing.ElapsedMilliseconds < TypeAhead; }
        }

        private void Typed(char character)
        {
            if (character < ' ') return;
            if (!Typing) typed = "";
            typed += character;
            typing.Reset();
            typing.Start();
            var texts = new string[Items.Count];
            for (int i = 0; i < texts.Length; i++) texts[i] = GetItemText(Items[i]);
            int found = Find(texts, typed, highlight);
            if (found >= 0) MoveHighlight(found);
        }

        /// The item `typed` finds among `texts`, with the highlight on `from`: the first from there on
        /// that starts with it, ignoring case, round to the start again. A first letter looks from the
        /// item after the highlight, and the same letter again steps on through the items that start
        /// with it, as Windows' lists do; a longer search keeps the highlighted item while it still
        /// matches. -1 when none does.
        internal static int Find(string[] texts, string typed, int from)
        {
            int count = texts == null ? 0 : texts.Length;
            if (count == 0 || string.IsNullOrEmpty(typed)) return -1;
            bool repeated = true;
            for (int i = 1; i < typed.Length; i++)
                if (char.ToUpperInvariant(typed[i]) != char.ToUpperInvariant(typed[0])) repeated = false;
            string wanted = repeated ? typed.Substring(0, 1) : typed;
            int start = repeated ? from + 1 : from;
            for (int step = 0; step < count; step++)
            {
                int i = ((start + step) % count + count) % count;
                string text = texts[i];
                if (text != null && text.StartsWith(wanted, StringComparison.CurrentCultureIgnoreCase)) return i;
            }
            return -1;
        }

        /// Opens its list, with the highlight on the chosen item: the focus ring showing on it when it is
        /// opened from the keyboard. Nothing happens when it is disabled, empty or not on screen.
        internal void OpenList(bool fromKeyboard)
        {
            if (Open || !Enabled || !IsHandleCreated || Items.Count == 0 || !Soft.Shown(this)) return;
            Form form = FindForm();
            if (form == null || !form.IsHandleCreated) return;
            highlight = SelectedIndex >= 0 && SelectedIndex < Items.Count ? SelectedIndex : 0;
            keyboard = fromKeyboard;
            typed = "";
            drop = new SoftDropList(this);
            Watch(form);
            OnDropDown(EventArgs.Empty);
            if (drop == null) return;
            drop.Show();
            Invalidate();
            AccessibilityNotifyClients(AccessibleEvents.StateChange, -1);
            AccessibilityNotifyClients(AccessibleEvents.Show, ListObjectId, -1);
            NotifyItem(highlight);
        }

        /// Closes its list, if it is open, leaving the choice as it is.
        internal void CloseList()
        {
            if (drop == null) return;
            SoftDropList closing = drop;
            drop = null;
            Unwatch();
            closing.Dispose();
            typed = "";
            if (IsHandleCreated)
            {
                AccessibilityNotifyClients(AccessibleEvents.Hide, ListObjectId, -1);
                AccessibilityNotifyClients(AccessibleEvents.StateChange, -1);
                if (Focused) AccessibilityNotifyClients(AccessibleEvents.Focus, -1);
            }
            OnDropDownClosed(EventArgs.Empty);
        }

        /// Moves the highlight to `index`, kept to the list, scrolling it into view, with the focus ring on it.
        internal void MoveHighlight(int index)
        {
            if (drop == null || Items.Count == 0) return;
            index = Math.Max(0, Math.Min(Items.Count - 1, index));
            bool moved = index != highlight;
            highlight = index;
            keyboard = true;
            drop.Reveal(index);
            drop.Render();
            if (moved) NotifyItem(index);
        }

        /// The pointer is over item `index` of the open list (-1: over none): the highlight follows it,
        /// shown by the item rising rather than by the ring.
        internal void Hovered(int index)
        {
            keyboard = false;
            if (index >= 0 && index < Items.Count) highlight = index;
        }

        /// Takes item `index` and closes the list: SelectedIndex, and SelectedIndexChanged, when it is not
        /// the item already chosen.
        internal void Pick(int index)
        {
            CloseList();
            if (index < 0 || index >= Items.Count || index == SelectedIndex) return;
            SelectedIndex = index;
            OnSelectionChangeCommitted(EventArgs.Empty);
            AccessibilityNotifyClients(AccessibleEvents.ValueChange, -1);
        }

        /// Tells screen readers the highlight is on item `index`. A reader of MSAA hears the focus and selection
        /// events for the list's item (ListObjectId), and UI Automation turns the selection event into its own; but
        /// UI Automation takes a focus event only for what has the keyboard focus, and that stays on the drop-down.
        /// So the item's focus is also raised to UI Automation itself, as .NET's own ComboBox raises it for the
        /// item its list's highlight is on - the item as UI Automation's MSAA proxy reads it (SoftDropList.RaiseFocus).
        private void NotifyItem(int index)
        {
            if (!IsHandleCreated || index < 0 || index >= Items.Count) return;
            AccessibilityNotifyClients(AccessibleEvents.Focus, ListObjectId, index);
            AccessibilityNotifyClients(AccessibleEvents.Selection, ListObjectId, index);
            if (drop != null) SoftDropList.RaiseFocus(ListObject, index);
        }

        // What closes the list while it is open: the window losing activation, moving or resizing; the
        // drop-down losing the focus, or it or anything it is in moving, resizing, hiding or going; and a
        // click anywhere but the list and the drop-down (DropFilter).
        private void Watch(Form form)
        {
            watchedForm = form;
            form.Deactivate += closer;
            form.Move += closer;
            form.Resize += closer;
            LostFocus += closer;
            for (Control c = this; c != null && c != form; c = c.Parent)
            {
                c.VisibleChanged += closer;
                c.LocationChanged += closer;
                c.SizeChanged += closer;
                c.EnabledChanged += closer;
                c.ParentChanged += closer;
                watched.Add(c);
            }
            if (filter == null) filter = new DropFilter(this);
            Application.AddMessageFilter(filter);
        }

        private void Unwatch()
        {
            if (filter != null) Application.RemoveMessageFilter(filter);
            if (watchedForm != null)
            {
                watchedForm.Deactivate -= closer;
                watchedForm.Move -= closer;
                watchedForm.Resize -= closer;
                watchedForm = null;
            }
            LostFocus -= closer;
            foreach (Control c in watched)
            {
                c.VisibleChanged -= closer;
                c.LocationChanged -= closer;
                c.SizeChanged -= closer;
                c.EnabledChanged -= closer;
                c.ParentChanged -= closer;
            }
            watched.Clear();
        }

        /// What the thread's message loop sees while the list is open, before any window does: a press of
        /// a mouse button anywhere but the list and the drop-down closes it - and, in a window's client
        /// area, goes no further, as the press that closes Windows' own list does; on a title bar it goes
        /// on, so the window still moves - and a turn of the wheel anywhere scrolls the list, never the page
        /// under it.
        private sealed class DropFilter : IMessageFilter
        {
            private const int WM_NCLBUTTONDOWN = 0x00A1;
            private const int WM_NCRBUTTONDOWN = 0x00A4;
            private const int WM_NCMBUTTONDOWN = 0x00A7;
            private const int WM_NCXBUTTONDOWN = 0x00AB;
            private const int WM_RBUTTONDOWN = 0x0204;
            private const int WM_MBUTTONDOWN = 0x0207;
            private const int WM_XBUTTONDOWN = 0x020B;
            private readonly SoftCombo combo;

            internal DropFilter(SoftCombo combo) { this.combo = combo; }

            public bool PreFilterMessage(ref Message m)
            {
                SoftDropList list = combo.drop;
                if (list == null) return false;
                int message = m.Msg;
                if (message == WM_MOUSEWHEEL)
                {
                    list.Wheel(WheelDelta(m.WParam));
                    return true;
                }
                bool client = message == WM_LBUTTONDOWN || message == WM_RBUTTONDOWN || message == WM_MBUTTONDOWN ||
                              message == WM_XBUTTONDOWN || message == WM_LBUTTONDBLCLK;
                bool frame = message == WM_NCLBUTTONDOWN || message == WM_NCRBUTTONDOWN || message == WM_NCMBUTTONDOWN ||
                             message == WM_NCXBUTTONDOWN;
                if (!client && !frame) return false;
                if (m.HWnd == list.Handle) return false;
                if (client && message == WM_LBUTTONDOWN && combo.IsHandleCreated && m.HWnd == combo.Handle) return false;
                combo.CloseList();
                return client;
            }
        }

        // ------------------------------------------------------------------ what a screen reader hears

        protected override AccessibleObject CreateAccessibilityInstance()
        {
            return new ComboAccessible(this);
        }

        protected override AccessibleObject GetAccessibilityObjectById(int objectId)
        {
            return objectId == ListObjectId ? ListObject : base.GetAccessibilityObjectById(objectId);
        }

        /// Its list's accessible object: the drop-down's one child, whose children are the items.
        internal AccessibleObject ListObject
        {
            get
            {
                if (listObject == null) listObject = new ListAccessible(this);
                return listObject;
            }
        }

        private sealed class ComboAccessible : ControlAccessibleObject
        {
            private readonly SoftCombo combo;

            internal ComboAccessible(SoftCombo owner) : base(owner) { combo = owner; }

            public override AccessibleRole Role
            {
                get { return combo.AccessibleRole != AccessibleRole.Default ? combo.AccessibleRole : AccessibleRole.ComboBox; }
            }

            public override AccessibleStates State
            {
                get
                {
                    AccessibleStates state = base.State & ~(AccessibleStates.Expanded | AccessibleStates.Collapsed);
                    return state | AccessibleStates.HasPopup | (combo.Open ? AccessibleStates.Expanded : AccessibleStates.Collapsed);
                }
            }

            public override string Value
            {
                get { return combo.SelectedIndex >= 0 ? combo.GetItemText(combo.SelectedItem) : ""; }
                set { }
            }

            public override void DoDefaultAction()
            {
                if (combo.Open)
                {
                    combo.CloseList();
                    return;
                }
                if (!combo.Focused) combo.Focus();
                combo.OpenList(true);
            }

            public override int GetChildCount() { return 1; }

            public override AccessibleObject GetChild(int index)
            {
                return index == 0 ? combo.ListObject : null;
            }
        }

        private sealed class ListAccessible : AccessibleObject
        {
            private readonly SoftCombo combo;
            private readonly List<ItemAccessible> items = new List<ItemAccessible>();

            internal ListAccessible(SoftCombo combo) { this.combo = combo; }

            public override AccessibleRole Role { get { return AccessibleRole.List; } }

            public override string Name
            {
                get { return combo.AccessibilityObject.Name; }
                set { }
            }

            public override AccessibleStates State
            {
                get { return combo.Open ? AccessibleStates.None : AccessibleStates.Invisible | AccessibleStates.Offscreen; }
            }

            public override Rectangle Bounds
            {
                get { return combo.drop != null ? combo.drop.CardOnScreen : Rectangle.Empty; }
            }

            public override AccessibleObject Parent { get { return combo.AccessibilityObject; } }

            public override int GetChildCount() { return combo.Items.Count; }

            public override AccessibleObject GetChild(int index)
            {
                if (index < 0 || index >= combo.Items.Count) return null;
                while (items.Count <= index) items.Add(new ItemAccessible(this, combo, items.Count));
                return items[index];
            }

            public override AccessibleObject GetFocused()
            {
                return combo.Open ? GetChild(combo.highlight) : null;
            }

            public override AccessibleObject GetSelected()
            {
                return GetFocused();
            }

            public override AccessibleObject HitTest(int x, int y)
            {
                if (combo.drop == null) return null;
                int index = combo.drop.ItemAtScreen(new Point(x, y));
                if (index >= 0) return GetChild(index);
                return combo.drop.CardOnScreen.Contains(x, y) ? this : null;
            }
        }

        private sealed class ItemAccessible : AccessibleObject
        {
            private readonly ListAccessible list;
            private readonly SoftCombo combo;
            private readonly int index;

            internal ItemAccessible(ListAccessible list, SoftCombo combo, int index)
            {
                this.list = list;
                this.combo = combo;
                this.index = index;
            }

            public override AccessibleRole Role { get { return AccessibleRole.ListItem; } }

            public override string Name
            {
                get { return index < combo.Items.Count ? combo.GetItemText(combo.Items[index]) : ""; }
                set { }
            }

            public override AccessibleStates State
            {
                get
                {
                    AccessibleStates state = AccessibleStates.Selectable | AccessibleStates.Focusable;
                    SoftDropList drop = combo.drop;
                    if (drop == null) return state | AccessibleStates.Invisible | AccessibleStates.Offscreen;
                    if (!drop.Shows(index)) state |= AccessibleStates.Offscreen;
                    if (combo.highlight == index) state |= AccessibleStates.Focused | AccessibleStates.Selected;
                    return state;
                }
            }

            public override Rectangle Bounds
            {
                get { return combo.drop != null ? combo.drop.ItemOnScreen(index) : Rectangle.Empty; }
            }

            public override AccessibleObject Parent { get { return list; } }

            public override void DoDefaultAction()
            {
                combo.Pick(index);
            }

            public override void Select(AccessibleSelection flags)
            {
                if ((flags & (AccessibleSelection.TakeFocus | AccessibleSelection.TakeSelection)) != 0 && combo.Open)
                    combo.MoveHighlight(index);
            }

            public override AccessibleObject Navigate(AccessibleNavigation direction)
            {
                if (direction == AccessibleNavigation.Next || direction == AccessibleNavigation.Down) return list.GetChild(index + 1);
                if (direction == AccessibleNavigation.Previous || direction == AccessibleNavigation.Up) return list.GetChild(index - 1);
                return null;
            }
        }

        // ------------------------------------------------------------------ the closed face

        private void PaintFace(Graphics g)
        {
            Rectangle face = ClientRectangle;
            float radius = Soft.PxF(Palette.RadiusControl);
            Ground.PaintBehind(this, g, face, radius);
            Soft.InsetWell(g, face, radius, Focused && ShowFocusCues);
            string text = SelectedIndex >= 0 ? GetItemText(SelectedItem) : "";
            int left = Soft.Px(Brand.SelectPadLeft), right = Soft.Px(Brand.SelectPadRight);
            TextRenderer.DrawText(g, text, Font, new Rectangle(left, 0, Math.Max(0, face.Width - left - right), face.Height),
                                  Enabled ? Palette.Ink : Palette.Muted,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.SingleLine |
                                  TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
            // The chevron: a small wedge in the muted colour, where the panel's select has it.
            float wedge = Soft.PxF(Brand.ChevronWidth), tall = Soft.PxF(Brand.ChevronHeight);
            float right1 = face.Right - Soft.Hairline - Soft.PxF(Brand.ChevronRight), left1 = right1 - wedge;
            float top = face.Top + face.Height * 0.55f - tall / 2f;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var brush = new SolidBrush(Enabled ? Palette.Muted : Soft.Mix(Palette.Muted, Palette.Inset, 0.5)))
                g.FillPolygon(brush, new[] { new PointF(left1, top), new PointF(right1, top), new PointF((left1 + right1) / 2f, top + tall) });
            g.Restore(state);
        }

        // Windows draws only the closed face with this now - its own list never opens.
        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            if (e.Index < 0) return;
            bool selected = (e.State & DrawItemState.Selected) != 0;
            bool face = (e.State & DrawItemState.ComboBoxEdit) != 0;
            // The closed face is PaintFace's. Windows draws it by itself as well when the choice
            // changes from the keyboard; that becomes a repaint, not a square over the well.
            if (face)
            {
                Invalidate();
                return;
            }
            bool highlighted = selected && !face;
            Color back = highlighted ? Palette.AccentSoft : Palette.Raised;
            // In High Contrast that ground is Highlight, and the one text colour every contrast
            // theme pairs with Highlight is HighlightText - as the page tabs have it. WindowText
            // on Highlight is under 1.5:1 in Aquatic and Desert.
            Color ink = !Enabled ? Palette.Muted
                      : highlighted && Palette.Contrast ? SystemColors.HighlightText : Palette.Ink;
            using (var brush = new SolidBrush(back)) e.Graphics.FillRectangle(brush, e.Bounds);
            var bounds = new Rectangle(e.Bounds.X + Soft.Px(6), e.Bounds.Y, Math.Max(0, e.Bounds.Width - Soft.Px(8)), e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, GetItemText(Items[e.Index]), Font, bounds, ink,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        }
    }

    /// The list a SoftCombo opens (v0.6.5): a card of the cards' own material - their ground, their
    /// radius, their hairline and in dark their one-pixel top light - floating just under the drop-down,
    /// lifted by the cards' own shadow (brand.SHADOWS' "card"), which spills outside the card over
    /// whatever is behind it. A child window is clipped to itself, so the list is a top-level window
    /// of its own, layered, with an alpha for every pixel (UpdateLayeredWindow): the card opaque, the
    /// shadow around it translucent, and nothing beyond. It is owned by the drop-down's window, never
    /// activates (WS_EX_NOACTIVATE, MA_NOACTIVATE), and lets a press on its shadow through to what is
    /// under it (HTTRANSPARENT), which closes it like any press outside.
    ///
    /// It opens under the drop-down, `Gap` below it and `Indent` to its left, so its items' words start
    /// exactly under the drop-down's own; above it where the screen has no room below and has room above;
    /// and where neither side has room for every row, on the side with more, as many whole rows as fit
    /// (Place). It shows up to MaxDropDownItems rows and scrolls the rest inside the card on the soft bar.
    /// Every size is the window's scale (Soft.Px) - the scale the drop-down itself is drawn at - and it
    /// keeps to the work area of the monitor the drop-down is on.
    ///
    /// Its items are pills set in the drop-down's font with the field's own padding, SpaceXs apart. The
    /// item chosen now is a sunken pill - a well, with its inset shadow - and its words are the accent;
    /// the item under the pointer rises, a raised pill with the control's lift; the item the keyboard is
    /// on has the focus ring. In High Contrast there is no shadow anywhere, the card is Window with a
    /// WindowFrame edge, the chosen item Highlight with HighlightText, and the item under the pointer
    /// has a Highlight edge.
    ///
    /// It opens with a fade from nothing and a rise of SpaceXs into place over brand's transition, on its
    /// one curve (Motion); with motion reduced it is simply there. It closes at once.
    internal sealed class SoftDropList : NativeWindow, IDisposable
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

        [StructLayout(LayoutKind.Sequential)]
        private struct TrackEvent
        {
            public int Size, Flags;
            public IntPtr Window;
            public int Hover;
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
        private static extern bool GdiFlush();

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapHeader header, int usage, out IntPtr bits,
                                                      IntPtr section, int offset);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr window, int command);

        [DllImport("user32.dll")]
        private static extern bool TrackMouseEvent(ref TrackEvent track);

        [DllImport("user32.dll")]
        private static extern IntPtr SetCapture(IntPtr window);

        [DllImport("user32.dll")]
        private static extern bool ReleaseCapture();

        [DllImport("oleacc.dll")]
        private static extern IntPtr LresultFromObject(ref Guid iid, IntPtr wParam, IntPtr unknown);

        /// IID_IAccessible, as oleacc.h defines it. Built from its fields rather than written as a string: the
        /// repository holds no GUID-shaped text but made-up ones (tests/test_repo_hygiene.py).
        private static readonly Guid IAccessibleId = new Guid(0x618736e0, 0x3c3d, 0x11cf, 0x81, 0x0c, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71);

        [DllImport("uiautomationcore.dll")]
        private static extern bool UiaClientsAreListening();

        [DllImport("uiautomationcore.dll")]
        private static extern int UiaProviderFromIAccessible(IntPtr accessible, int child, int flags, out IntPtr provider);

        [DllImport("uiautomationcore.dll")]
        private static extern int UiaRaiseAutomationEvent(IntPtr provider, int eventId);

        private const int UIA_AutomationFocusChangedEventId = 20005;

        /// `accessible` as the IAccessible a screen reader is handed - a reference the caller releases - or zero.
        private static IntPtr AccessibleInterface(AccessibleObject accessible)
        {
            Type type = Type.GetType("Accessibility.IAccessible, Accessibility, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a", false);
            return type == null ? IntPtr.Zero : Marshal.GetComInterfaceForObject(accessible, type);
        }

        /// Raises UI Automation's focus-changed event for item `index` of `list` (SoftCombo.NotifyItem), when a UI
        /// Automation client is listening: the item as UI Automation's MSAA proxy reads it (UiaProviderFromIAccessible),
        /// a list item with its name. Nothing else changes, and a failure is only an event not heard.
        internal static void RaiseFocus(AccessibleObject list, int index)
        {
            try
            {
                if (!UiaClientsAreListening()) return;
                IntPtr unknown = AccessibleInterface(list);
                if (unknown == IntPtr.Zero) return;
                IntPtr provider = IntPtr.Zero;
                try
                {
                    if (UiaProviderFromIAccessible(unknown, index + 1, 0, out provider) == 0 && provider != IntPtr.Zero)
                        UiaRaiseAutomationEvent(provider, UIA_AutomationFocusChangedEventId);
                }
                finally
                {
                    if (provider != IntPtr.Zero) Marshal.Release(provider);
                    Marshal.Release(unknown);
                }
            }
            catch (Exception) { }
        }

        internal const int WS_EX_LAYERED = 0x00080000;
        internal const int WS_EX_TOOLWINDOW = 0x00000080;
        internal const int WS_EX_NOACTIVATE = 0x08000000;
        internal const int MA_NOACTIVATE = 3;
        private const int WS_POPUP = unchecked((int)0x80000000);
        private const int SW_SHOWNOACTIVATE = 4;
        private const int ULW_ALPHA = 2;
        private const int WM_SETCURSOR = 0x0020;
        private const int WM_MOUSEACTIVATE = 0x0021;
        private const int WM_GETOBJECT = 0x003D;
        private const int WM_NCHITTEST = 0x0084;
        private const int WM_MOUSEMOVE = 0x0200;
        private const int WM_LBUTTONDOWN = 0x0201;
        private const int WM_LBUTTONUP = 0x0202;
        private const int WM_LBUTTONDBLCLK = 0x0203;
        private const int WM_MOUSEWHEEL = 0x020A;
        private const int WM_CAPTURECHANGED = 0x0215;
        private const int WM_MOUSELEAVE = 0x02A3;
        private const int HTCLIENT = 1;
        private const int HTTRANSPARENT = -1;
        private const int OBJID_CLIENT = -4;
        private const int TME_LEAVE = 0x00000002;

        private const TextFormatFlags Flags = TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.SingleLine |
                                              TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix;

        /// The screen area a list keeps to, in place of its monitor's work area - for the tests and the
        /// captures, which open lists in windows nobody sees. Empty: the monitor's.
        internal static Rectangle Area = Rectangle.Empty;

        private readonly SoftCombo combo;
        private readonly Timer timer = new Timer();
        private readonly System.Diagnostics.Stopwatch clock = new System.Diagnostics.Stopwatch();
        private Rectangle card;
        private Padding margin;
        private bool above, scrolls, tracking, dragging;
        private int pad, pill, rowGap, rows, offset, extent, grab, hover = -1, alpha = 255, rise;
        private Point pointer;
        private Bitmap image;
        private IntPtr memory, dib, previous;

        internal SoftDropList(SoftCombo combo)
        {
            this.combo = combo;
            timer.Interval = Motion.Interval;
            timer.Tick += delegate { Tick(); };
        }

        /// The card, on the screen, where it settles.
        internal Rectangle Card { get { return card; } }

        /// The card on the screen where it is now: lower by what is left of its rise while it appears.
        internal Rectangle CardOnScreen { get { return new Rectangle(card.X, card.Y + rise, card.Width, card.Height); } }

        /// The room its window keeps around the card for the shadow: none in High Contrast.
        internal Padding Margin { get { return margin; } }

        /// Whether it opened above the drop-down.
        internal bool Above { get { return above; } }

        /// Whether it holds more rows than it shows, and scrolls them on the soft bar.
        internal bool Scrolls { get { return scrolls; } }

        /// How many whole rows it shows.
        internal int Rows { get { return rows; } }

        /// How far its rows are scrolled, in pixels.
        internal int Offset { get { return offset; } }

        /// The item under the pointer, or -1.
        internal int Hover { get { return hover; } }

        /// Its opacity now, 0 to 255: under 255 only while it fades in.
        internal int Alpha { get { return alpha; } }

        /// Whether it is still fading in and rising; its timer runs only then.
        internal bool Appearing { get { return timer.Enabled; } }

        /// What was last drawn: the card and its shadow, premultiplied, the size of its window.
        internal Bitmap Image { get { return image; } }

        /// A row: an item's pill and the gap under it.
        internal int Pitch { get { return pill + rowGap; } }

        /// How tall a card of `rows` rows is.
        internal static int CardHeight(int rows, int pill, int rowGap, int pad)
        {
            return 2 * pad + rows * pill + Math.Max(0, rows - 1) * rowGap;
        }

        /// Where the card goes for a drop-down at `field` on the screen, `width` wide with `wanted` rows
        /// of `pill` and `rowGap` inside `pad`: `pad` left of the field, so its items' words start under the
        /// field's, and `gap` below it - or above it where `area` has no room below and has room above.
        /// Where neither side has room for every row it goes on the side with more, as many whole rows as fit
        /// there and never fewer than one (`rows`). Across, it is kept inside `area`.
        internal static Rectangle Place(Rectangle field, int width, int wanted, int pill, int rowGap, int pad,
                                        Rectangle area, int gap, out bool above, out int rows)
        {
            width = Math.Max(0, Math.Min(width, area.Width));
            int x = Math.Max(area.Left, Math.Min(area.Right - width, field.X - pad));
            int below = area.Bottom - (field.Bottom + gap), over = field.Top - gap - area.Top;
            rows = Math.Max(1, wanted);
            int height = CardHeight(rows, pill, rowGap, pad);
            above = false;
            if (height > below)
            {
                if (height <= over) above = true;
                else
                {
                    above = over > below;
                    int room = above ? over : below;
                    rows = Math.Max(1, Math.Min(rows, (room - 2 * pad + rowGap) / Math.Max(1, pill + rowGap)));
                    height = CardHeight(rows, pill, rowGap, pad);
                }
            }
            return new Rectangle(x, above ? field.Top - gap - height : field.Bottom + gap, width, height);
        }

        private void Measure()
        {
            Rectangle field = combo.RectangleToScreen(combo.ClientRectangle);
            Rectangle area = Area.IsEmpty ? Screen.FromRectangle(field).WorkingArea : Area;
            Font font = combo.Font;
            pad = Soft.Px(Brand.SpaceS);
            rowGap = Soft.Px(Brand.SpaceXs);
            var unbounded = new Size(int.MaxValue, int.MaxValue);
            pill = TextRenderer.MeasureText("Ag", font, unbounded, Flags).Height + 2 * Soft.Px(Brand.SpaceS);
            int widest = 0, count = combo.Items.Count;
            for (int i = 0; i < count; i++)
                widest = Math.Max(widest, TextRenderer.MeasureText(combo.GetItemText(combo.Items[i]) ?? "", font, unbounded, Flags).Width);
            extent = count * pill + Math.Max(0, count - 1) * rowGap;
            int wanted = Math.Max(1, Math.Min(count, combo.MaxDropDownItems));
            int words = widest + 2 * Soft.Px(Brand.SelectPadLeft);
            int width = Math.Max(field.Width, words) + 2 * pad;
            card = Place(field, width, wanted, pill, rowGap, pad, area, Soft.Px(Brand.SpaceXs), out above, out rows);
            scrolls = rows < count;
            if (scrolls)
            {
                // Room for the soft bar beside the items, which keep the width their words need.
                width = Math.Max(field.Width, words + SoftBar.Gutter) + 2 * pad;
                card = Place(field, width, wanted, pill, rowGap, pad, area, Soft.Px(Brand.SpaceXs), out above, out rows);
            }
            margin = Palette.Contrast ? Padding.Empty : Elevation.Reach("card");
            offset = 0;
            pointer = Cursor.Position;
        }

        /// Opens it: measured, placed, drawn, shown without taking activation, and - unless motion is
        /// reduced - fading in and rising into place.
        internal void Show()
        {
            Measure();
            bool animate = Motion.Allowed(combo);
            alpha = animate ? 0 : 255;
            rise = animate ? Soft.Px(Brand.SpaceXs) : 0;
            var cp = new CreateParams();
            cp.Caption = "";
            cp.X = card.X - margin.Left;
            cp.Y = card.Y - margin.Top + rise;
            cp.Width = card.Width + margin.Horizontal;
            cp.Height = card.Height + margin.Vertical;
            cp.Style = WS_POPUP;
            cp.ExStyle = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
            Form form = combo.FindForm();
            if (form != null && form.IsHandleCreated) cp.Parent = form.Handle;
            CreateHandle(cp);
            Reveal(combo.Highlight);
            Render();
            ShowWindow(Handle, SW_SHOWNOACTIVATE);
            if (!animate) return;
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
            if (t >= 1.0) timer.Stop();
            Push();
        }

        // ------------------------------------------------------------------ geometry, in the card's coordinates

        private int Viewport { get { return Math.Max(1, card.Height - 2 * pad); } }

        private Rectangle TrackRect
        {
            get
            {
                int width = Soft.Px(SoftBar.TrackWidth);
                return new Rectangle(card.Width - Soft.Hairline - Soft.Px(SoftBar.TrackMargin) - width, pad, width, Viewport);
            }
        }

        private Rectangle ThumbRect
        {
            get
            {
                Rectangle track = TrackRect;
                int inset = Soft.Px(SoftBar.ThumbInset), start, length;
                SoftBar.Thumb(track.Height - 2 * inset, extent, Viewport, offset, Soft.Px(SoftBar.MinThumb), out start, out length);
                return new Rectangle(track.X + inset, track.Y + inset + start, Math.Max(0, track.Width - 2 * inset), length);
            }
        }

        /// Item `index`'s pill, in the card's coordinates, where it is scrolled to.
        internal Rectangle PillRect(int index)
        {
            int right = scrolls ? TrackRect.X - Soft.Px(Brand.SpaceXs) : card.Width - pad;
            return new Rectangle(pad, pad + index * (pill + rowGap) - offset, Math.Max(0, right - pad), pill);
        }

        /// The item at `local`, a point in the card's coordinates, or -1. The gap under a pill is its item's.
        internal int ItemAt(Point local)
        {
            int count = combo.Items.Count;
            Rectangle column = PillRect(0);
            if (count == 0 || local.X < column.Left || local.X >= column.Right) return -1;
            if (local.Y < pad || local.Y >= card.Height - pad) return -1;
            int along = local.Y - pad + offset;
            int index = along / Math.Max(1, pill + rowGap);
            return along < 0 || index >= count ? -1 : index;
        }

        internal int ItemAtScreen(Point screen)
        {
            Rectangle now = CardOnScreen;
            return ItemAt(new Point(screen.X - now.X, screen.Y - now.Y));
        }

        /// Item `index`'s pill on the screen, as much of it as shows; empty when none does.
        internal Rectangle ItemOnScreen(int index)
        {
            Rectangle shown = Rectangle.Intersect(PillRect(index), new Rectangle(0, pad, card.Width, Viewport));
            if (shown.IsEmpty) return Rectangle.Empty;
            Rectangle now = CardOnScreen;
            shown.Offset(now.X, now.Y);
            return shown;
        }

        internal bool Shows(int index)
        {
            return !ItemOnScreen(index).IsEmpty;
        }

        /// Scrolls just far enough that item `index` shows whole. Drawn by whoever asked.
        internal void Reveal(int index)
        {
            if (!scrolls || index < 0) return;
            int top = index * (pill + rowGap);
            offset = SoftBar.IntoView(offset, top, top + pill, Viewport, 0, extent);
        }

        /// Scrolls by one turn of the wheel, `delta` as Windows reports it.
        internal void Wheel(int delta)
        {
            if (!scrolls) return;
            int step = SoftBar.WheelStep(delta, SystemInformation.MouseWheelScrollLines, pill + rowGap, Viewport);
            if (ScrollTo(offset + step)) Render();
        }

        private bool ScrollTo(int target)
        {
            target = Math.Max(0, Math.Min(Math.Max(0, extent - Viewport), target));
            if (target == offset) return false;
            offset = target;
            return true;
        }

        // ------------------------------------------------------------------ drawing

        /// Draws the card and its shadow again, and puts them on the screen.
        internal void Render()
        {
            if (card.Width <= 0 || card.Height <= 0) return;
            var size = new Size(card.Width + margin.Horizontal, card.Height + margin.Vertical);
            var next = new Bitmap(size.Width, size.Height, PixelFormat.Format32bppPArgb);
            var body = new Rectangle(margin.Left, margin.Top, card.Width, card.Height);
            float radius = Soft.PxF(Palette.RadiusCard);
            using (Graphics g = Graphics.FromImage(next))
            {
                g.Clear(Color.Transparent);
                Elevation.StampOuter(g, body, "card", radius, new Rectangle(Point.Empty, size));
            }
            Lay(next, body, radius);
            using (Graphics g = Graphics.FromImage(next))
            {
                int hairline = Soft.Hairline;
                // In dark, the card's one-pixel top light; then its hairline.
                Elevation.StampInner(g, Rectangle.Inflate(body, -hairline, -hairline), "card", radius - hairline, body);
                Soft.Edge(g, body, radius, Palette.Line, hairline);
            }
            if (image != null) image.Dispose();
            image = next;
            Upload();
            Push();
        }

        // The card's face is drawn opaque into a bitmap of Windows' own (Face), where its words are drawn as
        // the window draws them - drawn on a GDI+ bitmap they came out heavier, without ClearType - and laid
        // into the rounded card pixel for pixel: whole inside the rounded edge, and over the shadow in
        // proportion to how much of each edge pixel the card covers.
        private void Lay(Bitmap target, Rectangle body, float radius)
        {
            int[] face = Face(body.Width, body.Height);
            using (var mask = new Bitmap(body.Width, body.Height, PixelFormat.Format32bppPArgb))
            {
                using (Graphics m = Graphics.FromImage(mask))
                {
                    m.Clear(Color.Transparent);
                    m.SmoothingMode = SmoothingMode.AntiAlias;
                    m.PixelOffsetMode = PixelOffsetMode.Half;
                    using (GraphicsPath path = Soft.Rounded(new Rectangle(0, 0, body.Width, body.Height), radius))
                    using (var brush = new SolidBrush(Palette.Card))
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
                            int over = face[y * body.Width + x];
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

        // The card's face, `width` by `height`, as opaque RGB, drawn into a device-independent bitmap of
        // Windows' own.
        private int[] Face(int width, int height)
        {
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
                using (Graphics f = Graphics.FromHdc(dc)) PaintFace(f);
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

        private void PaintFace(Graphics f)
        {
            var whole = new Rectangle(0, 0, card.Width, card.Height);
            using (var brush = new SolidBrush(Palette.Card)) f.FillRectangle(brush, whole);
            int count = combo.Items.Count, chosen = combo.SelectedIndex, highlight = combo.Highlight;
            bool cues = combo.KeyboardCues;
            float radius = Soft.PxF(Palette.RadiusSmall);
            int words = Soft.Px(Brand.SelectPadLeft);
            for (int i = 0; i < count; i++)
            {
                Rectangle item = PillRect(i);
                if (item.Bottom < 0 || item.Top > card.Height) continue;
                Color ink = Palette.Ink;
                if (i == chosen)
                {
                    if (Palette.Contrast)
                    {
                        Soft.Body(f, item, radius, SystemColors.Highlight, SystemColors.Highlight, null);
                        ink = SystemColors.HighlightText;
                    }
                    else
                    {
                        Soft.Body(f, item, radius, Palette.Inset, Palette.Line, "inset");
                        ink = Palette.Accent;
                    }
                }
                else if (i == hover && !cues)
                {
                    if (Palette.Contrast) Soft.Edge(f, item, radius, SystemColors.Highlight, Soft.Hairline);
                    else
                    {
                        Elevation.StampOuter(f, item, "control", radius, whole);
                        Soft.Body(f, item, radius, Palette.Raised, Palette.Line, null);
                    }
                }
                var text = new Rectangle(item.X + words, item.Y, Math.Max(0, item.Width - 2 * words), item.Height);
                TextRenderer.DrawText(f, combo.GetItemText(combo.Items[i]), combo.Font, text, ink, Flags);
            }
            if (scrolls)
            {
                // What scrolls stops at the card's padding, as a list's rows stop at its edge.
                using (var brush = new SolidBrush(Palette.Card))
                {
                    f.FillRectangle(brush, 0, 0, card.Width, pad);
                    f.FillRectangle(brush, 0, card.Height - pad, card.Width, pad);
                }
            }
            if (cues && highlight >= 0 && highlight < count) Soft.Ring(f, PillRect(highlight), radius);
            // The list is its own window, drawn here rather than by a parent: its ground is the card it
            // just filled, which is what the track's colour is chosen against.
            if (scrolls) SoftBar.Draw(f, TrackRect, ThumbRect, dragging ? 2 : 0, Palette.Card);
        }

        // Copies what was drawn into a bitmap Windows can lay on the screen: premultiplied, top down.
        private void Upload()
        {
            Release();
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
                dib = CreateDIBSection(screen, ref header, 0, out bits, IntPtr.Zero, 0);
                if (dib == IntPtr.Zero || bits == IntPtr.Zero) return;
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

        private void Push()
        {
            if (Handle == IntPtr.Zero || memory == IntPtr.Zero || image == null) return;
            var at = new NativePoint();
            at.X = card.X - margin.Left;
            at.Y = card.Y - margin.Top + rise;
            var size = new NativeSize();
            size.Width = image.Width;
            size.Height = image.Height;
            var from = new NativePoint();
            var blend = new Blend();
            blend.Alpha = (byte)Math.Max(0, Math.Min(255, alpha));
            blend.Format = 1;   // AC_SRC_ALPHA: every pixel's own alpha, premultiplied
            UpdateLayeredWindow(Handle, IntPtr.Zero, ref at, ref size, memory, ref from, 0, ref blend, ULW_ALPHA);
        }

        private void Release()
        {
            if (memory != IntPtr.Zero)
            {
                SelectObject(memory, previous);
                DeleteDC(memory);
                memory = IntPtr.Zero;
            }
            if (dib != IntPtr.Zero)
            {
                DeleteObject(dib);
                dib = IntPtr.Zero;
            }
        }

        // ------------------------------------------------------------------ the pointer

        protected override void WndProc(ref Message m)
        {
            int message = m.Msg;
            if (message == WM_MOUSEACTIVATE)
            {
                m.Result = (IntPtr)MA_NOACTIVATE;
                return;
            }
            if (message == WM_NCHITTEST)
            {
                m.Result = (IntPtr)(CardOnScreen.Contains(ScreenPoint(m.LParam)) ? HTCLIENT : HTTRANSPARENT);
                return;
            }
            if (message == WM_SETCURSOR)
            {
                Cursor.Current = Cursors.Default;
                m.Result = (IntPtr)1;
                return;
            }
            if (message == WM_MOUSEMOVE)
            {
                Moved(ClientPoint(m.LParam));
                return;
            }
            if (message == WM_MOUSELEAVE)
            {
                tracking = false;
                if (!dragging && hover >= 0)
                {
                    hover = -1;
                    Render();
                }
                return;
            }
            if (message == WM_LBUTTONDOWN || message == WM_LBUTTONDBLCLK)
            {
                Pressed(ClientPoint(m.LParam));
                return;
            }
            if (message == WM_LBUTTONUP)
            {
                Released(ClientPoint(m.LParam));
                return;
            }
            if (message == WM_MOUSEWHEEL)
            {
                Wheel(SoftCombo.WheelDelta(m.WParam));
                m.Result = IntPtr.Zero;
                return;
            }
            if (message == WM_CAPTURECHANGED) dragging = false;
            if (message == WM_GETOBJECT && Accessible(ref m)) return;
            base.WndProc(ref m);
        }

        private static Point ScreenPoint(IntPtr lParam)
        {
            long value = lParam.ToInt64();
            return new Point(unchecked((short)(value & 0xFFFF)), unchecked((short)((value >> 16) & 0xFFFF)));
        }

        // A point in the window, in the card's coordinates.
        private Point ClientPoint(IntPtr lParam)
        {
            Point point = ScreenPoint(lParam);
            return new Point(point.X - margin.Left, point.Y - margin.Top);
        }

        private void Moved(Point local)
        {
            if (!tracking)
            {
                var track = new TrackEvent();
                track.Size = Marshal.SizeOf(typeof(TrackEvent));
                track.Flags = TME_LEAVE;
                track.Window = Handle;
                tracking = TrackMouseEvent(ref track);
            }
            if (dragging)
            {
                Rectangle track = TrackRect, thumb = ThumbRect;
                int inset = Soft.Px(SoftBar.ThumbInset);
                if (ScrollTo(SoftBar.OffsetAt(track.Height - 2 * inset, extent, Viewport, thumb.Height, local.Y - grab - track.Y - inset)))
                    Render();
                return;
            }
            // Windows moves the pointer's message on when a window appears or scrolls under a pointer that
            // is standing still; only a pointer that moved takes the highlight from the keyboard.
            Point now = Cursor.Position;
            if (now == pointer && combo.KeyboardCues) return;
            pointer = now;
            SetHover(ItemAt(local));
        }

        private void SetHover(int index)
        {
            if (index == hover && !combo.KeyboardCues) return;
            hover = index;
            if (index >= 0 || combo.KeyboardCues) combo.Hovered(index);
            Render();
        }

        private void Pressed(Point local)
        {
            if (!scrolls) return;
            Rectangle track = TrackRect;
            int slack = Soft.Px(SoftBar.TrackMargin);
            if (!Rectangle.Inflate(track, slack, 0).Contains(local)) return;
            Rectangle thumb = ThumbRect;
            if (local.Y >= thumb.Top && local.Y < thumb.Bottom)
            {
                dragging = true;
                grab = local.Y - thumb.Top;
                SetCapture(Handle);
                Render();
                return;
            }
            int page = SoftBar.PageStep(Viewport, pill + rowGap);
            if (ScrollTo(offset + (local.Y < thumb.Top ? -page : page))) Render();
        }

        private void Released(Point local)
        {
            if (dragging)
            {
                dragging = false;
                ReleaseCapture();
                Render();
                return;
            }
            int index = ItemAt(local);
            if (index >= 0) combo.Pick(index);
        }

        // A screen reader asking the list's own window what it is gets the list, as asking the drop-down's does.
        private bool Accessible(ref Message m)
        {
            if (unchecked((int)m.LParam.ToInt64()) != OBJID_CLIENT) return false;
            try
            {
                IntPtr unknown = AccessibleInterface(combo.ListObject);
                if (unknown == IntPtr.Zero) return false;
                try
                {
                    Guid iid = IAccessibleId;
                    m.Result = LresultFromObject(ref iid, m.WParam, unknown);
                }
                finally { Marshal.Release(unknown); }
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public void Dispose()
        {
            timer.Stop();
            timer.Dispose();
            if (dragging) ReleaseCapture();
            dragging = false;
            if (Handle != IntPtr.Zero) DestroyHandle();
            Release();
            if (image != null)
            {
                image.Dispose();
                image = null;
            }
        }
    }
}

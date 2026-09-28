// Codex Auto Resume - Custom...: a value of the person's own beside a drop-down's choices (v0.6.11).
//
// Every drop-down whose schema carries `custom` (settings.describe, ownvalues.published) ends in Custom...,
// which opens a small dialog for a value of the person's own - a number and its unit, a time of day, or the
// days of the week - with the range it may be in said above it. Whether a value is taken is never decided
// here: the dialog composes the words the settings store (`m45`, `13:15`, `mon,wed,fri`, `mb1280`,
// `above_300000`) and asks the bridge (`check-setting`), which answers with the settings validator's verdict
// and the value in the one spelling it will be stored in. Only then does the drop-down show it, as one item
// before Custom..., or as the choice it turned out to be. So the rule is one - ownvalues.py - and this file
// holds no bound of its own: it reads the range from the schema to say it, and a value past it comes back
// refused, in the dialog, before anything is saved.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        /// The item that opens the dialog. It is never a value: nothing a setting stores starts with U+0001.
        internal const string OwnItem = "\u0001own";

        /// A drop-down with Custom...: the setting's schema, its choices, the item it last held and whether its
        /// dialog is open.
        private sealed class OwnPick
        {
            internal Dictionary<string, object> Field;
            internal Dictionary<string, object> Custom;
            internal readonly HashSet<string> Choices = new HashSet<string>();
            internal int Last;
            internal bool Asking;
        }

        /// A duration's units and a count's, as their words are spelled: `m45`, `above_300k`.
        private static double UnitSize(string kind, string unit)
        {
            if (kind == "duration") return unit == "s" ? 1 : unit == "m" ? 60 : unit == "h" ? 3600 : 0;
            return unit == "" ? 1 : unit == "k" ? 1000 : unit == "m" ? 1000000 : 0;
        }

        /// What a value of the person's own measures - seconds, or a count - read from its words as the schema says
        /// they are spelled, or -1. How it is shown, never whether it is allowed: the bridge answers that.
        internal static double OwnAmount(Dictionary<string, object> custom, string value)
        {
            string kind = Str(custom, "kind");
            if (string.IsNullOrEmpty(value) || (kind != "duration" && kind != "count")) return -1;
            string digits = value, unit = "";
            if (kind == "duration")
            {
                unit = value.Substring(0, 1);
                digits = value.Substring(1);
            }
            else
            {
                string prefix = Str(custom, "prefix") ?? "";
                if (!value.StartsWith(prefix, StringComparison.Ordinal)) return -1;
                digits = value.Substring(prefix.Length);
                char last = digits.Length > 0 ? digits[digits.Length - 1] : '0';
                if (last == 'k' || last == 'm')
                {
                    unit = last.ToString();
                    digits = digits.Substring(0, digits.Length - 1);
                }
            }
            double number, size = UnitSize(kind, unit);
            if (size <= 0 || !double.TryParse(digits, NumberStyles.None, CultureInfo.InvariantCulture, out number)) return -1;
            return number * size;
        }

        /// The drop-down's items for a value of the person's own: the one it holds now, when that is none of its
        /// choices, and Custom..., last.
        private void OwnItems(Dictionary<string, object> custom, string value, List<Choice> items)
        {
            bool listed = false;
            foreach (Choice item in items) listed |= item.Value == value;
            if (!listed && !string.IsNullOrEmpty(value)) items.Add(new Choice(value, OwnLabel(custom, value)));
            items.Add(new Choice(OwnItem, S("choice.custom_value", "Custom...")));
        }

        /// Custom... on `combo`: picking it opens the dialog, and the item before it comes back if nothing is taken.
        private void Own(SoftCombo combo, Dictionary<string, object> field, Dictionary<string, object> custom)
        {
            var state = new OwnPick();
            state.Field = field;
            state.Custom = custom;
            foreach (object choice in Items(field, "choices") ?? new List<object>())
                state.Choices.Add(Convert.ToString(choice, CultureInfo.InvariantCulture));
            state.Last = combo.SelectedIndex;
            combo.SelectedIndexChanged += delegate
            {
                var chosen = combo.SelectedItem as Choice;
                if (chosen == null) return;
                if (chosen.Value != OwnItem)
                {
                    state.Last = combo.SelectedIndex;
                    return;
                }
                if (state.Asking || auditing || !IsHandleCreated) return;
                state.Asking = true;
                // After the drop-down has finished taking the item, never inside its own event.
                BeginInvoke((MethodInvoker)delegate { AskOwn(combo, state); });
            };
        }

        private void AskOwn(SoftCombo combo, OwnPick state)
        {
            var held = state.Last >= 0 && state.Last < combo.Items.Count ? combo.Items[state.Last] as Choice : null;
            string taken = null;
            try
            {
                using (Form dialog = BuildOwnValue(state.Field, held == null ? null : held.Value,
                                                   delegate(string value) { taken = value; }))
                    dialog.ShowDialog(this);
            }
            finally
            {
                state.Asking = false;
            }
            if (taken == null)
            {
                if (state.Last >= 0 && state.Last < combo.Items.Count) combo.SelectedIndex = state.Last;
            }
            else
            {
                TakeOwn(combo, state, taken);
            }
            if (combo.CanFocus) combo.Focus();
        }

        /// Shows `value` - the validator's own spelling of it - in `combo`: the choice it is, or the one item of the
        /// person's own before Custom..., in place of the one there was.
        private void TakeOwn(SoftCombo combo, OwnPick state, string value)
        {
            int at = -1, own = -1;
            for (int i = 0; i < combo.Items.Count; i++)
            {
                var item = combo.Items[i] as Choice;
                if (item == null || item.Value == OwnItem) continue;
                if (item.Value == value) at = i;
                else if (!state.Choices.Contains(item.Value)) own = i;
            }
            if (at < 0)
            {
                var item = new Choice(value, OwnLabel(state.Custom, value));
                if (own >= 0)
                {
                    combo.Items[own] = item;
                    at = own;
                }
                else
                {
                    at = Math.Max(0, combo.Items.Count - 1);
                    combo.Items.Insert(at, item);
                }
            }
            combo.SelectedIndex = at;
        }

        /// How long a value of the person's own is, in the words the window's durations are said in - in whole
        /// days where it is some.
        private string OwnDuration(double seconds)
        {
            if (seconds >= 86400 && seconds % 86400 == 0) return S("time.days", "{n}d", "n", (long)(seconds / 86400));
            return Duration(seconds);
        }

        /// An amount of a count, in its words where the schema names them - "{n} MB", written as the choices beside
        /// it are, in plain digits - or as a number grouped the way the interface language groups one, as the choices
        /// of a count of tokens are.
        private string OwnCount(Dictionary<string, object> custom, double amount, string words)
        {
            bool plain = words != null && words == Str(custom, "amount");
            CultureInfo culture = CultureInfo.CurrentCulture;
            try { culture = CultureInfo.GetCultureInfo(InterfaceLocale()); }
            catch (ArgumentException) { }
            string number = ((long)amount).ToString(plain ? "0" : "N0", culture);
            return words == null ? number : S(words, "{n}").Replace("{n}", number);
        }

        /// A value of the person's own as its drop-down item says it.
        internal string OwnLabel(Dictionary<string, object> custom, string value)
        {
            string kind = Str(custom, "kind");
            if (kind == "clock") return value;
            if (kind == "days")
            {
                var names = new List<string>();
                foreach (string day in value.Split(',')) names.Add(S("day." + day, day));
                return string.Join(S("own.days_join", ", "), names.ToArray());
            }
            double amount = OwnAmount(custom, value);
            if (amount < 0) return value;
            if (kind == "duration") return OwnDuration(amount);
            return OwnCount(custom, amount, Str(custom, "label") ?? Str(custom, "amount"));
        }

        /// What the dialog says above its editor: the range, or what a time of day and the days are.
        internal string OwnHint(Dictionary<string, object> custom)
        {
            string kind = Str(custom, "kind");
            if (kind == "clock") return S("own.clock", "A time of day, from 00:00 to 23:59.");
            if (kind == "days") return S("own.days", "Choose at least one day.");
            double low = Number(custom, "min"), high = Number(custom, "max");
            string words = Str(custom, "amount");
            string from = kind == "duration" ? OwnDuration(low) : OwnCount(custom, low, words);
            string to = kind == "duration" ? OwnDuration(high) : OwnCount(custom, high, words);
            return S("own.range", "From {low} to {high}.").Replace("{low}", from).Replace("{high}", to);
        }

        // The dialog's controls, for the layout audit.
        private Control ownEditor;
        private Label ownHint;

        /// The dialog for a value of the person's own, built and not shown: the range above, the editor, and Use this
        /// value and Cancel. `taken` is handed the value as the bridge will store it, once the bridge has taken it.
        private Form BuildOwnValue(Dictionary<string, object> field, string current, Action<string> taken)
        {
            string name = Str(field, "name");
            var custom = Map(field, "custom");
            string kind = Str(custom, "kind");
            string title = Humanise(name ?? "");
            var dialog = new Form();
            dialog.Text = title;
            dialog.Font = Font;
            dialog.BackColor = Canvas;
            dialog.ForeColor = Ink;
            Soft.TitleBar(dialog);
            dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.MinimizeBox = false;
            dialog.MaximizeBox = false;
            dialog.ShowInTaskbar = false;
            dialog.ShowIcon = false;

            int width = Px(440);
            var body = new SoftStack();
            body.Dock = DockStyle.Fill;
            body.ColumnCount = 1;
            body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            body.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            body.Padding = Pad(16, 16, 16, 0);
            body.BackColor = Canvas;
            string hintText = OwnHint(custom);
            var hint = Value(hintText);
            hint.ForeColor = Secondary;
            hint.MaximumSize = new Size(width - Px(32), 0);
            body.Controls.Add(hint);

            Func<string> compose;
            Control editor;
            if (kind == "clock")
            {
                // Two numbers, the hour and the minute, as the panel has them: no box that could hold words.
                int hour = 0, minute = 0;
                string[] parts = (current ?? "").Split(':');
                if (parts.Length != 2 || !int.TryParse(parts[0], NumberStyles.None, CultureInfo.InvariantCulture, out hour) ||
                    !int.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out minute))
                    hour = minute = 0;
                var row = new SoftFlow();
                row.AutoSize = true;
                row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                row.WrapContents = false;
                row.Margin = Pad(0, 8, 0, 4);
                var spins = new List<NumericUpDown>();
                foreach (int part in new[] { hour, minute })
                {
                    var number = new SoftNumber();
                    GiveTextRoom(number.Spin);
                    number.Spin.DecimalPlaces = 0;
                    // Wide enough for any two digits; which are a time of day is the bridge's to say.
                    number.Spin.Minimum = 0;
                    number.Spin.Maximum = 99;
                    number.Spin.Value = Math.Min(99, Math.Max(0, part));
                    number.Spin.AccessibleName = title + " - " + (spins.Count == 0 ? S("own.unit.h", "hours") : S("own.unit.m", "minutes"));
                    number.Margin = new Padding(0);
                    if (spins.Count == 1)
                    {
                        var colon = new Label();
                        colon.Text = ":";
                        colon.AutoSize = true;
                        colon.ForeColor = Ink;
                        // On the fields' centre line, as the Statistics page's label beside its drop-down is.
                        colon.Margin = new Padding(Px(6), Math.Max(0, (SoftCombo.FieldHeight - TextRenderer.MeasureText(":", Font).Height) / 2),
                                                   Px(6), 0);
                        row.Controls.Add(colon);
                    }
                    row.Controls.Add(number);
                    spins.Add(number.Spin);
                }
                compose = delegate
                {
                    return ((int)spins[0].Value).ToString("00", CultureInfo.InvariantCulture) + ":" +
                           ((int)spins[1].Value).ToString("00", CultureInfo.InvariantCulture);
                };
                editor = row;
            }
            else if (kind == "days")
            {
                var flow = new SoftFlow();
                flow.AutoSize = true;
                flow.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                flow.WrapContents = true;
                flow.MaximumSize = new Size(width - Px(32), 0);
                flow.Margin = Pad(0, 8, 0, 4);
                var picked = new HashSet<string>();
                var named = Map(custom, "named");
                List<object> set = current == null ? null : Items(named, current);
                if (set != null) foreach (object day in set) picked.Add(Convert.ToString(day, CultureInfo.InvariantCulture));
                else if (current != null) foreach (string day in current.Split(',')) picked.Add(day);
                var checks = new List<KeyValuePair<string, CheckBox>>();
                // The working days on one line and the weekend on the next, as the choices name them.
                List<object> working = Items(named, "weekdays");
                string lastWorking = working != null && working.Count > 0 ? Convert.ToString(working[working.Count - 1], CultureInfo.InvariantCulture) : null;
                foreach (object entry in Items(custom, "days") ?? new List<object>())
                {
                    string day = Convert.ToString(entry, CultureInfo.InvariantCulture);
                    CheckBox check = NewCheck(S("day." + day, day), picked.Contains(day), true);
                    check.Margin = Pad(0, 3, 12, 3);
                    flow.Controls.Add(check);
                    if (day == lastWorking) flow.SetFlowBreak(check, true);
                    checks.Add(new KeyValuePair<string, CheckBox>(day, check));
                }
                compose = delegate
                {
                    var chosen = new List<string>();
                    foreach (var pair in checks) if (pair.Value.Checked) chosen.Add(pair.Key);
                    return string.Join(",", chosen.ToArray());
                };
                editor = flow;
            }
            else
            {
                var number = new SoftNumber();
                NumericUpDown spin = number.Spin;
                GiveTextRoom(spin);
                spin.DecimalPlaces = 0;
                // Wide enough for any number a person types; the setting's own range is the bridge's to hold.
                spin.Minimum = 0;
                spin.Maximum = 999999999;
                spin.AccessibleName = title;
                spin.ThousandsSeparator = kind == "count";
                number.Width = Px(kind == "count" ? 160 : Brand.NumberWidth);
                number.Margin = Pad(0, 0, 10, 0);
                var units = new List<string>();
                foreach (object unit in Items(custom, "units") ?? new List<object>())
                    units.Add(Convert.ToString(unit, CultureInfo.InvariantCulture));
                double amount = OwnAmount(custom, current);
                if (amount < 0) amount = Number(custom, "min");
                var row = new SoftFlow();
                row.AutoSize = true;
                row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                row.WrapContents = false;
                row.Margin = Pad(0, 8, 0, 4);
                row.Controls.Add(number);
                if (kind == "duration")
                {
                    // The largest unit that says the value exactly, as the settings spell it.
                    string shown = units.Count > 0 ? units[0] : "s";
                    foreach (string unit in units) if (UnitSize(kind, unit) > 0 && amount % UnitSize(kind, unit) == 0) shown = unit;
                    spin.Value = (decimal)Math.Min(999999999, amount / UnitSize(kind, shown));
                    var unitCombo = new SoftCombo();
                    IgnoreWheel(unitCombo);
                    unitCombo.AccessibleName = S("own.unit", "Unit");
                    int widest = 0;
                    foreach (string unit in units)
                    {
                        string fallback = unit == "s" ? "seconds" : unit == "m" ? "minutes" : "hours";
                        var item = new Choice(unit, S("own.unit." + unit, fallback));
                        unitCombo.Items.Add(item);
                        widest = Math.Max(widest, TextRenderer.MeasureText(item.ToString(), Font).Width);
                    }
                    unitCombo.Width = Math.Max(Px(120), widest + Px(Brand.SelectPadLeft + Brand.SelectPadRight + 4));
                    unitCombo.SelectedIndex = Math.Max(0, units.IndexOf(shown));
                    unitCombo.Margin = new Padding(0);
                    row.Controls.Add(unitCombo);
                    compose = delegate
                    {
                        var unit = unitCombo.SelectedItem as Choice;
                        return (unit == null ? "" : unit.Value) + ((long)spin.Value).ToString(CultureInfo.InvariantCulture);
                    };
                }
                else
                {
                    spin.Value = (decimal)Math.Min(999999999, amount);
                    double step = UnitSize(kind, units.Count > 0 ? units[0] : "");
                    spin.Increment = (decimal)Math.Max(1, step);
                    string prefix = Str(custom, "prefix") ?? "";
                    compose = delegate { return prefix + ((long)spin.Value).ToString(CultureInfo.InvariantCulture); };
                }
                editor = row;
            }
            body.Controls.Add(editor);
            ownEditor = editor;
            ownHint = hint;
            dialog.Controls.Add(body);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(0, 12, 16, 16);
            Button use = null;
            use = MakeButton(S("own.use", "Use this value"), true, delegate
            {
                string value = compose();
                string argument = "{\"name\":" + Json.Escape(name) + ",\"value\":" + Json.Escape(value) + "}";
                use.Enabled = false;
                CallAsync("check-setting", argument, delegate(Dictionary<string, object> reply)
                {
                    if (dialog.IsDisposed) return;
                    use.Enabled = true;
                    string stored = Ok(reply) ? Str(Map(reply, "result"), "value") : null;
                    if (stored != null)
                    {
                        taken(stored);
                        dialog.Close();
                        return;
                    }
                    // Refused by the settings' own rule: said with the range, in the dialog, and nothing changes.
                    hint.Text = S("own.refused", "This value can't be used. {hint}", "hint", hintText);
                    hint.ForeColor = Palette.Danger;
                });
            });
            Button cancel = MakeButton(S("action.cancel", "Cancel"), false, delegate { dialog.Close(); });
            buttons.Controls.Add(use);
            buttons.Controls.Add(cancel);
            dialog.Controls.Add(buttons);
            dialog.AcceptButton = use;
            dialog.CancelButton = cancel;
            dialog.ActiveControl = editor is SoftFlow && ((SoftFlow)editor).Controls.Count > 0
                                   ? ((SoftFlow)editor).Controls[0] : editor;
            if (kind != "days") dialog.ActiveControl = ((SoftNumber)((SoftFlow)editor).Controls[0]).Spin;

            // As tall as the refusal needs, which says the range too: the dialog never grows under a person's hand.
            hint.Text = S("own.refused", "This value can't be used. {hint}", "hint", hintText);
            int tall = body.GetPreferredSize(new Size(width, 0)).Height;
            hint.Text = hintText;
            dialog.ClientSize = new Size(width, tall + buttons.GetPreferredSize(new Size(width, 0)).Height);
            return dialog;
        }

        /// The dialog of each kind a value of the person's own comes in, built from `schema` at its opening size and never
        /// shown: nothing in it may be cut off, and every control in it has a name a screen reader says (v0.6.11).
        private void AuditOwnValues(List<object> schema, List<string> findings)
        {
            var seen = new HashSet<string>();
            foreach (object entry in schema ?? new List<object>())
            {
                var field = entry as Dictionary<string, object>;
                var custom = Map(field, "custom");
                if (custom == null) continue;
                var units = Items(custom, "units");
                string sort = Str(custom, "kind") + "/" + (units == null ? 0 : units.Count) + "/" + (Str(custom, "amount") ?? Str(custom, "label"));
                if (!seen.Add(sort)) continue;
                var choices = Items(field, "choices");
                string current = choices != null && choices.Count > 0 ? Convert.ToString(choices[choices.Count - 1], CultureInfo.InvariantCulture) : null;
                using (Form dialog = BuildOwnValue(field, current, delegate(string value) { }))
                {
                    dialog.TopLevel = false;
                    string where = "custom value " + Str(field, "name");
                    Materialise(dialog);
                    dialog.PerformLayout();
                    Walk(dialog, where, findings);
                    // And with the refusal said above it, the longest the line gets.
                    ownHint.Text = S("own.refused", "This value can't be used. {hint}", "hint", OwnHint(custom));
                    dialog.PerformLayout();
                    int needs = dialog.Controls[0].GetPreferredSize(new Size(dialog.ClientSize.Width, 0)).Height;
                    int room = dialog.ClientSize.Height - dialog.Controls[1].Height;
                    if (needs > room) findings.Add(where + " :: the refusal needs " + needs + " high, the dialog gives " + room);
                    AuditSpoken(where, dialog, findings);
                }
            }
        }
    }
}

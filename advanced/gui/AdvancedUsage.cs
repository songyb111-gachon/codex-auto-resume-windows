// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Advanced features page's near-the-limit choices (v0.6.16-beta.4, the owner's additions to
// issue #29).
//
// Wrap up near a limit's words as they would be sent: under its drop-downs, for each window, the exact words the wrap-up
// would send now - its wording, numbers, reset time and Custom words as they stand, in the continuation language - as
// the continuation styles show theirs (the bridge makes them: advanced-wordings' `previews`).
//
// Wrap up near a limit's Custom wording: while its Wording is Custom, its Choices card has, under the drop-downs, one
// box for each window - the five-hour and the weekly - with the person's own words (advanced-wordings, read when the
// capability opens), a line saying which numbers the words may hold, and Save words under each (advanced-wording, with
// the generation the page read). A refusal says why, in the page's words for each of the custom text's checks. The words
// are the person's own and are never written anywhere but the advanced state.
//
// Every number with Custom... (item (f), "이런 수치들은 직접 입력도 가능해야 한다니까"): a choice the bridge says takes a number
// of one's own (its `custom` range) has Custom... last in its drop-down, and a number already taken shown there as itself,
// one item before Custom.... Custom... opens the small dialog the Settings page's Custom... has opened since v0.6.11
// (SettingsOwn.cs OwnDialog; v0.6.16 final, the owner's "예전에 직접입력 누를 시 하던 방식대로"): the range said above a
// number, in the unit the choices are said in, Use this value and Cancel. A number outside the range is refused in the
// dialog, with the range, and nothing is sent; Cancel puts the drop-down back on the item it held; a number taken shows
// in the drop-down - as one item before Custom..., or as the preset it is - and is sent as a choice is, the bridge's
// refusal said as the page says any.
//
// Both windows off (v0.6.16 final): a capability with a pair of window switches - the meter, the wrap-up, the stop - and
// both of them off says, under them, that it acts on neither.
//
// Nothing here draws anything the page does not draw already: the captions, help lines, boxes and buttons are the
// Settings page's.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // Wrap up near a limit (registry.USAGE_WRAP_UP), whose Choices card holds its Custom wording.
        private const string WrapUpId = "usage_wrap_up";
        private const int CustomWording = 5;
        // The two windows' wording keys (vocabulary.WordingKey), in the order the boxes are shown.
        private static readonly string[] WordingKeys = { "wrap_custom_five_hour", "wrap_custom_weekly" };

        // advanced-wordings' last answer, or null where it was not read or the read failed.
        private Dictionary<string, object> advancedWordings;
        // Each window's box and its Save words, as the card was built.
        private readonly Dictionary<string, SoftTextArea> wordingBoxes = new Dictionary<string, SoftTextArea>();
        private readonly Dictionary<string, Button> wordingSaves = new Dictionary<string, Button>();
        // The windows' lengths in minutes, as advanced-wordings' previews are keyed, and each one's line on the card.
        private static readonly string[] PreviewWindows = { "300", "10080" };
        private readonly List<Label> previewLines = new List<Label>();

        // (f): the drop-downs' last item, Custom..., and each customizable drop-down by its key: its capability, its label,
        // its range, its presets, the item it held before Custom... was chosen, and whether its dialog is open.
        private const string CustomChoice = "custom";
        private sealed class CustomPick
        {
            internal string Id, Key, Label;
            internal int[] Range;
            internal readonly HashSet<string> Presets = new HashSet<string>();
            internal int Last = -1;
            internal bool Asking;
        }
        private readonly Dictionary<string, CustomPick> customPicks = new Dictionary<string, CustomPick>();
        // Null in every window a person opens. In a window AdvancedPageRun drives: what answers the dialog, never shown.
        private Action<Form> customAnswer;

        private void ForgetCustomEntries()
        {
            customPicks.Clear();
        }

        /// A choice's custom range, [lowest, highest], or null where it takes only its presets.
        private static int[] CustomRange(Dictionary<string, object> option)
        {
            List<object> range = Items(option, "custom");
            if (range == null || range.Count != 2) return null;
            return new[] { Whole(range[0]), Whole(range[1]) };
        }

        /// A customizable choice's drop-down kept with its range, and the item it holds followed, so that Custom... can
        /// put it back.
        private void WatchCustom(string id, string key, string label, int[] range, List<object> presets, SoftCombo combo)
        {
            if (range == null) return;
            var pick = new CustomPick();
            pick.Id = id;
            pick.Key = key;
            pick.Label = label;
            pick.Range = range;
            foreach (object preset in presets ?? new List<object>())
                pick.Presets.Add(Whole(preset).ToString(CultureInfo.InvariantCulture));
            pick.Last = combo.SelectedIndex;
            combo.SelectedIndexChanged += delegate
            {
                var chosen = combo.SelectedItem as Choice;
                if (chosen != null && chosen.Value != CustomChoice) pick.Last = combo.SelectedIndex;
            };
            customPicks[key] = pick;
        }

        /// Custom... chosen: its dialog, once the drop-down has finished taking the item - never inside its own event.
        private void OpenCustom(string key, SoftCombo combo)
        {
            CustomPick pick;
            if (!customPicks.TryGetValue(key, out pick) || pick.Asking) return;
            pick.Asking = true;
            if (advancedScript != null) AskCustom(combo, pick);
            else if (auditing || !IsHandleCreated) HoldCustom(combo, pick);
            else BeginInvoke((MethodInvoker)delegate { AskCustom(combo, pick); });
        }

        /// The dialog for a number of one's own, as the Settings page's Custom... asks for one: Cancel - or a number
        /// refused, then the dialog closed - puts back the item the drop-down held; a number taken is shown and sent.
        private void AskCustom(SoftCombo combo, CustomPick pick)
        {
            string taken = null;
            try
            {
                if (combo.IsDisposed || busy > 0 || advancedListing == null) return;
                var held = pick.Last >= 0 && pick.Last < combo.Items.Count ? combo.Items[pick.Last] as Choice : null;
                using (Form dialog = BuildCustomValue(pick, held == null ? null : held.Value, delegate(string value) { taken = value; }))
                {
                    if (customAnswer != null) customAnswer(dialog);
                    else dialog.ShowDialog(this);
                }
            }
            finally
            {
                if (taken == null) HoldCustom(combo, pick);
                pick.Asking = false;
            }
            if (taken == null) return;
            if (!combo.IsDisposed) TakeCustom(combo, pick, taken);
            SetAdvancedOptionValue(pick.Id, pick.Key, taken);
            if (!combo.IsDisposed && combo.CanFocus) combo.Focus();
        }

        /// The drop-down back on the item it held before Custom... was chosen.
        private void HoldCustom(SoftCombo combo, CustomPick pick)
        {
            pick.Asking = false;
            if (!combo.IsDisposed && pick.Last >= 0 && pick.Last < combo.Items.Count) combo.SelectedIndex = pick.Last;
        }

        /// The Settings page's dialog for a value of one's own (OwnDialog), for a whole number in the choice's range: titled
        /// with the choice's label, the range said in the unit its choices are said in; a number outside it is refused
        /// there, before anything is sent.
        private Form BuildCustomValue(CustomPick pick, string current, Action<string> taken)
        {
            int[] range = pick.Range;
            var custom = new Dictionary<string, object>();
            // v0.6.20: a time of day of one's own (window_anchor) is asked for in the Settings page's clock, as HH:MM.
            if (IsAnchorTime(pick.Key))
            {
                custom["kind"] = "clock";
                return OwnDialog(pick.Label, custom, CustomHint(pick), AnchorClock(current) ?? "07:00",
                                 delegate(string value, Action<string> answer) { answer(AnchorValue(value)); }, taken);
            }
            custom["kind"] = "number";
            custom["min"] = (double)range[0];
            custom["max"] = (double)range[1];
            return OwnDialog(pick.Label, custom, CustomHint(pick), current, delegate(string value, Action<string> answer)
            {
                int typed;
                answer(int.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out typed) &&
                       typed >= range[0] && typed <= range[1] ? typed.ToString(CultureInfo.InvariantCulture) : null);
            }, taken);
        }

        /// What the dialog says above its number: the Settings page's own range words, with the ends said as the choices
        /// say theirs ("1 min", "100%").
        private string CustomHint(CustomPick pick)
        {
            if (IsAnchorTime(pick.Key))
                return S("own.range", "From {low} to {high}.").Replace("{low}", AnchorTimeText(AnchorShift))
                                                            .Replace("{high}", AnchorTimeText(1439 + AnchorShift));
            return S("own.range", "From {low} to {high}.").Replace("{low}", OptionText(pick.Key, pick.Range[0]))
                                                        .Replace("{high}", OptionText(pick.Key, pick.Range[1]));
        }

        /// Shows `value` in `combo`: the preset it is, or the one item of one's own before Custom..., in place of the one
        /// there was.
        private void TakeCustom(SoftCombo combo, CustomPick pick, string value)
        {
            int at = -1, own = -1;
            for (int i = 0; i < combo.Items.Count; i++)
            {
                var item = combo.Items[i] as Choice;
                if (item == null || item.Value == CustomChoice) continue;
                if (item.Value == value) at = i;
                else if (!pick.Presets.Contains(item.Value)) own = i;
            }
            if (at < 0)
            {
                var item = new Choice(value, OptionText(pick.Key, int.Parse(value, NumberStyles.None, CultureInfo.InvariantCulture)));
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

        /// Each customizable choice's dialog on the open capability, built and never shown, held to the Settings page's
        /// checks of its own (AuditOwnDialog): nothing cut off, the refusal given room, every control named - once for
        /// each range and unit `seen` has not met.
        private void AuditCustomValues(string where, HashSet<string> seen, List<string> findings)
        {
            foreach (CustomPick pick in customPicks.Values)
            {
                if (!seen.Add(CustomHint(pick))) continue;
                using (Form dialog = BuildCustomValue(pick, null, delegate(string value) { }))
                    AuditOwnDialog(dialog, where + "/custom value " + pick.Key, CustomHint(pick), findings);
            }
        }

        /// The wrap-up's wordings read, then `after`.
        private void ReadWordings(MethodInvoker after)
        {
            AdvancedCall("advanced-wordings", "{\"capability\":" + Json.Escape(WrapUpId) + "}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedWordings = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                after();
            });
        }

        /// What the wrap-up's wording boxes are built from, for ShowAdvancedDetail to compare.
        private string WordingsShown(Dictionary<string, object> item)
        {
            return Str(item, "id") == WrapUpId ? AdvancedWritten(advancedWordings) : "";
        }

        /// Under the wrap-up's drop-downs, while its Wording is Custom: a box for each window with the person's words and
        /// Save words under it.
        private void BuildWordings(string id, List<object> options, TableLayoutPanel card)
        {
            wordingBoxes.Clear();
            wordingSaves.Clear();
            previewLines.Clear();
            if (id != WrapUpId || advancedWordings == null) return;
            // (a) What is sent, exactly, for each window - whatever the wording.
            Dictionary<string, object> previews = Map(advancedWordings, "previews");
            card.Controls.Add(Caption(Word("page.preview.title", "What is sent")));
            foreach (string minutes in PreviewWindows)
            {
                string words = Str(previews, minutes);
                if (words == null) continue;
                Label line = HelpText(Word("page.preview." + minutes, minutes) + Environment.NewLine + words);
                line.ForeColor = Ink;
                line.Margin = Pad(0, 2, 0, 6);
                card.Controls.Add(line);
                previewLines.Add(line);
            }
            if (OptionValue(options, "wrap_style") != CustomWording) return;
            Dictionary<string, object> held = Map(advancedWordings, "wordings");
            int most = Math.Max(1, Whole(Get(advancedWordings, "limit")));
            card.Controls.Add(HelpText(Word("page.wording.help", "Your words may hold {percent}, {window}, {stop_at} and {reset}, each filled in when they are sent, and nothing else in braces. A window with no words of its own is sent the standard wording.")));
            foreach (string key in WordingKeys)
            {
                string caption = Word("page.wording." + key, key);
                var box = new SoftTextArea();
                box.Font = Font;
                box.Box.Font = Font;
                box.Box.MaxLength = most;
                box.Box.AccessibleName = caption;
                box.Height = Px(72);
                box.Dock = DockStyle.Fill;
                box.Margin = Pad(0, 4, 0, 2);
                string draft;
                box.Box.Text = resetDrafts.TryGetValue("wording." + key, out draft) ? draft : (Str(held, key) ?? "");
                string draftKey = "wording." + key;
                SoftTextArea typed = box;
                box.Box.TextChanged += delegate { resetDrafts[draftKey] = typed.Box.Text; };
                card.Controls.Add(Caption(caption));
                card.Controls.Add(box);
                string chosen = key;
                Button save = CardButton(card, Word("page.wording.save", "Save words"), delegate { SaveWording(chosen); });
                save.AccessibleName = Word("page.wording.save", "Save words") + " " + caption;
                wordingBoxes[key] = box;
                wordingSaves[key] = save;
            }
        }

        /// Under the switches of a capability that has a pair for the windows (v0.6.16 final: the usage meter, Wrap up near
        /// a limit and Stop near a limit, each its own), where both are off: a line saying it acts on neither - on, and
        /// doing nothing for either window.
        private void BuildNoWindowNote(List<object> options, TableLayoutPanel card)
        {
            if (OptionValue(options, "window_five_hour") != SwitchOff || OptionValue(options, "window_weekly") != SwitchOff) return;
            card.Controls.Add(HelpText(Word("page.option.no_window", "Both windows are switched off, so this feature acts on neither of them.")));
        }

        /// A choice's value as the list says it is now, or 0.
        private static int OptionValue(List<object> options, string key)
        {
            foreach (object entry in options ?? new List<object>())
            {
                var option = entry as Dictionary<string, object>;
                if (Str(option, "key") == key) return Whole(Get(option, "value"));
            }
            return 0;
        }

        /// One window's words saved as typed - or, where the box is blank, taken away, so that window is sent the standard
        /// wording - against the generation the page read.
        private void SaveWording(string key)
        {
            SoftTextArea box;
            if (busy > 0 || advancedListing == null || !wordingBoxes.TryGetValue(key, out box)) return;
            string text = box.Box.Text;
            string words = text.Trim().Length == 0 ? "null" : Json.Escape(text);
            string argument = "{\"capability\":" + Json.Escape(WrapUpId) + ",\"key\":" + Json.Escape(key) + ",\"words\":" + words +
                              ",\"generation\":" + AdvancedGeneration() + "}";
            string name = AdvancedName(WrapUpId);
            AdvancedCall("advanced-wording", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                {
                    resetDrafts.Remove("wording." + key);
                    SetNote(advancedNote, Word("page.done.wording", "{name} uses these words from now on.", "name", name));
                }
                advancedShown = null;
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(WordingRefusal(result));
            });
        }

        /// A refused wording in words: which of the custom text's checks it failed, or as the page says any refusal.
        private string WordingRefusal(Dictionary<string, object> result)
        {
            string problem = Str(result, "problem");
            if (Str(result, "refusal") == "wording_invalid" && problem != null)
                return Word("page.refused.wording." + problem, Word("page.refused.other", "That request was refused. Nothing was changed."));
            return KeptRefusal(Str(result, "refusal"));
        }

        /// What Save words may do now: nothing while another action is under way.
        private void UpdateWordingButtons(bool idle)
        {
            foreach (Button save in wordingSaves.Values) save.Enabled = idle && advancedListing != null;
        }
    }
}

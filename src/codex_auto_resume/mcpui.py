"""The settings panel Codex renders inside the conversation.

One self-contained page: no network, no CDN, no framework, no fonts to fetch. A widget
that reaches for a script it cannot load is a blank rectangle, and this one has to work
on a machine whose whole point is that its network just failed.

It renders from the schema the tool returns rather than from a hardcoded list of
fields, so it shows exactly what the settings module defines - the same source the
standalone window and the command line render from.

The host API is feature-detected. Different hosts expose the widget bridge under
different names, and a version that assumed one of them would silently show a panel
whose Save button does nothing. When no bridge is found the page says so plainly and
falls back to being a readable summary, which is still worth showing.

v0.6.3 gave it the same visual language as the Dashboard and the notification-area popup
- soft cards on a warm canvas, a state that breathes while it is being watched - and the
continuation settings. Two things about those are structural rather than stylistic:

* **Custom message text is shown, never edited.** Whatever it says is later sent into the
  user's conversations when nobody is watching, so it is written in the Windows Dashboard
  and nowhere else. This page has no text field for it, and neither the Save request nor
  the Preview request can carry it - `editable()` and `previewArguments()` are the two
  gates, and the tests run both.
* **The Preview is the watcher's own text.** It asks `preview_recovery_message`, which
  builds the message with the function the watcher sends with. The page never assembles a
  continuation of its own.

v0.6.4 added the Theme setting, which the panel applies to itself - Light or Dark stamp
`data-theme` on the root, Use system setting stamps nothing and follows Codex - and it
speaks a newly saved Interface language at once, from every language's words for this page,
which ship with it. An on/off setting is a switch when it turns something that runs on or
off and a check box when it picks items of a list, as in the Windows Dashboard. A switch or a
button at the right of a row is pinned to the row's bottom-right, beside the last line of the
text it belongs to, as it is in the window and the notification-area popup.

v0.6.5 made the last native piece its own. A select opened the browser's list - square, flat,
system blue, a box from no card here - so every choice now opens the list the Windows Dashboard
opens: a raised card in the cards' material with pill items, which is a WAI-ARIA combobox over the
select, keys and screen readers included. The select stays underneath as the value, never shown.
And controls move when they change, on brand's one time and one curve: a switch's knob glides and
its track cross-fades, a check box fades its fill and mark, a list rises into place - none of it
with less motion or in High Contrast, and a switch that asks first moves once it is answered.
"""
from __future__ import annotations

import json
import re

from . import brand, interface, l10n

# The page is delivered as one resource, so the style lives in it. Every colour comes
# from the shared palette, which is what keeps this panel, the settings window and the
# icon the same product rather than three that happen to ship together.
_STYLE = r"""
/* Three states, not two. An explicit choice - the Theme setting's Light or Dark - stamps
   `data-theme` on the root; Use system setting stamps nothing and only the media query,
   which is Codex's own scheme, separates light from dark. The stamp goes on the root and
   nowhere else: the `--check-*` aliases are resolved where they are declared, which is here.
   A colour whose only definition lives inside the media block is the classic unreadable
   panel, so every token is declared here first and only redefined below. */
:root {
  color-scheme: light dark;
  @LIGHT@
  @ELEVATION_LIGHT@
  @SCALE@
  /* The glow's easing: a half-cosine, to within 0.002 of its phase, so a breath the stylesheet
     draws is the same curve brand.glow() gives the window and the popup. */
  --glow-ease: cubic-bezier(.37, 0, .63, 1);
  /* Every transition on the page takes brand's time and brand's one curve, --transition and
     --transition-ease (MOTION, in the scale above): an ease-out, so a switch's knob, a check box's
     mark and a list that opens leave at once and settle softly, as they do in the window and the
     popup. */
  --font: system-ui, "Segoe UI Variable Text", "Segoe UI", "Malgun Gothic", "Yu Gothic UI",
          "Microsoft YaHei UI", "Microsoft JhengHei UI", sans-serif;
  --mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { color-scheme: dark; @DARK@ @ELEVATION_DARK@ }
}
:root[data-theme="dark"] { color-scheme: dark; @DARK@ @ELEVATION_DARK@ }
:root[data-theme="light"] { color-scheme: light; @LIGHT@ @ELEVATION_LIGHT@ }

* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; padding: var(--size-page-pad); background: var(--canvas); color: var(--ink);
       font: var(--type-body)/var(--lh-body) var(--font); -webkit-font-smoothing: antialiased; }
h1, h2, h3, p, ul { margin: 0; }
button, select, input { font: inherit; }
.page { max-width: 820px; margin: 0 auto; display: grid; gap: var(--size-page-gap); }
.help, .note { color: var(--muted); font-size: var(--type-small); line-height: var(--lh-small); }
.note:empty { display: none; }
.mono { font-family: var(--mono); font-size: var(--type-mono); }

/* The card is one object, repeated: one ground, one hairline, one radius, one soft lift.
   The hairline stays even where the shadow does the visible work - a shadow alone is not
   an edge for everybody, and nothing here may depend on seeing one. */
.card { background: var(--surface); border: 1px solid var(--line);
        border-radius: var(--radius-card); box-shadow: var(--elev-card);
        padding: var(--size-card-pad); min-width: 0; }
@supports (color: color-mix(in srgb, red 50%, blue)) {
  .card { background: var(--card-ground); }
}
.card h2 { font-size: var(--type-title); line-height: var(--lh-title); font-weight: 600; }
.card-head { display: flex; align-items: center; justify-content: space-between;
             gap: var(--size-card-head-gap); }
.count { min-width: var(--size-count-min-width); padding: 0 var(--size-count-pad-x); border-radius: 999px;
         background: var(--inset); color: var(--muted); font-size: var(--type-small);
         line-height: var(--size-count-height); text-align: center;
         font-variant-numeric: tabular-nums; }

/* State leads. Whether anything is being watched is the reason the panel gets opened,
   so it is the first thing on it and the largest type on it - a word, never a colour
   alone, with the halo saying the same thing for a reader who glances. */
.hero { display: grid; gap: var(--size-hero-gap); padding: var(--size-hero-pad); }
.eyebrow { font-size: var(--type-small); color: var(--muted); }
.hero-state { display: flex; align-items: center; gap: 18px; padding: 8px 0 4px 9px; }
.hero h1 { font-size: var(--type-display); line-height: var(--lh-display); font-weight: 600;
           letter-spacing: -.01em; }
.facts { display: flex; flex-wrap: wrap; color: var(--muted); }
.facts span:not(:last-child)::after { content: "\00b7"; padding: 0 8px; }
.hero-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.hero-actions > * { margin-top: 6px; }

/* The status light: a flat dot, and a glow that says it is alive. The dot is the brand's
   `active` cyan whenever the watcher runs with recovery on, whatever it is doing; the word
   beside it and the motion tell those states apart. A light that is off - stopped, not known
   to be running, or paused - keeps the grey it always had and has no glow at all, and amber is
   for a watcher that runs and is not well.

   The glow is a falloff, never a disc with an edge, and its numbers are brand's GLOW, the
   ones the window and the notification-area popup draw with. Monitoring breathes slowly and
   low; recovering a little quicker and brighter; waiting holds still; a problem pulses once,
   when it is first shown, and then holds - nothing here blinks for attention it already has. */
.halo { --halo-color: var(--idle); position: relative; flex: none; width: 12px; height: 12px;
        border-radius: 50%; background: var(--halo-color); }
.halo::before { content: none; position: absolute; inset: calc(-1 * var(--glow-reach));
                border-radius: 50%; pointer-events: none; opacity: var(--glow-still);
                background: radial-gradient(circle closest-side,
                  var(--halo-color) var(--glow-edge),
                  color-mix(in srgb, var(--halo-color) var(--glow-near-mix), transparent) var(--glow-near),
                  color-mix(in srgb, var(--halo-color) var(--glow-far-mix), transparent) var(--glow-far),
                  transparent var(--glow-outer)); }
.halo.monitoring, .halo.waiting, .halo.checking, .halo.recovering { --halo-color: var(--active); }
.halo.attention { --halo-color: var(--attention); }
.halo.paused { --halo-color: var(--paused); }
.halo.monitoring::before, .halo.waiting::before, .halo.checking::before, .halo.recovering::before,
.halo.attention::before { content: ""; }
.halo.monitoring::before { opacity: var(--glow-monitoring-rest);
                           animation: glow-monitoring var(--glow-monitoring-ms) var(--glow-ease) infinite; }
.halo.recovering::before { opacity: var(--glow-recovering-rest);
                           animation: glow-recovering var(--glow-recovering-ms) var(--glow-ease) infinite; }
.halo.attention.once::before { animation: glow-attention var(--glow-attention-ms) var(--glow-ease) 1; }
@keyframes glow-monitoring {
  0%, 100% { opacity: var(--glow-monitoring-low); transform: scale(var(--glow-monitoring-scale-low)); }
  50% { opacity: var(--glow-monitoring-high); transform: scale(var(--glow-monitoring-scale-high)); }
}
@keyframes glow-recovering {
  0%, 100% { opacity: var(--glow-recovering-low); transform: scale(var(--glow-recovering-scale-low)); }
  50% { opacity: var(--glow-recovering-high); transform: scale(var(--glow-recovering-scale-high)); }
}
@keyframes glow-attention {
  0%, 100% { opacity: var(--glow-still); }
  50% { opacity: var(--glow-attention-peak); }
}

/* Controls rest on the card; values sit in wells. */
button { min-height: var(--size-button-height); padding: var(--size-button-pad);
         border-radius: var(--radius-control);
         border: 1px solid var(--line); background: var(--raised); color: var(--ink);
         box-shadow: var(--elev-control); font-weight: 500; line-height: 20px; cursor: pointer;
         transition: background-color var(--transition), border-color var(--transition),
                     box-shadow var(--transition), color var(--transition);
         transition-timing-function: var(--transition-ease); }
button:hover:not([disabled]) { background: var(--surface); }
button:active:not([disabled]) { background: var(--inset); box-shadow: var(--elev-inset); }
button.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
button.primary:hover:not([disabled]) { background: var(--accent-hover); border-color: var(--accent-hover); }
/* After hover, which it would otherwise lose to: a pressed primary stays primary. Without it a
   key press, which is active without hover, fell through to `inset` under white text. */
button.primary:active:not([disabled]) { background: var(--accent-pressed); border-color: var(--accent-pressed);
                                        box-shadow: var(--elev-inset); }
button.danger { color: var(--danger); }
/* Disabled is said by the text and the lost lift, not by fading the whole control: at half
   opacity the label fell to about 3.3:1. `muted` on the card's ground stays above 4.5. */
button[disabled] { background: var(--surface); border-color: var(--line); color: var(--muted);
                   box-shadow: none; cursor: default; }
:focus { outline: none; }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }

.combo-box, input[type=number] { min-height: var(--size-field-height); padding: 6px 12px; color: var(--ink);
        background-color: var(--inset); border: 1px solid var(--line);
        border-radius: var(--radius-control); box-shadow: var(--elev-inset);
        transition: border-color var(--transition), box-shadow var(--transition);
        transition-timing-function: var(--transition-ease); }
input[type=number] { width: var(--size-number-width); text-align: right; font-variant-numeric: tabular-nums; }
/* Opacity 1 is said, not left out: the browser's own stylesheet fades a disabled field to 0.7,
   and muted text at 0.7 fell to about 3:1 in light. */
.combo-box[aria-disabled="true"], input[type=number]:disabled { background-color: var(--surface); box-shadow: none;
                                               color: var(--muted); cursor: default; opacity: 1; }

/* A drop-down is the page's own, never the browser's: the list a native select opens is a
   square, flat, system-blue box that belongs to no card here, so every choice opens the list the
   Windows Dashboard opens (SoftDropList) - the same list, by the same numbers, on this page's type.
   The select stays in the page, hidden, as the value the rest of the page reads and the `change`
   it listens to; the combobox beside it is what is seen, focused and read out.

   The field is the well a value sits in, with brand's wedge on the right. The list is a card: the
   card's ground, hairline, radius and lift, the soft shadow spilling outside it (in dark, its light
   top edge), SPACING xs under the field - over it where there is no room below. It starts a pad
   (SPACING s) left of the field and is at least a pad wider on each side, so each item's pill starts
   where the field does and its words start under the field's; it is wider only where its words need
   it, and never wider than the page.

   Its items are pills a pad in from the card's edge and SPACING xs apart, each the field's line with
   a pad above and below, set as the field is set, words the field's padding in, RADII small. The
   current value is sunken, in the accent; under the pointer an item rises, the control's lift - not
   the current one, which stays sunken, and not while the keyboard leads; the item the keyboard is on
   carries the focus ring every control has, in the room kept around the items for it. The field
   gives its own ring up while its list is open, so the ring is where the keyboard is.

   It shows twelve rows whole - every list here has fewer, so none scrolls - and a longer list, or one
   cut to the room there is, scrolls inside the card's padding and not at its edge, a whole row at a
   time, on the window's soft bar. It rises a few pixels into place as it fades in, and closes at once. */
.combo { position: relative; display: block; width: 100%; min-width: 0;
         --combo-line: 20px; --combo-words: @SELECT_PAD_LEFT@;
         --combo-pill: calc(var(--combo-line) + 2 * var(--space-s)); }
.combo-box { position: relative; display: flex; align-items: center; width: 100%; min-width: 0;
             padding: var(--size-select-pad); line-height: var(--combo-line); cursor: pointer; }
.combo-box[aria-expanded="true"] { outline: none; }
.combo-value { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.combo-box::after { content: ""; position: absolute; right: var(--size-chevron-right);
                    top: calc(55% - var(--size-chevron-height) * .55);
                    width: var(--size-chevron-width); height: var(--size-chevron-height);
                    background: var(--muted); clip-path: polygon(0 0, 100% 0, 50% 100%); pointer-events: none; }
.combo-list { position: absolute; z-index: 3; top: calc(100% + var(--space-xs)); left: calc(-1 * var(--space-s));
              width: max-content; min-width: calc(100% + 2 * var(--space-s));
              padding: calc(var(--space-s) - var(--space-xs) - var(--size-hairline));
              background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-card);
              box-shadow: var(--elev-card);
              animation: combo-rise var(--transition) var(--transition-ease); }
@supports (color: color-mix(in srgb, red 50%, blue)) {
  .combo-list { background: var(--card-ground); }
}
.combo-list.up { top: auto; bottom: calc(100% + var(--space-xs)); }
@keyframes combo-rise {
  from { opacity: 0; transform: translateY(var(--space-xs)); }
}
/* What scrolls, inside the card's padding: SPACING xs of room around the items for the ring, which
   with the card's hairline and padding is the window's pad. */
.combo-scroll { position: relative; display: grid; gap: var(--space-xs); padding: var(--space-xs);
                max-height: calc(2 * var(--space-xs) + 12 * var(--combo-pill) + 11 * var(--space-xs));
                overflow-y: auto; overscroll-behavior: contain;
                scroll-snap-type: y mandatory; scroll-padding: var(--space-xs) 0; }
.combo-option { display: block; min-width: 0; padding: calc(var(--space-s) - var(--size-hairline)) var(--combo-words);
                border-radius: var(--radius-small); border: 1px solid transparent; color: var(--ink);
                line-height: var(--combo-line); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                scroll-snap-align: start; cursor: pointer;
                transition: background-color var(--transition), box-shadow var(--transition),
                            color var(--transition), border-color var(--transition);
                transition-timing-function: var(--transition-ease); }
.combo-list:not(.keys) .combo-option:not([aria-selected="true"]):hover { background: var(--raised);
                border-color: var(--line); box-shadow: var(--elev-control); }
.combo-option[aria-selected="true"] { background: var(--inset); border-color: var(--line);
                                      box-shadow: var(--elev-inset); color: var(--accent); }
.combo-list.keys .combo-option.active { outline: 2px solid var(--focus); outline-offset: 2px; }
/* The soft bar a long list scrolls on, the window's SoftBar: a well 12 across, a pad from the card's
   top and bottom and SPACING xs from its right, and in it a raised pill 2 inside the well, never
   shorter than 32. */
.combo-scroll::-webkit-scrollbar { width: var(--space-m); }
.combo-scroll::-webkit-scrollbar-track { margin: var(--space-xs) 0; background: var(--inset);
                                         border: 1px solid var(--line); border-radius: 999px; }
.combo-scroll::-webkit-scrollbar-thumb { min-height: var(--space-xxl); background: var(--raised);
                                         background-clip: padding-box; border: 2px solid transparent;
                                         border-radius: 999px; box-shadow: inset 0 0 0 1px var(--line); }
.combo-scroll::-webkit-scrollbar-thumb:hover { box-shadow: inset 0 0 0 1px var(--muted); }
@supports not selector(::-webkit-scrollbar) {
  .combo-scroll { scrollbar-width: thin; scrollbar-color: var(--line) var(--inset); }
}

/* A switch glides: the knob slides end to end and settles, and the track cross-fades from the
   grey well to the accent and back - brand's time on brand's curve, and nothing but paint. A check box fades its fill and its mark in the same time. With less motion or in
   High Contrast the change is immediate (see the two blocks at the end). */
input.switch { appearance: none; -webkit-appearance: none; position: relative; flex: none;
               width: var(--size-switch-width); height: var(--size-switch-height); margin: 0;
               border-radius: 999px; cursor: pointer;
               background: var(--inset); border: 1px solid var(--line); box-shadow: var(--elev-inset);
               transition: background-color var(--transition), border-color var(--transition),
                           box-shadow var(--transition);
               transition-timing-function: var(--transition-ease); }
input.switch::before { content: ""; position: absolute; top: calc(var(--size-knob-inset) - var(--size-hairline));
                       left: calc(var(--size-knob-inset) - var(--size-hairline)); width: var(--size-knob);
                       height: var(--size-knob); border-radius: 50%; background: var(--muted);
                       transition: transform var(--transition), background-color var(--transition);
                       transition-timing-function: var(--transition-ease); }
input.switch:checked { background: var(--accent); border-color: var(--accent); box-shadow: none; }
input.switch:checked::before { transform: translateX(var(--size-knob-travel)); background: var(--on-accent); }
/* A switch carries no text, so it may still fade. */
input.switch:disabled { opacity: .5; cursor: default; }

/* A switch turns something that runs on or off; a check box picks which items of a list apply -
   which kinds of interruption may be recovered, which events notify. The box is brand's CHECKBOX
   through the `--check-*` names css_scale() writes: unchecked, the sunken well a switch sits in;
   checked, the accent with its mark; disabled, flat on the surface. The mark is brand's tick,
   clipped out of a layer that covers the whole box, border included. The box sits left of its
   label, centred on the label's first line however far the label wraps. */
input.check { appearance: none; -webkit-appearance: none; position: relative; flex: none;
              width: var(--size-check-size); height: var(--size-check-size);
              margin: calc((var(--type-body) * var(--lh-body) - var(--size-check-size)) / 2) 0 0;
              border-radius: var(--radius-check); cursor: pointer;
              background: var(--check-off-fill); border: var(--size-hairline) solid var(--check-off-edge);
              box-shadow: var(--check-off-elev);
              transition: background-color var(--transition), border-color var(--transition),
                          box-shadow var(--transition);
              transition-timing-function: var(--transition-ease); }
/* The mark fades rather than blinks: its opacity eases, and it stays visible until a fade out has
   finished (a visibility transition keeps `visible` for its whole length). */
input.check::before { content: ""; position: absolute; inset: calc(-1 * var(--size-hairline));
                      clip-path: var(--check-mark-shape); background: var(--check-on-mark);
                      opacity: 0; visibility: hidden;
                      transition: opacity var(--transition), visibility var(--transition),
                                  background-color var(--transition);
                      transition-timing-function: var(--transition-ease); }
input.check:checked { background: var(--check-on-fill); border-color: var(--check-on-edge);
                      box-shadow: var(--check-on-elev); }
input.check:checked::before { opacity: 1; visibility: visible; }
input.check:disabled { background: var(--check-off-disabled-fill); border-color: var(--check-off-disabled-edge);
                       box-shadow: var(--check-off-disabled-elev); cursor: default; }
input.check:checked:disabled { background: var(--check-on-disabled-fill);
                               border-color: var(--check-on-disabled-edge);
                               box-shadow: var(--check-on-disabled-elev); }
input.check:checked:disabled::before { background: var(--check-on-disabled-mark); }

/* A setting is a row: what it is on the left, the control on the right. When there is no
   room for both, the control moves under its name rather than pushing past the edge.

   A switch or a button at the right of a row is pinned to the row's bottom-right: its right
   edge on the row's, its bottom on the bottom of the text beside it - so it sits beside the
   last line of a name that wraps, not centred on the first. Text shorter than the control is
   still centred on it, so a one-line row is drawn as it always was. The control comes after
   its text in the markup, which is the order it is read and reached by Tab, and it is a flex
   item that never shrinks beside text that does: the text wraps, or the control drops under
   it and stays on the right, and nothing ever runs underneath it. A select, a number, a chip
   and a check box keep their places. */
.rows > .setting + .setting, .rows > .setting + .custom, .toggles > .setting,
.custom > .setting + .setting { border-top: 1px solid var(--line); }
.setting { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
           gap: 6px var(--size-row-gap); padding: var(--size-row-pad); min-width: 0; }
label.setting { cursor: pointer; }
.setting.toggle > input.switch { align-self: flex-end; margin-left: auto; }
.setting.check { flex-wrap: nowrap; justify-content: flex-start; align-items: flex-start;
                 gap: var(--size-check-gap); }
.setting-text { flex: 1 1 180px; min-width: 0; display: grid; gap: 2px; }
.setting-label { font-weight: 500; }
.setting-control { flex: 0 1 auto; display: flex; min-width: 0; max-width: 100%; margin-left: auto; }
.has-select .setting-control { flex: 0 1 280px; }
.has-select .combo { width: 100%; }
.setting.stack { display: grid; grid-template-columns: minmax(0, 1fr); justify-content: stretch; gap: 8px; }
.card > h2 + *, .card-head + * { margin-top: var(--size-card-first-gap); }

.toggles { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
           column-gap: 28px; }
.toggles .setting { flex-wrap: nowrap; }
.toggles.quiet .setting-label { color: var(--muted); }

.master { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; margin: 10px 0 6px;
          padding: var(--size-tile-pad); background: var(--raised); border: 1px solid var(--line);
          border-radius: var(--radius-control); }
/* What the tile says - the state, and under it what the last press answered - is one block, and
   the button is pinned to the tile's bottom-right beside it (see .setting). */
.master-body { flex: 1 1 200px; display: grid; gap: 4px; min-width: 0; }
.master-text { display: flex; align-items: center; gap: 10px; min-width: 0; font-weight: 500; }
.master > button { align-self: flex-end; margin-left: auto; }
/* The same light, small and still: the state card above is the one that breathes. */
.dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--idle); }
.dot.on { background: var(--active); }
.dot.paused { background: var(--paused); }

.segmented { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--size-segment-gap); }
.segment { position: relative; display: flex; min-width: 0; }
.segment input { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0;
                 cursor: pointer; }
.segment span { flex: 1; min-width: 0; padding: var(--size-segment-pad); text-align: center; line-height: 20px;
                font-weight: 500; overflow-wrap: anywhere; color: var(--ink);
                border-radius: var(--radius-control); border: 1px solid var(--line);
                background: var(--raised); box-shadow: var(--elev-control);
                transition: background-color var(--transition), box-shadow var(--transition),
                            color var(--transition), border-color var(--transition);
                transition-timing-function: var(--transition-ease); }
.segment input:hover:not(:disabled) + span { background: var(--surface); }
.segment input:checked + span { background: var(--inset); box-shadow: var(--elev-inset);
                                color: var(--accent); border-color: var(--accent); font-weight: 600; }
.segment input:focus-visible + span { outline: 2px solid var(--focus); outline-offset: 2px; }
.segment input:disabled { cursor: default; }
.segment input:disabled + span { background: var(--surface); box-shadow: none; color: var(--muted); }

/* Folding sections: what is rarely changed stays one line tall until it is wanted. */
details.fold > summary { display: flex; align-items: center; justify-content: space-between;
                         gap: 12px; list-style: none; cursor: pointer; }
details.fold > summary::-webkit-details-marker { display: none; }
.chevron { flex: none; width: var(--size-fold-chevron); height: var(--size-fold-chevron); margin-right: 6px;
           border-right: 2px solid var(--muted); border-bottom: 2px solid var(--muted);
           transform: translateY(-2px) rotate(45deg);
           transition: transform var(--transition) var(--transition-ease); }
details.fold:not([open]) > summary .chevron { transform: rotate(-45deg); }
details.card.fold { padding: 0; }
details.card.fold > summary { padding: var(--size-card-pad); border-radius: var(--radius-card); }
details.card.fold[open] > summary { padding-bottom: 4px; }
details.card.fold > .fold-body { padding: 0 18px 8px; }
details.inner { border-top: 1px solid var(--line); }
details.inner > summary { padding: 12px 0; border-radius: var(--radius-small); }
details.inner > summary h3 { font-size: var(--type-body); font-weight: 600; }
details.inner > .fold-body { padding-bottom: 2px; }
details.inner > .fold-body > .setting { border-top: 1px solid var(--line); }

/* What is waiting, as soft rows rather than a table. Wide content wraps inside its row;
   the panel itself never scrolls sideways. */
.prows { list-style: none; padding: 0; display: grid; gap: var(--size-tile-gap); }
.prow { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; min-width: 0;
        padding: var(--size-tile-pad); background: var(--raised); border: 1px solid var(--line);
        border-radius: var(--radius-control); }
.prow-main { flex: 1 1 220px; min-width: 0; display: grid; gap: 3px; }
.prow-title { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; min-width: 0; }
.prow-name { font-weight: 600; min-width: 0; max-width: 100%; overflow: hidden;
             text-overflow: ellipsis; white-space: nowrap; }
.prow-meta { display: flex; flex-wrap: wrap; gap: 0 14px; color: var(--muted); font-size: var(--type-small);
             font-variant-numeric: tabular-nums; }
.prow-meta b { font-weight: 500; color: var(--ink); }
/* Pinned to the row's bottom-right, beside the facts line (see .setting); an open confirmation is
   a line of its own under both. */
.prow-switch { display: flex; align-items: center; align-self: flex-end; gap: 10px; margin-left: auto;
               color: var(--muted); font-size: var(--type-small); cursor: pointer; }
.prow-confirm { flex: 1 1 100%; display: grid; gap: 8px; padding-top: 10px;
                border-top: 1px solid var(--line); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }

.chip { --chip: var(--paused); display: inline-block; max-width: 100%; padding: 1px var(--size-chip-pad-x);
        border-radius: 999px; font-size: var(--type-small); line-height: 20px; font-weight: 500;
        color: var(--chip); background: var(--inset); white-space: nowrap; overflow: hidden;
        text-overflow: ellipsis; }
@supports (color: color-mix(in srgb, red 50%, blue)) {
  .chip { background: color-mix(in srgb, var(--chip) 12%, var(--surface)); }
}
.chip.waiting { --chip: var(--waiting); }
.chip.active { --chip: var(--accent); }
.chip.success { --chip: var(--success); }
.chip.warning { --chip: var(--warning); }
.chip.danger { --chip: var(--danger); }
.chip.paused { --chip: var(--paused); }

/* Stored Custom text: shown in a well, never in a field. */
.custom { display: grid; }
.stored { display: grid; gap: 10px; padding: 12px 0; border-top: 1px solid var(--line); }
.stored-item { display: grid; gap: 4px; min-width: 0; }
.stored-title { font-size: var(--type-small); font-weight: 500; color: var(--muted); }
.stored-text { padding: var(--size-stored-pad); border-radius: var(--radius-control); background: var(--inset);
               border: 1px solid var(--line); white-space: pre-wrap; overflow-wrap: anywhere;
               max-height: 10.5em; overflow: auto; }
.stored-item.unset { grid-template-columns: minmax(0, 1fr) auto; align-items: baseline; gap: 12px; }
.stored-item.unset .stored-title { color: var(--ink); font-size: var(--type-body); font-weight: 400; }
.stored-empty { color: var(--muted); font-size: var(--type-small); }
.callout { display: flex; align-items: flex-start; gap: var(--size-callout-gap); padding: var(--size-callout-pad);
           margin-bottom: 10px; border-radius: var(--radius-control); background: var(--accent-soft);
           color: var(--ink); font-size: var(--type-small); line-height: var(--lh-small); }
.callout::before { content: "i"; flex: none; width: var(--size-callout-badge); height: var(--size-callout-badge);
                   border-radius: 50%; background: var(--accent); color: var(--on-accent);
                   font: 600 var(--type-badge)/var(--size-callout-badge) var(--font); text-align: center; }

.bubble { margin-top: 10px; padding: var(--size-well-pad); border-radius: var(--radius-control);
          background: var(--inset); border: 1px solid var(--line); box-shadow: var(--elev-inset); }
.bubble-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: var(--lh-bubble);
               transition: opacity var(--transition) var(--transition-ease); }
.bubble[aria-busy="true"] .bubble-text { opacity: .55; }
.bubble.unavailable .bubble-text { color: var(--muted); }
.skeleton { display: block; height: var(--size-skeleton-height); margin: 6px 0;
            border-radius: var(--size-skeleton-radius); background: var(--line); }
.skeleton + .skeleton { width: 62%; }
.preview .source { margin-top: 10px; color: var(--ink); font-weight: 500; }
.preview .source + .help, .preview .bubble + .help { margin-top: 8px; }

.savebar { position: sticky; bottom: 10px; z-index: 1; display: flex; flex-wrap: wrap;
           align-items: center; gap: 8px 14px; padding: var(--size-savebar-pad); background: var(--surface);
           border: 1px solid var(--line); border-radius: var(--radius-card);
           box-shadow: var(--elev-card); }
/* The save card is a card: in dark it stands on the same lifted ground as the others. */
@supports (color: color-mix(in srgb, red 50%, blue)) {
  .savebar { background: var(--card-ground); }
}
.savebar .note { flex: 1 1 200px; min-width: 0; }
.savebar button { margin-left: auto; }

@media (max-width: 520px) {
  body { padding: 10px 10px 16px; }
  .card { padding: 14px; }
  .hero { padding: 14px 16px; }
  .hero h1 { font-size: var(--type-display-narrow); }
  /* One fact per line: a separator left hanging at the end of a wrapped line reads as a typo. */
  .facts { display: grid; gap: 1px; }
  .facts span:not(:last-child)::after { content: none; }
  details.card.fold > summary { padding: 14px; }
  details.card.fold > .fold-body { padding: 0 14px 6px; }
  .has-select { flex-direction: column; align-items: stretch; }
  .has-select .setting-text { flex: none; }
  .has-select .setting-control { flex: none; width: 100%; margin-left: 0; }
  .segmented { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

/* A person who asked Windows for less motion gets none: every glow holds still at its resting
   strength - the opacity each state's rule above already sets - nothing slides, a switch or a
   check box simply changes, and a list simply appears. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
  .halo::before { transform: none; }
}

/* Windows High Contrast. The browser puts the person's system colours in place of the palette
   and takes every shadow away - and it would paint the light over with the page's ground,
   and the switch's knob with it. So those keep a solid system colour of their own: Highlight
   while something is watched, the text colour for a problem, grey when the light is off. No
   glow: a soft falloff is exactly what High Contrast is asked to remove.

   And no motion, whatever Windows' animation setting says: High Contrast is less motion, as the
   window counts it (Soft.ReduceMotion) - a list simply appears, an item simply changes, and a switch
   or a check box simply changes. */
@media (forced-colors: active) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
  .card, .savebar, button, select, input, .segment span, .bubble,
  .combo-box, .combo-list, .combo-option { box-shadow: none; }
  .halo, .dot, .halo.paused, .dot.paused { forced-color-adjust: none; background: GrayText; }
  .halo.monitoring, .halo.waiting, .halo.checking, .halo.recovering, .dot.on { background: Highlight; }
  .halo.attention { background: CanvasText; }
  .halo::before { display: none; }
  /* The wedge is a clipped fill, which forced colours would paint the page's ground: it keeps the
     text colour. */
  .combo-box::after { forced-color-adjust: none; background: CanvasText; }
  .combo-box[aria-disabled="true"]::after { background: GrayText; }
  /* The list's items opt out for the same reason as the check box, so each draws itself in system
     colours: the current value in Highlight, the item under the pointer edged in it, and the item
     the keyboard is on ringed in it. */
  .combo-option { forced-color-adjust: none; background: Canvas; color: CanvasText; border-color: Canvas; }
  .combo-list:not(.keys) .combo-option:not([aria-selected="true"]):hover { background: Canvas;
                border-color: Highlight; box-shadow: none; }
  .combo-option[aria-selected="true"] { background: Highlight; color: HighlightText; border-color: Highlight;
                                        box-shadow: none; }
  .combo-list.keys .combo-option.active { outline-color: Highlight; }
  input.switch::before { forced-color-adjust: none; background: CanvasText; }
  input.switch:checked { forced-color-adjust: none; background: Highlight; border-color: Highlight; }
  input.switch:checked::before { background: HighlightText; }
  button[disabled], .combo-box[aria-disabled="true"], input:disabled, .segment input:disabled + span {
    color: GrayText; border-color: GrayText; }
  /* The check box keeps brand's system colours (CHECKBOX_SYSTEM) for the same reason as the knob:
     left to forced colours, the layer its mark is cut from is painted the page's ground. It opts
     out, so it takes its own shadow off and draws its own focus ring in a system colour. */
  input.check { forced-color-adjust: none; background: Canvas; border-color: CanvasText; box-shadow: none; }
  input.check:checked { background: Highlight; border-color: Highlight; box-shadow: none; }
  input.check:checked::before { background: HighlightText; }
  input.check:disabled { background: Canvas; border-color: GrayText; box-shadow: none; }
  input.check:checked:disabled { background: Canvas; border-color: GrayText; box-shadow: none; }
  input.check:checked:disabled::before { background: GrayText; }
  input.switch:focus-visible, input.check:focus-visible { outline-color: Highlight; }
  .segment input:checked + span { forced-color-adjust: none; background: Highlight; color: HighlightText;
                                  border-color: Highlight; box-shadow: none; }
}
"""

# Resolved once, at import: the palette is a build-time fact, not a per-request one. The lift
# of a surface is brand's SHADOWS written as CSS - the recipe the window and the popup paint
# from - so this page states no shadow of its own.
_STYLE = (_STYLE.replace("@LIGHT@", brand.css_variables(brand.LIGHT))
                .replace("@DARK@", brand.css_variables(brand.DARK))
                .replace("@ELEVATION_LIGHT@", brand.css_elevation("light"))
                .replace("@ELEVATION_DARK@", brand.css_elevation("dark"))
                .replace("@SCALE@", brand.css_scale())
                # Where a drop-down's words start, in its field and in its list: the field's own padding.
                .replace("@SELECT_PAD_LEFT@", "%gpx" % brand.padding("select_pad")[3]))

_SCRIPT = r"""
// The widget bridge is whatever the host provides. Try the documented shape first,
// then the ones seen in practice, and degrade to read-only rather than pretending.
function bridge() {
  var hosts = [window.openai, window.webplus, window.mcp, window.parent && window.parent.openai];
  for (var i = 0; i < hosts.length; i++) {
    var host = hosts[i];
    if (host && typeof host.callTool === 'function') return host;
  }
  return null;
}

function initialData() {
  var host = bridge() || window.openai || {};
  var output = host.toolOutput || host.output || window.__CODEX_AUTO_RESUME__;
  if (typeof output === 'string') { try { output = JSON.parse(output); } catch (e) { output = null; } }
  return output || null;
}

var HOST = bridge();
var DATA = initialData();
// A stamp the page was served with is a documentation capture's pinned theme, which the stored
// setting must not undo. Codex is never served one.
var THEME_PINNED = !!(document.documentElement && document.documentElement.hasAttribute('data-theme-pinned'));
// Survives a re-render: set before render(), shown by it, then cleared.
var NOTICE = '';
var EDITORS = {};
// Unsaved choices, kept across a re-render. A pause or a per-conversation switch redraws
// the whole panel, and a redraw that quietly put back what somebody had just changed would
// be a Save button that saves less than the panel showed a moment ago.
var DRAFT = {};
// Which folding sections are open, for the same reason.
var OPEN = {};
var HOOKS = {};
// The state the hero last showed, so a problem pulses when it appears and not on every redraw.
var LAST_STATE = '';
// The pending row whose "turn off" is being confirmed, by its exact interruption id.
var CONFIRM_ROW = '';
// What each pending row's switch showed when the page was last drawn, by interruption id - the
// drawing before this one in WAS, this one's in SHOWN - and the switches to move once drawn.
// A conversation's switch changes only when a tool has confirmed the change, and that answer
// arrives with a redraw: a switch drawn already moved would jump, so it is drawn where it was and
// glides from there (glide()).
var WAS = {};
var SHOWN = {};
var GLIDES = [];
var PREVIEW = {reason: '', nodes: null, last: null, asking: ''};
// The settings whose unsaved value changes the Preview.
var PREVIEW_FIELDS = ['interface_language', 'continuation_language', 'continuation_style',
                      'custom_message_mode'];

// Every word on this panel comes from Python, in the language Python resolved. The panel
// does not consult the browser's language: the notifications, the setup output, the
// standalone window and this page all have to agree, and only one of them can decide.
var S = window.__CODEX_AUTO_RESUME_STRINGS__ || {};
// The locale those words are in, and every language's words for this page. Python still
// decides: a language chosen here is spoken the moment the watcher confirms it was saved, by
// the rule Python resolves it with, from the words Python shipped - not a page that tells
// somebody the panel will change language the next time it is opened.
var LOCALE = window.__CODEX_AUTO_RESUME_LOCALE__ || '';
var CATALOGS = window.__CODEX_AUTO_RESUME_CATALOGS__ || {};
// What the save card says once a save has redrawn the page in another language.
var SAVED = '';

function t(key, fallback) {
  var value = S[key];
  return (value === undefined || value === null) ? (fallback || key) : value;
}

function fill(key, fallback, values) {
  var text = t(key, fallback);
  Object.keys(values || {}).forEach(function (name) {
    text = text.split('{' + name + '}').join(String(values[name]));
  });
  return text;
}

// The locale a stored Interface language is spoken in, by the rule Python adopts it with: a
// language chosen by name is that language, and `system` - or no choice at all - follows
// Windows, which Python already resolved and sent as `system_language`. '' when the page has no
// words for the answer, or no answer: then it keeps the words it was served rather than
// speaking a language nobody chose.
function localeFor(preference, systemLanguage, catalogs) {
  catalogs = catalogs || {};
  var has = function (code) {
    return typeof code === 'string' && Object.prototype.hasOwnProperty.call(catalogs, code);
  };
  if (typeof preference === 'string' && preference && preference !== 'system') {
    return has(preference) ? preference : '';
  }
  return has(systemLanguage) ? systemLanguage : '';
}

// Speak the stored language. True when the words changed, and so the page has to be drawn again.
function adoptLanguage(settings) {
  var locale = localeFor((settings || {}).interface_language, DATA && DATA.system_language, CATALOGS);
  if (!locale || locale === LOCALE) return false;
  S = CATALOGS[locale];
  LOCALE = locale;
  return true;
}

// What the stored Theme stamps on the page's root: Light or Dark as chosen, and nothing for Use
// system setting, which leaves Codex's own scheme in charge. Anything else - a watcher older than
// the setting, or a value from a newer one - is Use system setting.
function themeStamp(preference) {
  return (preference === 'light' || preference === 'dark') ? preference : '';
}

// On the root, because that is where the theme blocks and the aliases built on them are declared.
// High Contrast needs nothing here: forced colours replace whichever palette is stamped.
function applyTheme(root, settings, pinned) {
  if (!root || pinned) return;
  var stamp = themeStamp((settings || {}).theme);
  if (stamp) root.setAttribute('data-theme', stamp);
  else root.removeAttribute('data-theme');
}

// The stored appearance and language, applied to the page in place. True when the words changed.
function adopt(settings) {
  applyTheme(document.documentElement, settings, THEME_PINNED);
  return adoptLanguage(settings);
}

// The one code that is not worth translating, because the sentence beside it says more.
// The control layer gives it to a refusal it deliberately leaves unworded - a value the
// validator rejected, whose sentence names the setting it refused - and swapping that for
// "the request could not be completed" inside "Not saved: {reason}" would throw away the
// only informative half to say nothing twice.
var GENERIC_REFUSAL = 'request_failed';

// What a refused call says, in the language the rest of the panel is already speaking.
//
// Every refusal from the control layer carries a machine code from a closed set beside its
// English sentence, and this page was served an `error.<code>` string for every member of
// that set - so the code, not the prose, is the part that can be said in Korean. Without
// it the panel could only wrap a Korean frame around an English sentence, which is half a
// translation and reads worse than either language alone.
//
// Hosts differ on whether a rejected call hands back the whole tool result or only its
// structured half, exactly as they differ on a fulfilled one, so both shapes are looked in
// rather than depending on one. A refusal that arrives with no code at all is an older
// watcher than the codes, and then its sentence is all there is - still better than a
// panel that goes quiet about why nothing was saved.
function refusal(error) {
  var sentence = (error && error.message) ? error.message : t('panel.refused', 'refused');
  var payload = (error && error.structuredContent) || error || {};
  var code = payload.error_code;
  if (!code || code === GENERIC_REFUSAL) return sentence;
  return t('error.' + code, sentence);
}

// MCP tool failures are successful JSON-RPC replies with isError set. A host may
// resolve its promise with that reply (or only its structured content), so rejection
// of the JavaScript promise alone is not evidence that the operation succeeded.
function toolPayload(result) {
  var payload = (result && result.structuredContent) || result || {};
  if ((result && result.isError) || payload.error_code) {
    var content = (result && result.content) || [];
    var text = content.filter(function (item) { return item.type === 'text'; })
                      .map(function (item) { return item.text; }).join(' ');
    var error = new Error(text || t('panel.refused', 'refused'));
    error.structuredContent = payload;
    throw error;
  }
  return payload;
}

// The parameter is not called `arguments`. It was, and inside the inner function that
// name is that function's own implicit arguments object - so every call this panel made,
// Save included, handed the host an empty object instead of what it meant to send.
function callTool(name, args) {
  return Promise.resolve().then(function () {
    return HOST.callTool(name, args);
  }).then(toolPayload);
}

function saveSettings(changes) {
  return callTool('update_settings', changes).then(function (payload) {
    if (!payload.settings || typeof payload.settings !== 'object' || Array.isArray(payload.settings)) {
      throw new Error(t('panel.refused', 'refused'));
    }
    // A later pause re-renders the panel. Keep the acknowledged settings so that
    // re-render cannot restore the values from the original open_settings snapshot.
    DATA.settings = payload.settings;
    return payload;
  });
}

function setRecoveryEnabled(enable) {
  return callTool(enable ? 'resume_auto_recovery' : 'pause_auto_recovery', {}).then(function (payload) {
    if (typeof payload.enabled !== 'boolean') throw new Error(t('panel.refused', 'refused'));
    DATA.status.enabled = payload.enabled;
    return payload;
  });
}

// Automatic recovery for one exact conversation, addressed by the thread id the row was
// drawn from and by nothing else. Not optimistic: the rows change only once a tool has
// answered for that same thread, and a reply about any other thread is a refusal.
// Turning it back on adds automation, so Codex asks the person first; that is expected.
function setThreadRecovery(threadId, enable) {
  var tool = enable ? 'enable_conversation_recovery' : 'disable_conversation_recovery';
  return callTool(tool, {thread_id: threadId}).then(function (payload) {
    if (payload.thread_id !== threadId) throw new Error(t('panel.refused', 'refused'));
    var enabled = typeof payload.enabled === 'boolean' ? payload.enabled : null;
    if (enabled === null) {
      // Turning recovery off answers with the thread alone. Turning it on has to say so.
      if (enable) throw new Error(t('panel.refused', 'refused'));
      enabled = false;
    }
    (DATA.pending || []).forEach(function (row) {
      if (row.thread_id !== threadId) return;
      row.thread_enabled = enabled;
      var overlays = (row.overlays || []).filter(function (name) { return name !== 'thread_disabled'; });
      if (!enabled) overlays.push('thread_disabled');
      row.overlays = overlays;
    });
    return enabled;
  });
}

// Which settings this panel may write. The same rule the server generates the
// update_settings schema by - the groups a person edits, and never Custom message text,
// which is written in the Windows Dashboard by the person it will speak for - kept here so
// the Save button cannot even assemble a request that carries it.
function editable(entry) {
  var groups = ['general', 'recovery', 'limits', 'notifications', 'continuation'];
  // Of the appearance settings only the theme, which the panel applies to itself. Reduce motion
  // and the notification-area icon are Windows' own and stay in the Windows Dashboard.
  var appearance = ['theme'];
  if (!entry || typeof entry.name !== 'string') return false;
  if (entry.group === 'appearance') return appearance.indexOf(entry.name) >= 0 && !entry.multiline;
  if (groups.indexOf(entry.group) < 0 || entry.multiline) return false;
  return entry.name.indexOf('custom_message') !== 0 || entry.name === 'custom_message_mode';
}

function collectChanges(editors, schema) {
  var changes = {};
  (schema || []).forEach(function (entry) {
    if (editable(entry) && typeof editors[entry.name] === 'function') {
      changes[entry.name] = editors[entry.name]();
    }
  });
  return changes;
}

// Of the collected changes, the settings every surface is drawn in - the Interface language and
// the Theme - that still hold what the page was drawn with (or last saved). This page is not told
// when the Windows Dashboard, another panel or Codex changes either, so sending them back unedited
// would quietly undo that change, and the Dashboard, which reopens itself in a new language or
// theme, would reopen in the one it had just left. They go only when chosen here: the rule the
// Dashboard saves by too. Every other setting is still sent whole, as it always was.
function unedited(changes, saved) {
  saved = saved || {};
  return ['interface_language', 'theme'].filter(function (name) {
    return Object.prototype.hasOwnProperty.call(changes, name)
           && Object.prototype.hasOwnProperty.call(saved, name)
           && changes[name] === saved[name];
  });
}

// The Preview request: one kind of interruption, and the unsaved language and style.
// Exactly these four choices and nothing else - the tool refuses Custom text, and this
// never offers it one.
function previewArguments(category, read) {
  var changes = {};
  ['interface_language', 'continuation_language', 'continuation_style',
   'custom_message_mode'].forEach(function (name) {
    var value = read(name);
    if (typeof value === 'string' && value) changes[name] = value;
  });
  return {category: category, changes: changes};
}

// One word for the whole product, in the order that matters: nothing is recovered while
// no watcher runs, nothing is sent while paused, and a row already in Codex outranks a row
// that is still waiting.
function activity(status, rows) {
  var moving = ['submission_claimed', 'submitted', 'withdrawing', 'turn_running', 'turn_finishing'];
  var codes = (status && status.codes) || {};
  var list = rows || [];
  status = status || {};
  if (status.watcher_running !== true) return 'attention';
  if (!status.enabled) return 'paused';
  for (var i = 0; i < moving.length; i++) {
    if (codes[moving[i]] > 0) return 'recovering';
  }
  for (var j = 0; j < list.length; j++) {
    if (moving.indexOf(list[j].code) >= 0) return 'recovering';
  }
  return (status.pending > 0 || list.length > 0) ? 'waiting' : 'monitoring';
}

// The status light for a state. Not quite the word: a watcher that is not running - or that
// nothing has confirmed is running - is a light that is off, grey as it always was, while the
// word beside it still asks for attention. Amber is for a watcher that runs and is not well.
function lightFor(status, state) {
  return (status && status.watcher_running === true) ? state : 'idle';
}

// The colour a state chip carries. Always beside its word, never instead of it.
function tone(code) {
  if (['submission_claimed', 'submitted', 'withdrawing', 'turn_running',
       'turn_finishing'].indexOf(code) >= 0) return 'active';
  if (['waiting_reset', 'waiting_usage', 'waiting_thread', 'scheduled'].indexOf(code) >= 0) return 'waiting';
  if (code === 'recovered') return 'success';
  if (['exhausted', 'failed_terminal', 'recovery_failed'].indexOf(code) >= 0) return 'danger';
  if (['failed_retryable', 'outcome_unverified', 'submission_unknown', 'no_progress',
       'engine_unavailable', 'watcher_not_ticking', 'compatibility_blocked'].indexOf(code) >= 0) return 'warning';
  return 'paused';
}

function label(name) {
  var known = S['field.' + name];
  if (known) return known;
  var key = name.replace(/^recover_/, '').replace(/^notify_/, '').replace(/_/g, ' ');
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function element(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function card(title, extra) {
  var node = element('section', 'card' + (extra ? ' ' + extra : ''));
  if (title) node.appendChild(element('h2', null, title));
  return node;
}

// A section whose body folds away. Whether it is open survives a redraw.
function folding(key, title, openByDefault, kind) {
  var node = element('details', kind === 'inner' ? 'fold inner' : 'card fold');
  node.open = Object.prototype.hasOwnProperty.call(OPEN, key) ? OPEN[key] : openByDefault;
  var summary = element('summary');
  summary.appendChild(element(kind === 'inner' ? 'h3' : 'h2', null, title));
  var chevron = element('span', 'chevron');
  chevron.setAttribute('aria-hidden', 'true');
  summary.appendChild(chevron);
  node.appendChild(summary);
  node.addEventListener('toggle', function () { OPEN[key] = node.open; });
  var body = element('div', 'fold-body');
  node.appendChild(body);
  return {node: node, body: body};
}

function endonym(code) {
  return (DATA.endonyms || {})[code] || code || '';
}

// "System (한국어)" - with the language named in itself, or with no brackets at all when an
// older watcher did not say which language the system has.
function withLanguage(key, fallback, code) {
  var text = fill(key, fallback, {language: endonym(code)});
  return code ? text : text.replace(/\s*\(\s*\)/, '');
}

function value(name) {
  if (Object.prototype.hasOwnProperty.call(DRAFT, name)) return DRAFT[name];
  return (DATA.settings || {})[name];
}

function read(name) {
  return typeof EDITORS[name] === 'function' ? EDITORS[name]() : value(name);
}

function edited(name) {
  if (HOOKS.dirty) HOOKS.dirty();
  if (PREVIEW_FIELDS.indexOf(name) >= 0) refreshPreview();
}

function unsaved(schema) {
  var saved = DATA.settings || {};
  var changes = collectChanges(EDITORS, schema);
  return Object.keys(changes).some(function (name) { return changes[name] !== saved[name]; });
}

function settingRow(title, help, control, className) {
  var row = element('div', 'setting' + (className ? ' ' + className : ''));
  var text = element('div', 'setting-text');
  var name = element('label', 'setting-label', title);
  if (control.id) name.htmlFor = control.id;
  text.appendChild(name);
  var helpNode = null;
  if (help) {
    helpNode = element('p', 'help', help);
    text.appendChild(helpNode);
  }
  row.appendChild(text);
  var box = element('div', 'setting-control');
  box.appendChild(control);
  row.appendChild(box);
  return {row: row, help: helpNode, label: name};
}

// A drop-down: a select, and the list this page opens for it (`.combo` in the stylesheet says why
// the list is the page's own, and that it is the Windows Dashboard's list).
//
// The select stays in the page, hidden, and is still the value: EDITORS read it, the page listens
// to its `change`, and picking from the list sets it and fires that `change`, so nothing that reads
// a choice knows the list exists. Nothing can open the browser's own list: the select is never
// shown, never focused and never reached by Tab.
//
// What is seen, focused and read out is a combobox, as the WAI-ARIA pattern for a select-only
// combobox has it: `aria-expanded` while its list is open, `aria-activedescendant` naming the item
// the keyboard is on - focus itself never leaves the combobox - and a listbox of options, the
// current value's `aria-selected`. The listbox is the card; what scrolls inside it says nothing of
// its own. Its keys are the pattern's and the window's list's (SoftCombo) together:
//   closed  Down, Up, Enter, Space, F4, Alt+Down and Alt+Up open the list on the current value;
//           Home and End open it on the first and the last item, Page Up and Page Down a page along;
//           a letter opens it on the next item whose name begins with it;
//   open    Up, Down, Home, End, Page Up and Page Down move - a page is what shows, less one row, as
//           in the window; Enter, Space, F4, Alt+Up and Alt+Down pick and close; Tab picks and moves
//           on; Escape closes and changes nothing; Left and Right do nothing; a letter finds.
// Letters typed within a second of each other are one search, the window's TypeAhead, measured
// between the keys' own time stamps, so nothing here ticks. The search is the window's
// (SoftCombo.Find): a first letter looks from the item after the one the keyboard is on, round to
// the start, and the same letter again steps on through the items it begins; a longer search keeps
// the item the keyboard is on while that still matches, so a word typed through goes to its item and
// stays there.
//
// The pointer: a press on the field opens or closes the list, a press on an item picks it. The
// pointer moving over an item moves the keyboard's item there - shown by the item rising rather than
// by the ring - so Enter takes the item under the pointer, as in the window; a move the browser makes
// up for a pointer that stood still while the list appeared or scrolled under it leaves the keyboard
// where it is. A press anywhere else, the page losing focus - to another window, or to Codex itself -
// and Tab away all close it, since each takes focus from the combobox; only Tab picks on the way. A
// press inside the list keeps focus where it is. The wheel scrolls a long list, a row at a time, and
// stops at its ends rather than carrying on into the page.
var COMBO_ROWS = 12;
var COMBO_TYPING_MS = 1000;

function combo(select) {
  var id = select.id;
  var wrap = element('div', 'combo');
  select.hidden = true;
  select.setAttribute('tabindex', '-1');
  select.setAttribute('aria-hidden', 'true');
  wrap.appendChild(select);
  var box = element('div', 'combo-box');
  box.id = id + '-box';
  box.setAttribute('role', 'combobox');
  box.setAttribute('aria-haspopup', 'listbox');
  box.setAttribute('aria-expanded', 'false');
  box.setAttribute('aria-controls', id + '-list');
  var shown = element('span', 'combo-value');
  box.appendChild(shown);
  wrap.appendChild(box);
  var list = element('div', 'combo-list');
  list.id = id + '-list';
  list.setAttribute('role', 'listbox');
  list.setAttribute('tabindex', '-1');
  list.hidden = true;
  var scroll = element('div', 'combo-scroll');
  scroll.setAttribute('role', 'none');
  list.appendChild(scroll);
  wrap.appendChild(list);
  var items = [];
  var expanded = false;
  var active = 0;
  var typed = '';
  var typedAt = -Infinity;
  // Where the pointer last moved to, on the screen.
  var pointer = null;

  Array.prototype.forEach.call(select.options, function (option, index) {
    var item = element('div', 'combo-option');
    item.id = id + '-option-' + index;
    item.setAttribute('role', 'option');
    item.addEventListener('click', function () {
      pick(index);
      box.focus();
    });
    item.addEventListener('mousemove', function (event) { hover(index, event); });
    scroll.appendChild(item);
    items.push(item);
  });

  // The index of the value the select holds.
  function current() {
    for (var index = 0; index < select.options.length; index++) {
      if (select.options[index].value === select.value) return index;
    }
    return 0;
  }

  // The field, the items and whether any of it can be used, from the select - which is also how a
  // caller that renames an option (the Continuation language's "Same as the interface") is shown.
  function sync() {
    var chosen = current();
    shown.textContent = items.length ? select.options[chosen].textContent : '';
    items.forEach(function (item, index) {
      item.textContent = select.options[index].textContent;
      item.setAttribute('aria-selected', index === chosen ? 'true' : 'false');
    });
    if (select.disabled) {
      close();
      box.setAttribute('aria-disabled', 'true');
      box.removeAttribute('tabindex');
    } else {
      box.removeAttribute('aria-disabled');
      box.setAttribute('tabindex', '0');
    }
  }

  // From one item to the next, as laid out: an item and the gap under it.
  function pitch() {
    return items.length > 1 ? items[1].offsetTop - items[0].offsetTop : items[0].offsetHeight;
  }

  // How many rows show: as laid out, or - where nothing is laid out - what the stylesheet shows.
  function rows() {
    var step = pitch();
    var count = step > 0 ? Math.round((scroll.clientHeight - 2 * items[0].offsetTop + step - items[0].offsetHeight) / step)
                         : NaN;
    return count >= 1 ? count : Math.min(items.length, COMBO_ROWS);
  }

  // A page: what shows, less the row kept in view from the page before.
  function page() {
    return Math.max(1, rows() - 1);
  }

  // As the window places its list (SoftDropList.Place). Across, from a pad left of the field, as the
  // stylesheet has it, and moved left as far as it would run past the page, which it is never wider
  // than. Below the field, or above it when there is not room for it below and there is more above;
  // a list with room on neither side goes to the larger and is cut to the whole rows that fit there,
  // never fewer than one, and scrolls. Measured in layout, which the opening rise does not move.
  function place() {
    list.classList.toggle('up', false);
    list.style.left = '';
    list.style.maxWidth = '';
    scroll.style.maxHeight = '';
    var root = document.documentElement || {};
    var width = root.clientWidth || window.innerWidth || 0;
    if (width && typeof list.getBoundingClientRect === 'function') {
      list.style.maxWidth = width + 'px';
      var edge = list.getBoundingClientRect();
      var over = Math.min(edge.right - width, edge.left);
      if (over > 0) list.style.left = (list.offsetLeft - over) + 'px';
    }
    var view = window.innerHeight || root.clientHeight || 0;
    if (!view || typeof box.getBoundingClientRect !== 'function') return;
    var field = box.getBoundingClientRect();
    var gap = Math.max(0, list.offsetTop - box.offsetHeight);
    var height = list.offsetHeight;
    var below = view - field.bottom - 2 * gap;
    var above = field.top - 2 * gap;
    if (height <= below) return;
    var up = above > below;
    list.classList.toggle('up', up);
    var room = Math.floor(up ? above : below);
    var step = pitch(), pill = items[0].offsetHeight, inset = items[0].offsetTop;
    if (height <= room || !(step > 0)) return;
    // The card's hairlines and padding and the room around the items, above and below them.
    var frame = height - scroll.clientHeight + 2 * inset;
    var fit = Math.max(1, Math.floor((room - frame + step - pill) / step));
    scroll.style.maxHeight = (2 * inset + fit * step - (step - pill)) + 'px';
  }

  // The item the keyboard is on, scrolled into the list's view with its ring - a whole row at a time,
  // since every row starts a pitch after the one before.
  function reveal(item) {
    var room = scroll.clientHeight;
    if (!(scroll.scrollHeight > room)) return;
    var pad = items[0].offsetTop;
    var top = item.offsetTop - pad;
    var bottom = item.offsetTop + item.offsetHeight + pad;
    if (top < scroll.scrollTop) scroll.scrollTop = top;
    else if (bottom > scroll.scrollTop + room) scroll.scrollTop = bottom - room;
  }

  // The keyboard's item to `index`, kept to the list; scrolled into view unless the pointer put it there.
  function move(index, byPointer) {
    active = Math.max(0, Math.min(items.length - 1, index));
    items.forEach(function (item, at) { item.classList.toggle('active', at === active); });
    box.setAttribute('aria-activedescendant', items[active].id);
    if (!byPointer) reveal(items[active]);
  }

  // The pointer over item `index`. A move with no movement, or to where the pointer already was, is
  // one the browser makes up when the list appears or scrolls under a pointer that stood still: while
  // the keyboard leads, that leaves its item where it is. Any other hands the lead to the pointer.
  function hover(index, event) {
    if (!expanded) return;
    var at = event && typeof event.screenX === 'number' ? event.screenX + ',' + event.screenY : null;
    var still = !!event && ((event.movementX === 0 && event.movementY === 0) || (at !== null && at === pointer));
    pointer = at;
    if (still && list.classList.contains('keys')) return;
    list.classList.toggle('keys', false);
    move(index, true);
  }

  function open(index, byKeys) {
    if (select.disabled || !items.length) return;
    if (!expanded) {
      expanded = true;
      list.hidden = false;
      box.setAttribute('aria-expanded', 'true');
      list.classList.toggle('keys', !!byKeys);
      place();
    }
    move(index);
  }

  function close() {
    if (!expanded) return;
    expanded = false;
    list.hidden = true;
    list.classList.toggle('keys', false);
    box.setAttribute('aria-expanded', 'false');
    box.removeAttribute('aria-activedescendant');
    typed = '';
  }

  // The item at `index` becomes the value, and the select says so the way a select does.
  function pick(index) {
    close();
    var option = select.options[index];
    if (!option || option.value === select.value) return;
    select.value = option.value;
    sync();
    select.dispatchEvent(new Event('change', {bubbles: true}));
  }

  // What `text` finds with the keyboard on item `from`: SoftCombo.Find, the window's. -1 when nothing does.
  function seek(text, from) {
    var wanted = text.toLowerCase();
    var repeated = wanted.split('').every(function (character) { return character === wanted.charAt(0); });
    if (repeated) wanted = wanted.charAt(0);
    var start = repeated ? from + 1 : from;
    for (var step = 0; step < items.length; step++) {
      var at = (start + step) % items.length;
      if (items[at].textContent.toLowerCase().indexOf(wanted) === 0) return at;
    }
    return -1;
  }

  function typing(time) {
    return typed !== '' && time - typedAt < COMBO_TYPING_MS;
  }

  function find(letter, time) {
    if (!typing(time)) typed = '';
    typed += letter;
    typedAt = time;
    var from = expanded ? active : current();
    var at = seek(typed, from);
    open(at < 0 ? from : at, true);
  }

  box.addEventListener('keydown', function (event) {
    if (select.disabled || event.ctrlKey || event.metaKey) return;
    var key = event.key || '';
    var time = event.timeStamp || Date.now();
    var last = items.length - 1;
    if (key === 'Tab') {
      if (expanded) pick(active);
      return;
    }
    // F4, and Alt with Down or Up: what opens the window's list and takes its item. Never Alt+F4.
    var toggles = (key === 'F4' && !event.altKey) || (event.altKey && (key === 'ArrowDown' || key === 'ArrowUp'));
    if (key.length === 1 && !event.altKey && (key !== ' ' || typing(time))) find(key, time);
    else if (!expanded) {
      if (toggles || key === 'ArrowDown' || key === 'ArrowUp' || key === 'Enter' || key === ' ') open(current(), true);
      else if (key === 'Home') open(0, true);
      else if (key === 'End') open(last, true);
      else if (key === 'PageUp' || key === 'PageDown') {
        open(current(), true);
        move(active + (key === 'PageUp' ? -1 : 1) * page());
      }
      else return;
    }
    else if (toggles || key === 'Enter' || key === ' ') pick(active);
    else if (key === 'Escape') {
      close();
      event.stopPropagation();
    }
    else if (key === 'ArrowDown') move(active + 1);
    else if (key === 'ArrowUp') move(active - 1);
    else if (key === 'Home') move(0);
    else if (key === 'End') move(last);
    else if (key === 'PageUp') move(active - page());
    else if (key === 'PageDown') move(active + page());
    else if (key !== 'ArrowLeft' && key !== 'ArrowRight') return;
    event.preventDefault();
    if (expanded) list.classList.toggle('keys', true);
  });
  box.addEventListener('click', function () {
    if (select.disabled) return;
    if (expanded) close();
    else open(current(), false);
  });
  box.addEventListener('blur', close);
  list.addEventListener('mousedown', function (event) { event.preventDefault(); });
  select.addEventListener('change', sync);
  sync();

  // The setting's name names the field and its list, a press on the name puts focus on the field,
  // and the help under the name describes it.
  function labelled(labelNode, helpNode) {
    labelNode.id = id + '-label';
    box.setAttribute('aria-labelledby', labelNode.id);
    list.setAttribute('aria-labelledby', labelNode.id);
    if (helpNode) {
      helpNode.id = id + '-help';
      box.setAttribute('aria-describedby', helpNode.id);
    }
    labelNode.addEventListener('click', function () {
      if (!select.disabled) box.focus();
    });
  }

  return {node: wrap, box: box, list: list, sync: sync, labelled: labelled};
}

function toggle(entry, onChange) {
  var row = element('label', 'setting toggle');
  var text = element('span', 'setting-text');
  text.appendChild(element('span', 'setting-label', label(entry.name)));
  row.appendChild(text);
  var input = element('input', 'switch');
  input.type = 'checkbox';
  input.setAttribute('role', 'switch');
  input.checked = !!value(entry.name);
  input.disabled = !HOST;
  input.addEventListener('change', function () {
    DRAFT[entry.name] = input.checked;
    edited(entry.name);
    if (onChange) onChange(input.checked);
  });
  row.appendChild(input);
  EDITORS[entry.name] = function () { return input.checked; };
  return row;
}

// Which control an on/off setting gets, by what it means rather than by its type. A switch turns
// something that runs on or off - the notifications master, a conversation's auto-resume. A check
// box picks which items of a list apply: `recover_<category>`, which kinds of interruption may be
// recovered, and `notify_<event>`, which events notify under the master switch. The window
// draws the same setting as the same kind.
function booleanKind(entry) {
  if (!entry || entry.master) return 'switch';
  return /^(recover|notify)_[a-z0-9_]+$/.test(String(entry.name || '')) ? 'check' : 'switch';
}

// A native check box - no switch role, because it is not one - ahead of its label, inside the
// label so the whole row toggles it.
function checkItem(entry) {
  var row = element('label', 'setting check');
  var input = element('input', 'check');
  input.type = 'checkbox';
  input.checked = !!value(entry.name);
  input.disabled = !HOST;
  input.addEventListener('change', function () {
    DRAFT[entry.name] = input.checked;
    edited(entry.name);
  });
  row.appendChild(input);
  var text = element('span', 'setting-text');
  text.appendChild(element('span', 'setting-label', label(entry.name)));
  row.appendChild(text);
  EDITORS[entry.name] = function () { return input.checked; };
  return row;
}

function onOff(entry, onChange) {
  return booleanKind(entry) === 'check' ? checkItem(entry) : toggle(entry, onChange);
}

function numberField(entry) {
  var input = document.createElement('input');
  input.type = 'number';
  input.id = 'car-' + entry.name;
  if (entry.min !== undefined) input.min = entry.min;
  if (entry.max !== undefined) input.max = entry.max;
  input.value = value(entry.name);
  input.disabled = !HOST;
  input.addEventListener('input', function () {
    DRAFT[entry.name] = Number(input.value);
    edited(entry.name);
  });
  EDITORS[entry.name] = function () { return Number(input.value); };
  return settingRow(label(entry.name), '', input).row;
}

// A select whose stored value is the untranslated choice and whose label is whatever the
// caller says - a settings file whose meaning changed with the display language would be
// a bug nobody could see.
function choiceField(entry, options, help, onChange) {
  var input = document.createElement('select');
  input.id = 'car-' + entry.name;
  var chosen = value(entry.name);
  options.forEach(function (option) {
    var node = element('option', null, option.text);
    node.value = option.value;
    if (option.value === chosen) node.selected = true;
    input.appendChild(node);
  });
  input.disabled = !HOST;
  input.addEventListener('change', function () {
    DRAFT[entry.name] = input.value;
    edited(entry.name);
    if (onChange) onChange(input.value);
  });
  EDITORS[entry.name] = function () { return input.value; };
  var field = combo(input);
  var built = settingRow(label(entry.name), help, field.node, 'has-select');
  field.labelled(built.label, built.help);
  built.select = input;
  built.sync = field.sync;
  return built;
}

function segmented(entry, onChange) {
  var group = element('div', 'segmented');
  group.setAttribute('role', 'radiogroup');
  group.setAttribute('aria-label', label(entry.name));
  var chosen = value(entry.name);
  var inputs = [];
  (entry.choices || []).forEach(function (choice) {
    var item = element('label', 'segment');
    var input = document.createElement('input');
    input.type = 'radio';
    input.name = 'car-' + entry.name;
    input.value = choice;
    input.checked = choice === chosen;
    input.disabled = !HOST;
    input.addEventListener('change', function () {
      if (!input.checked) return;
      DRAFT[entry.name] = choice;
      edited(entry.name);
      if (onChange) onChange(choice);
    });
    item.appendChild(input);
    item.appendChild(element('span', null, t('choice.style.' + choice, choice)));
    group.appendChild(item);
    inputs.push(input);
  });
  EDITORS[entry.name] = function () {
    for (var i = 0; i < inputs.length; i++) {
      if (inputs[i].checked) return inputs[i].value;
    }
    return chosen;
  };
  return group;
}

// When a record is next looked at, as a local clock time.
//
// Not a ticking countdown: this page is drawn once from one tool result and is not
// refreshed, so a number counting down here would be wrong within a minute and would go
// on being wrong convincingly. A time is still true an hour later, and "due now" is what
// a moment that has already passed actually means - the watcher looks at it on its next
// pass, and nothing here can say when that is.
function nextCheck(row) {
  var at = row.eligible_at;
  if (at === null || at === undefined) return t('panel.next_unknown', 'not known yet');
  var when = new Date(at * 1000);
  if (isNaN(when.getTime())) return t('panel.next_unknown', 'not known yet');
  if (when.getTime() <= Date.now()) return t('panel.due', 'due now');
  // The clock, written the way the continuation writes a reset time. Not the browser's
  // own format: that speaks the browser's language, and put "오전 02:48" into an English
  // panel on a Korean machine.
  var pad = function (number) { return (number < 10 ? '0' : '') + number; };
  return pad(when.getHours()) + ':' + pad(when.getMinutes());
}

function heroFacts(status, state) {
  var count = status.pending || 0;
  var pending = count === 0 ? t('status.pending_none', 'Nothing pending')
              : count === 1 ? t('status.pending_one', '1 recovery pending')
              : fill('status.pending_many', '{n} recoveries pending', {n: count});
  if (state === 'attention') {
    var facts = [status.watcher_running === false ? t('status.not_running', 'Watcher not running')
                                                  : t('status.unknown', 'Watcher status unknown'),
                 t('status.recovery_idle', 'Nothing will be recovered until it is running')];
    if (count) facts.push(pending);
    return facts;
  }
  if (state === 'paused') return [t('status.recovery_paused', 'Automatic recovery is paused'), pending];
  var shown = [t('status.recovery_on', 'Automatic recovery is on'), pending];
  // The soonest check, which is the question a count raises rather than answers.
  var soonest = null;
  (DATA.pending || []).forEach(function (row) {
    if (row.eligible_at === null || row.eligible_at === undefined) return;
    if (soonest === null || row.eligible_at < soonest) soonest = row.eligible_at;
  });
  if (count && soonest !== null) {
    shown.push(fill('status.next_check', 'next check {time}', {time: nextCheck({eligible_at: soonest})}));
  }
  return shown;
}

function renderHero(status) {
  var state = activity(status, DATA.pending);
  var hero = element('section', 'card hero');
  hero.setAttribute('data-state', state);
  // The product name is an eyebrow rather than a heading: inside Codex the panel is
  // already attributed, and the question a reader arrives with is what it is doing.
  hero.appendChild(element('div', 'eyebrow', 'Codex Auto Resume · v' + (status.version || '?')));
  var line = element('div', 'hero-state');
  var light = lightFor(status, state);
  var halo = element('span', 'halo ' + light + (light === 'attention' && LAST_STATE !== 'attention' ? ' once' : ''));
  halo.setAttribute('aria-hidden', 'true');
  LAST_STATE = state;
  line.appendChild(halo);
  line.appendChild(element('h1', null, t('activity.' + state, state)));
  hero.appendChild(line);
  var facts = element('p', 'facts');
  heroFacts(status, state).forEach(function (fact) { facts.appendChild(element('span', null, fact)); });
  hero.appendChild(facts);
  var actions = element('div', 'hero-actions');
  // Offered only when it is the thing that is wrong. Nothing is recovered while the
  // watcher is stopped, so a panel that reports it and offers no way out is a dead end.
  var start = null;
  if (status.watcher_running === false) {
    start = element('button', 'primary', t('action.start', 'Start watcher'));
    start.disabled = !HOST;
    actions.appendChild(start);
  }
  var message = element('p', 'note');
  message.setAttribute('role', 'status');
  actions.appendChild(message);
  hero.appendChild(actions);
  return {node: hero, message: message, start: start};
}

function renderPending(rows) {
  if (!rows || !rows.length) return null;
  var box = card(null, 'pending');
  var head = element('div', 'card-head');
  head.appendChild(element('h2', null, t('panel.pending_title', 'Waiting to resume')));
  head.appendChild(element('span', 'count', String(rows.length)));
  box.appendChild(head);
  var list = element('ul', 'prows');
  rows.slice(0, 8).forEach(function (row) { list.appendChild(pendingRow(row)); });
  box.appendChild(list);
  if (rows.length > 8) {
    var more = element('p', 'note', fill('panel.more', 'and {n} more', {n: rows.length - 8}));
    more.style.marginTop = '10px';
    box.appendChild(more);
  }
  return box;
}

function pendingRow(row) {
  var item = element('li', 'prow');
  var main = element('div', 'prow-main');
  var title = element('div', 'prow-title');
  // The exact thread id, shortened for display only. Every action this panel can take
  // addresses a record by its full id, never by what is shown.
  var shown = row.name || String(row.thread_id || '').slice(0, 8);
  title.appendChild(element('span', 'prow-name' + (row.name ? '' : ' mono'), shown));
  // The public code, never the engine's working state: several stored states share
  // one code, and what a person is told must not depend on engine internals.
  var code = row.code || row.state || '';
  title.appendChild(element('span', 'chip ' + tone(code), t('code.' + code, code.replace(/_/g, ' '))));
  (row.overlays || []).forEach(function (overlay) {
    title.appendChild(element('span', 'chip ' + tone(overlay),
                              t('overlay.' + overlay, overlay.replace(/_/g, ' '))));
  });
  main.appendChild(title);
  var meta = element('div', 'prow-meta');
  if (row.category && S['reason.' + row.category]) {
    meta.appendChild(element('span', null, t('reason.' + row.category, row.category)));
  }
  [[t('panel.col_next', 'Next check'), nextCheck(row)],
   [t('panel.col_attempts', 'Attempts'), String(row.recovery_attempts === undefined ? 0 : row.recovery_attempts)]
  ].forEach(function (pair) {
    var fact = element('span', null, pair[0] + ' ');
    fact.appendChild(element('b', null, pair[1]));
    meta.appendChild(fact);
  });
  main.appendChild(meta);
  item.appendChild(main);
  if (typeof row.thread_enabled === 'boolean' && row.thread_id) {
    item.appendChild(threadSwitch(row, shown));
  }
  if (CONFIRM_ROW && CONFIRM_ROW === row.interruption_id) item.appendChild(confirmOff(row, shown));
  return item;
}

function threadSwitch(row, shown) {
  var wrap = element('label', 'prow-switch');
  wrap.appendChild(element('span', null, t('pending.col_resume', 'Auto-resume')));
  var input = element('input', 'switch');
  input.type = 'checkbox';
  input.setAttribute('role', 'switch');
  input.setAttribute('aria-label', t('pending.col_resume', 'Auto-resume') + ': ' + shown);
  var was = WAS[row.interruption_id];
  input.checked = typeof was === 'boolean' ? was : row.thread_enabled;
  if (input.checked !== row.thread_enabled) GLIDES.push({input: input, to: row.thread_enabled});
  SHOWN[row.interruption_id] = row.thread_enabled;
  input.disabled = !HOST;
  input.addEventListener('change', function () {
    // The switch shows what a tool last confirmed, until a tool confirms something else. Put back
    // in the same task as the press, before anything is drawn: it never moves on the press, and so
    // never snaps back - it moves once, when the change is confirmed.
    input.checked = row.thread_enabled;
    if (row.thread_enabled) {
      // Turning it off cancels what this conversation has waiting, so it is asked first.
      CONFIRM_ROW = row.interruption_id;
      render();
      return;
    }
    changeThread(row, shown, true, [input]);
  });
  wrap.appendChild(input);
  return wrap;
}

function confirmOff(row, shown) {
  var box = element('div', 'prow-confirm');
  box.appendChild(element('p', null, fill('confirm.thread_off',
    'Turn automatic recovery off for "{name}"? Its waiting recoveries are cancelled.', {name: shown})));
  var actions = element('div', 'actions');
  var off = element('button', 'danger', t('action.thread_off', 'Turn off for this conversation'));
  var keep = element('button', null, t('action.cancel', 'Cancel'));
  off.onclick = function () { changeThread(row, shown, false, [off, keep]); };
  keep.onclick = function () { CONFIRM_ROW = ''; render(); };
  actions.appendChild(off);
  actions.appendChild(keep);
  box.appendChild(actions);
  return box;
}

function changeThread(row, shown, enable, controls) {
  controls.forEach(function (control) { control.disabled = true; });
  setThreadRecovery(row.thread_id, enable).then(function (enabled) {
    NOTICE = shown + ': ' + (enabled ? t('event.thread_enabled', 'Conversation switched back on')
                                     : t('overlay.thread_disabled', 'off for this conversation'));
    // Turning a conversation off cancels what it had waiting, so the list is read again
    // rather than guessed at. If it cannot be read, the confirmed switch is still shown.
    return callTool('list_pending', {}).then(function (payload) {
      if (!Array.isArray(payload.pending)) return;
      DATA.pending = payload.pending;
      if (DATA.status) DATA.status.pending = payload.pending.length;
    }, function () {});
  }, function (error) {
    NOTICE = refusal(error);
  }).then(function () {
    CONFIRM_ROW = '';
    render();
  });
}

function renderGeneral(byName) {
  var entry = byName.interface_language;
  if (!entry) return null;
  var node = card(t('group.general', 'General'));
  var rows = element('div', 'rows');
  var options = (entry.choices || []).map(function (choice) {
    return {value: choice, text: choice === 'system'
      ? withLanguage('choice.language.system', 'System ({language})', DATA.system_language)
      : endonym(choice)};
  });
  rows.appendChild(choiceField(entry, options,
    t('help.interface_language', 'Used by this window, the notification-area popup, notifications and the panel in Codex.'),
    function (chosen) { if (HOOKS.follow) HOOKS.follow(chosen); }).row);
  node.appendChild(rows);
  return node;
}

// Light, Dark, or whatever Codex itself is showing. Applied when the save is confirmed, not
// while the choice is still only on screen: the page shows what is stored.
function renderAppearance(byName) {
  var entry = byName.theme;
  if (!entry || !editable(entry)) return null;
  var node = card(t('group.appearance', 'Appearance'));
  var rows = element('div', 'rows');
  rows.appendChild(choiceField(entry, (entry.choices || []).map(function (choice) {
    return {value: choice, text: t('choice.theme.' + choice, choice)};
  }), t('help.theme', 'Light or dark for this window, the notification-area popup and the panel in Codex.')).row);
  node.appendChild(rows);
  return node;
}

function renderRecovery(status, schema) {
  var node = card(t('group.recovery', 'Automatic recovery'));
  // The control every check box on this card depends on, first. It acts at once -
  // pausing needs no Save and resuming asks for approval - so it is a button beside what
  // it will change, rather than a switch that looks like it waits for Save. What the tile
  // says comes first - the state, and under it what the last press answered - and the
  // button last, pinned to the tile's bottom-right beside that text.
  var master = element('div', 'master');
  var body = element('div', 'master-body');
  var text = element('div', 'master-text');
  var running = status.watcher_running === true;
  text.appendChild(element('span', 'dot' + (!running ? '' : status.enabled ? ' on' : ' paused')));
  text.appendChild(element('span', null, !running
    ? t('status.recovery_idle', 'Nothing will be recovered until it is running')
    : status.enabled ? t('status.recovery_on', 'Automatic recovery is on')
    : t('status.recovery_paused', 'Automatic recovery is paused')));
  body.appendChild(text);
  var note = element('p', 'note');
  note.setAttribute('role', 'status');
  body.appendChild(note);
  master.appendChild(body);
  var pause = element('button', null, status.enabled
    ? t('action.pause', 'Pause recovery') : t('action.resume', 'Resume recovery'));
  pause.disabled = !HOST;
  master.appendChild(pause);
  node.appendChild(master);
  if (HOST) {
    pause.onclick = function () {
      pause.disabled = true;
      setRecoveryEnabled(!status.enabled).then(function () {
        render();
      }, function (error) {
        note.textContent = refusal(error);
        pause.disabled = false;
      });
    };
  }

  var toggles = element('div', 'toggles');
  schema.forEach(function (entry) {
    if (entry.group === 'recovery' && entry.type === 'boolean' && editable(entry)) {
      toggles.appendChild(onOff(entry));
    }
  });
  node.appendChild(toggles);

  var limits = schema.filter(function (entry) { return entry.group === 'limits' && editable(entry); });
  if (limits.length) {
    var fold = folding('limits', t('group.limits', 'Limits'), false, 'inner');
    fold.node.style.marginTop = '4px';
    limits.forEach(function (entry) {
      if (entry.choices) {
        fold.body.appendChild(choiceField(entry, entry.choices.map(function (choice) {
          return {value: choice, text: t('choice.' + choice, choice)};
        }), '').row);
      } else {
        fold.body.appendChild(numberField(entry));
      }
    });
    node.appendChild(fold.node);
  }
  return node;
}

function renderNotifications(schema) {
  var entries = schema.filter(function (entry) { return entry.group === 'notifications' && editable(entry); });
  if (!entries.length) return null;
  var fold = folding('notifications', t('group.notifications', 'Notifications'), false);
  var events = element('div', 'toggles');
  var master = null;
  entries.forEach(function (entry) {
    if (entry.master) {
      master = toggle(entry, function (on) { events.classList.toggle('quiet', !on); });
      events.classList.toggle('quiet', !value(entry.name));
    } else {
      events.appendChild(onOff(entry));
    }
  });
  if (master) fold.body.appendChild(master);
  fold.body.appendChild(events);
  return fold.node;
}

function renderContinuation(byName) {
  if (!byName.continuation_language && !byName.continuation_style) return null;
  var node = card(t('group.continuation', 'Continuation message'));
  var rows = element('div', 'rows');
  node.appendChild(rows);

  var language = byName.continuation_language;
  if (language) {
    var followLabel = function (interfaceChoice) {
      var code = (!interfaceChoice || interfaceChoice === 'system') ? DATA.system_language : interfaceChoice;
      return withLanguage('choice.continuation_language.follow', 'Same as the interface ({language})', code);
    };
    var field = choiceField(language, (language.choices || []).map(function (choice) {
      return {value: choice, text: choice === 'follow' ? followLabel(read('interface_language')) : endonym(choice)};
    }), t('help.continuation_language', 'The language of the message sent to Codex.'));
    var follow = null;
    Array.prototype.forEach.call(field.select.options, function (option) {
      if (option.value === 'follow') follow = option;
    });
    HOOKS.follow = function (chosen) {
      if (follow) follow.textContent = followLabel(chosen);
      field.sync();
    };
    rows.appendChild(field.row);
  }

  var custom = element('div', 'custom');
  var styleHelp = function (style) { return t('help.style.' + style, ''); };
  var showCustom = function () { custom.hidden = read('continuation_style') !== 'custom'; };
  var style = byName.continuation_style;
  if (style) {
    var row = element('div', 'setting stack');
    var heading = element('div', 'setting-text');
    heading.appendChild(element('span', 'setting-label', label(style.name)));
    row.appendChild(heading);
    var help = element('p', 'help', styleHelp(value(style.name)));
    row.appendChild(segmented(style, function (chosen) {
      help.textContent = styleHelp(chosen);
      showCustom();
    }));
    row.appendChild(help);
    rows.appendChild(row);
  }

  // Custom: which stored message is used, and what those messages say - shown, not
  // editable. The text itself is written in the Windows Dashboard.
  var stored = element('div', 'stored');
  var drawStored = function () {
    stored.textContent = '';
    var settings = DATA.settings || {};
    var mode = read('custom_message_mode');
    // A message that is set is shown whole, in a well. One that is not is a single quiet
    // line, so seven empty kinds of interruption do not bury the one that has words.
    var item = function (title, text) {
      var set = typeof text === 'string' && text.trim() !== '';
      var box = element('div', set ? 'stored-item' : 'stored-item unset');
      box.appendChild(element('div', 'stored-title', title));
      box.appendChild(element('div', set ? 'stored-text' : 'stored-empty',
                              set ? text : t('custom.not_set', 'Not set')));
      stored.appendChild(box);
    };
    if (mode === 'per_reason') {
      (DATA.reasons || []).forEach(function (reason) {
        item(t('reason.' + reason, reason), settings['custom_message_' + reason]);
      });
      item(t('choice.custom_mode.global', 'Every interruption'), settings.custom_message);
      stored.appendChild(element('p', 'help', t('custom.fallback', '')));
    } else {
      item(label('custom_message'), settings.custom_message);
    }
  };
  var mode = byName.custom_message_mode;
  if (mode) {
    custom.appendChild(choiceField(mode, (mode.choices || []).map(function (choice) {
      return {value: choice, text: t('choice.custom_mode.' + choice, choice)};
    }), '', drawStored).row);
  }
  custom.appendChild(stored);
  custom.appendChild(element('p', 'callout', t('custom.dashboard_only',
    'Custom messages are written in the Windows Dashboard.')));
  drawStored();
  showCustom();
  rows.appendChild(custom);
  return node;
}

function renderPreviewCard() {
  var node = card(t('preview.title', 'Preview'), 'preview');
  var reasons = DATA.reasons || [];
  if (reasons.indexOf(PREVIEW.reason) < 0) PREVIEW.reason = reasons[0] || '';
  if (reasons.length) {
    var select = document.createElement('select');
    select.id = 'car-preview-reason';
    reasons.forEach(function (reason) {
      var option = element('option', null, t('reason.' + reason, reason));
      option.value = reason;
      if (reason === PREVIEW.reason) option.selected = true;
      select.appendChild(option);
    });
    select.disabled = !HOST;
    select.addEventListener('change', function () {
      PREVIEW.reason = select.value;
      refreshPreview();
    });
    var field = combo(select);
    var built = settingRow(t('preview.for', 'Preview for'), '', field.node, 'has-select');
    field.labelled(built.label, built.help);
    var rows = element('div', 'rows');
    rows.appendChild(built.row);
    node.appendChild(rows);
  }
  var frame = element('div', 'bubble');
  frame.setAttribute('aria-live', 'polite');
  var text = element('p', 'bubble-text');
  text.appendChild(element('span', 'skeleton'));
  text.appendChild(element('span', 'skeleton'));
  frame.appendChild(text);
  node.appendChild(frame);
  var source = element('p', 'help source');
  source.hidden = true;
  node.appendChild(source);
  node.appendChild(element('p', 'help', t('preview.note', 'This is the text that will be sent.')));
  PREVIEW.nodes = {frame: frame, text: text, source: source};
  return node;
}

function showPreview(shown) {
  var nodes = PREVIEW.nodes;
  if (!nodes) return;
  nodes.frame.removeAttribute('aria-busy');
  nodes.frame.className = 'bubble' + (shown ? '' : ' unavailable');
  nodes.text.textContent = shown ? shown.text : t('preview.unavailable', 'Preview is not available right now.');
  var source = shown && ['global', 'per_reason', 'standard'].indexOf(shown.source) >= 0 ? shown.source : '';
  nodes.source.textContent = source ? t('preview.source.' + source, source) : '';
  nodes.source.hidden = !source;
}

// The exact text, from the watcher's own generator, for the choices on screen now. Asked
// again only when the question changed; an answer to a question nobody is asking any more
// is dropped rather than shown over a newer one.
function refreshPreview() {
  if (!PREVIEW.nodes) return;
  if (!HOST || !PREVIEW.reason) {
    showPreview(null);
    return;
  }
  var request = previewArguments(PREVIEW.reason, read);
  var key = JSON.stringify(request);
  if (PREVIEW.last && PREVIEW.last.key === key) {
    showPreview(PREVIEW.last);
    return;
  }
  PREVIEW.nodes.frame.setAttribute('aria-busy', 'true');
  if (PREVIEW.asking === key) return;
  PREVIEW.asking = key;
  callTool('preview_recovery_message', request).then(function (payload) {
    var preview = payload.preview;
    if (!preview || typeof preview.text !== 'string') throw new Error(t('panel.refused', 'refused'));
    return {key: key, text: preview.text, source: preview.source || null};
  }).then(function (shown) {
    if (PREVIEW.asking !== key) return;
    PREVIEW.asking = '';
    PREVIEW.last = shown;
    showPreview(shown);
  }, function () {
    if (PREVIEW.asking !== key) return;
    PREVIEW.asking = '';
    showPreview(null);
  });
}

function renderFooter(schema) {
  var bar = element('footer', 'savebar');
  var save = element('button', null, t('action.save', 'Save'));
  save.disabled = !HOST;
  var message = element('p', 'note');
  message.setAttribute('role', 'status');
  // What happened first, the button last: the commit sits where Windows puts it.
  bar.appendChild(message);
  bar.appendChild(save);
  // Quiet until there is something to save, so a changed switch visibly waits for it.
  HOOKS.dirty = function () { save.className = unsaved(schema) ? 'primary' : ''; };
  HOOKS.dirty();
  return {node: bar, save: save, message: message};
}

// The switches whose change a tool confirmed, moved now that they are drawn in the state they
// showed before. Reading a layout styles the page once in that state - synchronously, nothing
// waits or ticks - so the change is a transition from it rather than a switch drawn already moved.
// With less motion or in High Contrast the stylesheet has no transition, and the change is simply
// made.
function glide() {
  var moves = GLIDES;
  GLIDES = [];
  if (!moves.length) return;
  void moves[0].input.offsetWidth;
  moves.forEach(function (move) { move.input.checked = move.to; });
}

function render() {
  var root = document.getElementById('root');
  root.textContent = '';
  EDITORS = {};
  HOOKS = {};
  PREVIEW.nodes = null;
  WAS = SHOWN;
  SHOWN = {};
  GLIDES = [];
  if (!DATA) {
    root.appendChild(element('p', 'note',
      t('panel.unavailable', 'Settings are not available in this view.')));
    return;
  }
  var status = DATA.status || {};
  var schema = DATA.schema || [];
  var byName = {};
  schema.forEach(function (entry) { byName[entry.name] = entry; });

  var page = element('main', 'page');
  root.appendChild(page);
  // State first; then what is waiting, because it is the part that changes; then what is
  // configured, general to particular; then what the configuration will say; then how the
  // panel looks, where the Windows Dashboard puts it too.
  var hero = renderHero(status);
  page.appendChild(hero.node);
  [renderPending(DATA.pending), renderGeneral(byName), renderRecovery(status, schema),
   renderNotifications(schema), renderContinuation(byName), renderPreviewCard(),
   renderAppearance(byName)
  ].forEach(function (section) { if (section) page.appendChild(section); });
  var footer = renderFooter(schema);
  page.appendChild(footer.node);
  var message = hero.message;

  glide();

  // A message left over from the click that caused this render. It is carried across
  // rather than written before render(), which empties the panel and would discard it.
  if (NOTICE) {
    message.textContent = NOTICE;
    NOTICE = '';
  }
  if (SAVED) {
    footer.message.textContent = SAVED;
    SAVED = '';
    // The redraw replaced the button that was pressed; keep the keyboard where it was.
    if (typeof footer.save.focus === 'function') footer.save.focus({preventScroll: true});
  }

  refreshPreview();

  if (!HOST) {
    message.textContent = t('panel.readonly',
      'Read-only here. Use the Codex Auto Resume settings window to change these.');
    return;
  }

  var save = footer.save;
  save.onclick = function () {
    var before = DATA.settings || {};
    // Only what this panel may write, whatever else a control happens to hold.
    var changes = collectChanges(EDITORS, schema);
    // Nor the language or theme this page merely shows: either may have changed elsewhere.
    var kept = unedited(changes, before);
    kept.forEach(function (name) { delete changes[name]; });
    save.disabled = true;
    footer.message.textContent = t('panel.saving', 'Saving...');
    saveSettings(changes).then(function (payload) {
      DRAFT = {};
      var switched = before.interface_language !== undefined
                     && payload.settings.interface_language !== before.interface_language;
      // One of those did change elsewhere, and its control still shows the old value.
      var behind = kept.some(function (name) { return payload.settings[name] !== before[name]; });
      // The confirmed settings, applied at once: the theme in place, and a new language - or a
      // control left behind by a change made elsewhere - by drawing the page again from them.
      // Every draft was just saved, so a redraw loses nothing.
      if (adopt(payload.settings) || behind) {
        SAVED = t('panel.saved', 'Saved.');
        render();
        return;
      }
      // Only a language this page has no words for still waits for the next time it opens.
      var waits = switched && !localeFor(payload.settings.interface_language, DATA.system_language, CATALOGS);
      footer.message.textContent = waits
        ? t('settings.language_changed', 'Language changed. Anything already open changes the next time it opens.')
        : t('panel.saved', 'Saved.');
      save.disabled = false;
      if (HOOKS.dirty) HOOKS.dirty();
    }, function (error) {
      footer.message.textContent = fill('panel.not_saved', 'Not saved: {reason}',
        {reason: refusal(error)});
      save.disabled = false;
    });
  };

  var start = hero.start;
  if (start) {
    start.onclick = function () {
      start.disabled = true;
      message.textContent = t('panel.starting', 'Starting...');
      callTool('start_watcher', {}).then(function (result) {
        // Do not assume it worked. The panel used to set watcher_running to true here
        // and render a running watcher on the strength of the call not throwing, which
        // is a claim about a process nobody had looked at yet. Ask instead.
        // Hosts differ on whether they hand back the tool result or just its
        // structured half, so look in both rather than depending on one.
        var payload = (result && result.structuredContent) || result || {};
        var state = payload.state;
        if (state === 'running' || state === 'already-running') {
          status.watcher_running = true;
          NOTICE = '';
        } else if (state === 'exited') {
          NOTICE = t('panel.start_exited', 'It started and stopped again; nothing is watching.');
        } else {
          NOTICE = t('panel.start_unconfirmed',
            'Started, but not confirmed running yet. Ask for the status again.');
        }
        // Through NOTICE rather than onto `message`, because render() empties the panel
        // and builds a fresh span: text written here first would be on a node that is
        // detached before the browser paints it, and the click would look like nothing
        // happened - on exactly the two states that most need explaining.
        render();
      }, function (error) {
        message.textContent = fill('panel.start_failed', 'Could not start it: {reason}',
          {reason: refusal(error)});
        start.disabled = false;
      });
    };
  }
}

// The stored theme and language before anything is drawn: the page may be one Codex kept from an
// earlier read, and the tool result is what is true now.
adopt(DATA && DATA.settings);
render();
"""


# Which catalog keys the script can ask for: every key it names, and every key under a prefix it
# completes at runtime (`t('reason.' + category)`, `S['field.' + name]`). Read from the script
# itself, so a word added to the page is a word every language ships with it; the tests hold the
# script to asking only in these two shapes.
_NAMED_KEY = re.compile(r"\b(?:t|fill|withLanguage)\(\s*'([a-z0-9_.]+)'\s*[,)]")
_KEY_PREFIX = re.compile(r"\b(?:t|fill)\(\s*'([a-z0-9_.]+\.)'\s*\+|\bS\['([a-z0-9_.]+\.)'\s*\+")


def panel_keys() -> tuple:
    """The keys the script names, and the prefixes it builds keys from: ``(names, prefixes)``."""
    names = frozenset(_NAMED_KEY.findall(_SCRIPT))
    prefixes = tuple(sorted({named or indexed for named, indexed in _KEY_PREFIX.findall(_SCRIPT)}))
    return names, prefixes


def panel_catalogs() -> dict:
    """Every shipped language's words for this page, and only this page's.

    So a language chosen in the panel is spoken as soon as the save is confirmed, rather than
    the next time Codex opens the panel. Each catalog is English with that language layered
    over it, exactly as `l10n.catalog` gives it to every other surface.
    """
    names, prefixes = panel_keys()
    return {locale: {key: text for key, text in l10n.catalog(locale).items()
                     if key in names or key.startswith(prefixes)}
            for locale in l10n.LOCALES}


def _script_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str).replace("<", "\\u003c")


def settings_page(data=None, theme=None) -> str:
    """The panel as one HTML document.

    ``data`` is only ever used for a preview: in Codex the values arrive from the tool
    result, so the served page carries no settings of its own and cannot go stale
    between being read and being shown.
    """
    # The vocabulary always ships, seed data or not. In Codex the values arrive from the
    # tool result, but the page still has to know what to call them - and the panel must
    # not choose the language for itself. A product that speaks Korean in its
    # notifications and English in its settings panel has picked the worst of both, so
    # the language is resolved once, in Python, and handed here - with every other
    # language's words for this page beside it, for the moment the stored choice changes.
    locale = interface.language()
    catalog = "<script>window.__CODEX_AUTO_RESUME_STRINGS__=%s;</script>" % _script_json(
        l10n.catalog(locale))
    catalogs = ("<script>window.__CODEX_AUTO_RESUME_LOCALE__=%s;"
                "window.__CODEX_AUTO_RESUME_CATALOGS__=%s;</script>"
                % (_script_json(locale), _script_json(panel_catalogs())))
    seed = ""
    if data is not None:
        seed = "<script>window.__CODEX_AUTO_RESUME__=%s;</script>" % _script_json(data)
    # `theme` pins the colour scheme instead of following the host or the stored Theme.
    # Codex never passes it - inside Codex the panel follows the Theme setting, and with
    # Use system setting the host - and the documentation capture does, because a
    # screenshot whose theme depends on whichever machine ran the build is not a
    # deterministic artefact. `data-theme-pinned` tells the script to leave it alone.
    root = ("<html>" if theme not in ("light", "dark")
            else '<html data-theme="%s" data-theme-pinned="">' % theme)
    return (
        "<!doctype html>" + root + "<head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Codex Auto Resume</title><style>%s</style></head>"
        "<body><div id=\"root\"></div>%s%s%s<script>%s</script></body></html>"
        % (_STYLE, catalog, catalogs, seed, _SCRIPT))

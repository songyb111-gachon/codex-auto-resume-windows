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
"""
from __future__ import annotations

import json

from . import brand, interface

# The page is delivered as one resource, so the style lives in it. Every colour comes
# from the shared palette, which is what keeps this panel, the settings window and the
# icon the same product rather than three that happen to ship together.
_STYLE = r"""
/* Three states, not two. An explicit choice stamps `data-theme` on the root; the
   ordinary case stamps nothing and only the media query separates light from dark. A
   colour whose only definition lives inside the media block is the classic unreadable
   panel, so every token is declared here first and only redefined below. */
:root {
  color-scheme: light dark;
  @LIGHT@
  @ELEVATION_LIGHT@
  @SCALE@
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
body { margin: 0; padding: 16px 14px 20px; background: var(--canvas); color: var(--ink);
       font: 14px/1.5 var(--font); -webkit-font-smoothing: antialiased; }
h1, h2, h3, p, ul { margin: 0; }
button, select, input { font: inherit; }
.page { max-width: 820px; margin: 0 auto; display: grid; gap: 14px; }
.help, .note { color: var(--muted); font-size: 12.5px; line-height: 1.45; }
.note:empty { display: none; }
.mono { font-family: var(--mono); font-size: 13px; }

/* The card is one object, repeated: one ground, one hairline, one radius, one soft lift.
   The hairline stays even where the shadow does the visible work - a shadow alone is not
   an edge for everybody, and nothing here may depend on seeing one. */
.card { background: var(--surface); border: 1px solid var(--line);
        border-radius: var(--radius-card); box-shadow: var(--elev-card);
        padding: 16px 18px; min-width: 0; }
@supports (color: color-mix(in srgb, red 50%, blue)) {
  .card { background: var(--card-ground); }
}
.card h2 { font-size: 15px; line-height: 1.35; font-weight: 600; }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.count { min-width: 24px; padding: 0 8px; border-radius: 999px; background: var(--inset);
         color: var(--muted); font-size: 12.5px; line-height: 20px; text-align: center;
         font-variant-numeric: tabular-nums; }

/* State leads. Whether anything is being watched is the reason the panel gets opened,
   so it is the first thing on it and the largest type on it - a word, never a colour
   alone, with the halo saying the same thing for a reader who glances. */
.hero { display: grid; gap: 4px; padding: 16px 20px; }
.eyebrow { font-size: 12.5px; color: var(--muted); }
.hero-state { display: flex; align-items: center; gap: 18px; padding: 8px 0 4px 9px; }
.hero h1 { font-size: 21px; line-height: 1.25; font-weight: 600; letter-spacing: -.01em; }
.facts { display: flex; flex-wrap: wrap; color: var(--muted); }
.facts span:not(:last-child)::after { content: "\00b7"; padding: 0 8px; }
.hero-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.hero-actions > * { margin-top: 6px; }

/* Motion is a state. Monitoring breathes slowly; waiting holds a soft glow; recovering
   pulses harder; paused is still and has no glow at all; a problem pulses once, when it
   is first shown, and then holds - nothing here blinks for attention it already has. */
.halo { --halo-color: var(--idle); position: relative; flex: none; width: 12px; height: 12px;
        border-radius: 50%; background: var(--halo-color); }
.halo::before { content: ""; position: absolute; inset: -9px; border-radius: 50%;
                background: var(--halo-color); opacity: var(--halo-min); }
.halo.monitoring { --halo-color: var(--active); }
.halo.monitoring::before { animation: breathe var(--breathe) ease-in-out infinite alternate; }
.halo.waiting { --halo-color: var(--waiting); }
.halo.waiting::before { opacity: calc((var(--halo-min) + var(--halo-max)) / 2); }
.halo.recovering { --halo-color: var(--active); }
.halo.recovering::before { animation: surge var(--pulse) ease-in-out infinite alternate; }
.halo.paused { --halo-color: var(--paused); }
.halo.paused::before { display: none; }
.halo.attention { --halo-color: var(--attention); }
.halo.attention::before { opacity: calc((var(--halo-min) + var(--halo-max)) / 2); }
.halo.attention.once::before { animation: once var(--pulse) ease-out 1; }
@keyframes breathe {
  from { opacity: var(--halo-min); transform: scale(.78); }
  to { opacity: var(--halo-max); transform: scale(1); }
}
@keyframes surge {
  from { opacity: var(--halo-min); transform: scale(.7); }
  to { opacity: calc(var(--halo-max) + .2); transform: scale(1.18); }
}
@keyframes once {
  from { opacity: calc(var(--halo-max) + .2); transform: scale(.5); }
  to { opacity: calc((var(--halo-min) + var(--halo-max)) / 2); transform: scale(1); }
}

/* Controls rest on the card; values sit in wells. */
button { min-height: 34px; padding: 6px 16px; border-radius: var(--radius-control);
         border: 1px solid var(--line); background: var(--raised); color: var(--ink);
         box-shadow: var(--elev-control); font-weight: 500; line-height: 20px; cursor: pointer;
         transition: background-color var(--transition), border-color var(--transition),
                     box-shadow var(--transition), color var(--transition); }
button:hover:not([disabled]) { background: var(--surface); }
button:active:not([disabled]) { background: var(--inset); box-shadow: var(--elev-inset); }
button.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
button.primary:hover:not([disabled]) { background: var(--accent); filter: brightness(1.07); }
button.danger { color: var(--danger); }
button[disabled] { opacity: .5; cursor: default; box-shadow: none; }
:focus { outline: none; }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }

select, input[type=number] { min-height: 34px; padding: 6px 12px; color: var(--ink);
        background-color: var(--inset); border: 1px solid var(--line);
        border-radius: var(--radius-control); box-shadow: var(--elev-inset);
        transition: border-color var(--transition), box-shadow var(--transition); }
select { appearance: none; -webkit-appearance: none; max-width: 100%; min-width: 0;
         padding-right: 34px; cursor: pointer; text-overflow: ellipsis;
         background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%),
                           linear-gradient(135deg, var(--muted) 50%, transparent 50%);
         background-position: calc(100% - 18px) 55%, calc(100% - 13px) 55%;
         background-size: 5px 5px; background-repeat: no-repeat; }
select option { background-color: var(--surface); color: var(--ink); }
input[type=number] { width: 88px; text-align: right; font-variant-numeric: tabular-nums; }
select:disabled, input[type=number]:disabled { opacity: .6; cursor: default; }

input.switch { appearance: none; -webkit-appearance: none; position: relative; flex: none;
               width: 40px; height: 22px; margin: 0; border-radius: 999px; cursor: pointer;
               background: var(--inset); border: 1px solid var(--line); box-shadow: var(--elev-inset);
               transition: background-color var(--transition), border-color var(--transition); }
input.switch::before { content: ""; position: absolute; top: 2px; left: 2px; width: 16px;
                       height: 16px; border-radius: 50%; background: var(--muted);
                       transition: transform var(--transition), background-color var(--transition); }
input.switch:checked { background: var(--accent); border-color: var(--accent); box-shadow: none; }
input.switch:checked::before { transform: translateX(18px); background: var(--on-accent); }
input.switch:disabled { opacity: .5; cursor: default; }

/* A setting is a row: what it is on the left, the control on the right. When there is no
   room for both, the control moves under its name rather than pushing past the edge. */
.rows > .setting + .setting, .rows > .setting + .custom, .toggles > .setting,
.custom > .setting + .setting { border-top: 1px solid var(--line); }
.setting { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
           gap: 6px 16px; padding: 11px 0; min-width: 0; }
label.setting { cursor: pointer; }
.setting-text { flex: 1 1 180px; min-width: 0; display: grid; gap: 2px; }
.setting-label { font-weight: 500; }
.setting-control { flex: 0 1 auto; display: flex; min-width: 0; max-width: 100%; margin-left: auto; }
.has-select .setting-control { flex: 0 1 280px; }
.has-select select { width: 100%; }
.setting.stack { display: grid; grid-template-columns: minmax(0, 1fr); justify-content: stretch; gap: 8px; }
.card > h2 + *, .card-head + * { margin-top: 6px; }

.toggles { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
           column-gap: 28px; }
.toggles .setting { flex-wrap: nowrap; }
.toggles.quiet .setting-label { color: var(--muted); }

.master { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; margin: 10px 0 6px;
          padding: 10px 12px 10px 14px; background: var(--raised); border: 1px solid var(--line);
          border-radius: var(--radius-control); }
.master-text { flex: 1 1 200px; display: flex; align-items: center; gap: 10px; min-width: 0;
               font-weight: 500; }
.master .note { flex: 1 1 100%; }
.dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--idle); }
.dot.on { background: var(--active); }
.dot.paused { background: var(--paused); }

.segmented { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
.segment { position: relative; display: flex; min-width: 0; }
.segment input { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0;
                 cursor: pointer; }
.segment span { flex: 1; min-width: 0; padding: 7px 8px; text-align: center; line-height: 20px;
                font-weight: 500; overflow-wrap: anywhere; color: var(--ink);
                border-radius: var(--radius-control); border: 1px solid var(--line);
                background: var(--raised); box-shadow: var(--elev-control);
                transition: background-color var(--transition), box-shadow var(--transition),
                            color var(--transition), border-color var(--transition); }
.segment input:hover:not(:disabled) + span { background: var(--surface); }
.segment input:checked + span { background: var(--inset); box-shadow: var(--elev-inset);
                                color: var(--accent); border-color: var(--accent); font-weight: 600; }
.segment input:focus-visible + span { outline: 2px solid var(--focus); outline-offset: 2px; }
.segment input:disabled { cursor: default; }
.segment input:disabled + span { opacity: .6; }

/* Folding sections: what is rarely changed stays one line tall until it is wanted. */
details.fold > summary { display: flex; align-items: center; justify-content: space-between;
                         gap: 12px; list-style: none; cursor: pointer; }
details.fold > summary::-webkit-details-marker { display: none; }
.chevron { flex: none; width: 8px; height: 8px; margin-right: 6px;
           border-right: 2px solid var(--muted); border-bottom: 2px solid var(--muted);
           transform: translateY(-2px) rotate(45deg); transition: transform var(--transition); }
details.fold:not([open]) > summary .chevron { transform: rotate(-45deg); }
details.card.fold { padding: 0; }
details.card.fold > summary { padding: 16px 18px; border-radius: var(--radius-card); }
details.card.fold[open] > summary { padding-bottom: 4px; }
details.card.fold > .fold-body { padding: 0 18px 8px; }
details.inner { border-top: 1px solid var(--line); }
details.inner > summary { padding: 12px 0; border-radius: var(--radius-small); }
details.inner > summary h3 { font-size: 14px; font-weight: 600; }
details.inner > .fold-body { padding-bottom: 2px; }
details.inner > .fold-body > .setting { border-top: 1px solid var(--line); }

/* What is waiting, as soft rows rather than a table. Wide content wraps inside its row;
   the panel itself never scrolls sideways. */
.prows { list-style: none; padding: 0; display: grid; gap: 8px; }
.prow { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; min-width: 0;
        padding: 10px 12px 10px 14px; background: var(--raised); border: 1px solid var(--line);
        border-radius: var(--radius-control); }
.prow-main { flex: 1 1 220px; min-width: 0; display: grid; gap: 3px; }
.prow-title { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; min-width: 0; }
.prow-name { font-weight: 600; min-width: 0; max-width: 100%; overflow: hidden;
             text-overflow: ellipsis; white-space: nowrap; }
.prow-meta { display: flex; flex-wrap: wrap; gap: 0 14px; color: var(--muted); font-size: 12.5px;
             font-variant-numeric: tabular-nums; }
.prow-meta b { font-weight: 500; color: var(--ink); }
.prow-switch { display: flex; align-items: center; gap: 10px; margin-left: auto;
               color: var(--muted); font-size: 12.5px; cursor: pointer; }
.prow-confirm { flex: 1 1 100%; display: grid; gap: 8px; padding-top: 10px;
                border-top: 1px solid var(--line); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }

.chip { --chip: var(--paused); display: inline-block; max-width: 100%; padding: 1px 9px;
        border-radius: 999px; font-size: 12.5px; line-height: 20px; font-weight: 500;
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
.stored-title { font-size: 12.5px; font-weight: 500; color: var(--muted); }
.stored-text { padding: 9px 12px; border-radius: var(--radius-control); background: var(--inset);
               border: 1px solid var(--line); white-space: pre-wrap; overflow-wrap: anywhere;
               max-height: 10.5em; overflow: auto; }
.stored-item.unset { grid-template-columns: minmax(0, 1fr) auto; align-items: baseline; gap: 12px; }
.stored-item.unset .stored-title { color: var(--ink); font-size: 14px; font-weight: 400; }
.stored-empty { color: var(--muted); font-size: 12.5px; }
.callout { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; margin-bottom: 10px;
           border-radius: var(--radius-control); background: var(--accent-soft); color: var(--ink);
           font-size: 12.5px; line-height: 1.45; }
.callout::before { content: "i"; flex: none; width: 18px; height: 18px; border-radius: 50%;
                   background: var(--accent); color: var(--on-accent); font: 600 12px/18px var(--font);
                   text-align: center; }

.bubble { margin-top: 10px; padding: 12px 14px; border-radius: var(--radius-control);
          background: var(--inset); border: 1px solid var(--line); box-shadow: var(--elev-inset); }
.bubble-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.55;
               transition: opacity var(--transition); }
.bubble[aria-busy="true"] .bubble-text { opacity: .55; }
.bubble.unavailable .bubble-text { color: var(--muted); }
.skeleton { display: block; height: 9px; margin: 6px 0; border-radius: 6px; background: var(--line); }
.skeleton + .skeleton { width: 62%; }
.preview .source { margin-top: 10px; color: var(--ink); font-weight: 500; }
.preview .source + .help, .preview .bubble + .help { margin-top: 8px; }

.savebar { position: sticky; bottom: 10px; z-index: 1; display: flex; flex-wrap: wrap;
           align-items: center; gap: 8px 14px; padding: 10px 12px; background: var(--surface);
           border: 1px solid var(--line); border-radius: var(--radius-card);
           box-shadow: var(--elev-card); }
.savebar .note { flex: 1 1 200px; min-width: 0; }
.savebar button { margin-left: auto; }

@media (max-width: 520px) {
  body { padding: 10px 10px 16px; }
  .card { padding: 14px; }
  .hero { padding: 14px 16px; }
  .hero h1 { font-size: 20px; }
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

/* A person who asked Windows for less motion gets none: every halo holds still at the
   middle of its range, and nothing slides. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
  .halo::before { opacity: calc((var(--halo-min) + var(--halo-max)) / 2); transform: none; }
}
"""

# The lift of a surface, per theme. Light is the soft interface: a shadow down and right
# at a little over half strength and a highlight up and left. Dark is mostly the hairline -
# a shadow on a near-black ground is invisible at best and muddy at worst - so it keeps a
# faint drop and a one-pixel top light, and the card itself comes up a step toward `raised`.
_ELEVATION_LIGHT = (
    "--elev-card: 4px 4px 14px color-mix(in srgb, var(--shadow-dark) 55%, transparent), "
    "-4px -4px 14px color-mix(in srgb, var(--shadow-light) 90%, transparent); "
    "--elev-control: 2px 2px 6px color-mix(in srgb, var(--shadow-dark) 45%, transparent), "
    "-2px -2px 6px color-mix(in srgb, var(--shadow-light) 90%, transparent); "
    "--elev-inset: inset 2px 2px 6px color-mix(in srgb, var(--shadow-dark) 38%, transparent), "
    "inset -2px -2px 6px color-mix(in srgb, var(--shadow-light) 50%, transparent); "
    "--card-ground: var(--surface);")
_ELEVATION_DARK = (
    "--elev-card: 0 1px 2px color-mix(in srgb, var(--shadow-dark) 70%, transparent), "
    "0 6px 18px color-mix(in srgb, var(--shadow-dark) 35%, transparent), "
    "inset 0 1px 0 color-mix(in srgb, var(--shadow-light) 45%, transparent); "
    "--elev-control: 0 1px 2px color-mix(in srgb, var(--shadow-dark) 60%, transparent); "
    "--elev-inset: inset 0 1px 2px color-mix(in srgb, var(--shadow-dark) 55%, transparent); "
    "--card-ground: color-mix(in srgb, var(--raised) 22%, var(--surface));")

# Resolved once, at import: the palette is a build-time fact, not a per-request one.
_STYLE = (_STYLE.replace("@LIGHT@", brand.css_variables(brand.LIGHT))
                .replace("@DARK@", brand.css_variables(brand.DARK))
                .replace("@ELEVATION_LIGHT@", _ELEVATION_LIGHT)
                .replace("@ELEVATION_DARK@", _ELEVATION_DARK)
                .replace("@SCALE@", brand.css_scale()))

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
var PREVIEW = {reason: '', nodes: null, last: null, asking: ''};
// The settings whose unsaved value changes the Preview.
var PREVIEW_FIELDS = ['interface_language', 'continuation_language', 'continuation_style',
                      'custom_message_mode'];

// Every word on this panel comes from Python, in the language Python resolved. The panel
// does not consult the browser's language: the notifications, the setup output, the
// standalone window and this page all have to agree, and only one of them can decide.
var S = window.__CODEX_AUTO_RESUME_STRINGS__ || {};

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
  if (!entry || typeof entry.name !== 'string') return false;
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
  return {row: row, help: helpNode};
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
  var built = settingRow(label(entry.name), help, input, 'has-select');
  built.select = input;
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
  var halo = element('span', 'halo ' + state + (state === 'attention' && LAST_STATE !== 'attention' ? ' once' : ''));
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
  input.checked = row.thread_enabled;
  input.disabled = !HOST;
  input.addEventListener('change', function () {
    // The switch shows what a tool last confirmed, until a tool confirms something else.
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

function renderRecovery(status, schema) {
  var node = card(t('group.recovery', 'Automatic recovery'));
  // The switch every other switch on this card depends on, first. It acts at once -
  // pausing needs no Save and resuming asks for approval - so it is a button beside what
  // it will change, rather than one more switch that looks like it waits for Save.
  var master = element('div', 'master');
  var text = element('div', 'master-text');
  var running = status.watcher_running === true;
  text.appendChild(element('span', 'dot' + (!running ? '' : status.enabled ? ' on' : ' paused')));
  text.appendChild(element('span', null, !running
    ? t('status.recovery_idle', 'Nothing will be recovered until it is running')
    : status.enabled ? t('status.recovery_on', 'Automatic recovery is on')
    : t('status.recovery_paused', 'Automatic recovery is paused')));
  master.appendChild(text);
  var pause = element('button', null, status.enabled
    ? t('action.pause', 'Pause recovery') : t('action.resume', 'Resume recovery'));
  pause.disabled = !HOST;
  master.appendChild(pause);
  var note = element('p', 'note');
  note.setAttribute('role', 'status');
  master.appendChild(note);
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
      toggles.appendChild(toggle(entry));
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
      events.appendChild(toggle(entry));
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
    HOOKS.follow = function (chosen) { if (follow) follow.textContent = followLabel(chosen); };
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
    var rows = element('div', 'rows');
    rows.appendChild(settingRow(t('preview.for', 'Preview for'), '', select, 'has-select').row);
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

function render() {
  var root = document.getElementById('root');
  root.textContent = '';
  EDITORS = {};
  HOOKS = {};
  PREVIEW.nodes = null;
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
  // configured, general to particular; then what the configuration will say.
  var hero = renderHero(status);
  page.appendChild(hero.node);
  [renderPending(DATA.pending), renderGeneral(byName), renderRecovery(status, schema),
   renderNotifications(schema), renderContinuation(byName), renderPreviewCard()
  ].forEach(function (section) { if (section) page.appendChild(section); });
  var footer = renderFooter(schema);
  page.appendChild(footer.node);
  var message = hero.message;

  // A message left over from the click that caused this render. It is carried across
  // rather than written before render(), which empties the panel and would discard it.
  if (NOTICE) {
    message.textContent = NOTICE;
    NOTICE = '';
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
    save.disabled = true;
    footer.message.textContent = t('panel.saving', 'Saving...');
    saveSettings(changes).then(function (payload) {
      DRAFT = {};
      var switched = before.interface_language !== undefined
                     && payload.settings.interface_language !== before.interface_language;
      footer.message.textContent = switched
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

render();
"""


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
    # the language is resolved once, in Python, and handed here.
    catalog = "<script>window.__CODEX_AUTO_RESUME_STRINGS__=%s;</script>" % json.dumps(
        interface.catalog(), ensure_ascii=False).replace("<", "\\u003c")
    seed = ""
    if data is not None:
        seed = "<script>window.__CODEX_AUTO_RESUME__=%s;</script>" % json.dumps(
            data, ensure_ascii=False, default=str).replace("<", "\\u003c")
    # `theme` pins the colour scheme instead of following the host. Codex never passes
    # it - inside Codex the panel follows the host, which is the point - and the
    # documentation capture does, because a screenshot whose theme depends on whichever
    # machine ran the build is not a deterministic artefact.
    root = "<html>" if theme not in ("light", "dark") else '<html data-theme="%s">' % theme
    return (
        "<!doctype html>" + root + "<head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Codex Auto Resume</title><style>%s</style></head>"
        "<body><div id=\"root\"></div>%s%s<script>%s</script></body></html>"
        % (_STYLE, catalog, seed, _SCRIPT))

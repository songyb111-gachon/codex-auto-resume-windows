# The look of it

One palette, one scale, one mark, five surfaces. This is where the decisions are written down
so a future change can argue with them rather than guess at them.

## The idea

The product waits, and then it acts. That is the whole behaviour, so it is the whole
palette: **deep blue at rest, cyan at the moment it does something.** The ramp is not
decoration — a reader who learns that bright means active has learned what the tool does.

Until v0.5.2 the product was green, and each surface carried its own copy of the colours:
the settings window in C# literals, the Codex panel in a stylesheet, the icon renderer,
the plugin manifest. They had already drifted — the manifest's brand colour and the panel's
accent agreed with each other and with nothing else.

v0.6.3 kept the palette's idea and changed its material. The Dashboard, the notification-area
popup and the panel in Codex share one soft visual language: a card is the same material as the
window behind it, lifted by a small shadow rather than laid on it as a white sheet; a control
rests on the card; a value sits in a shallow well; a state is a word on a tinted chip; and the
state dot breathes while the watcher is watching. The flat cards with an accent rail that came
before are gone.

v0.6.4 made them one material rather than three similar ones. The panel in Codex was the
reference: its shadows, sizes and control recipes moved into `brand.py` as data, and the
Dashboard and the popup now draw the same lifted cards, the same shallow wells and the same
switches from those numbers. Each surface kept its own text sizes and its own layout. The state
light kept its shape and got back the colour it had before v0.6.3: cyan whenever the watcher is
running, with a soft glow, and grey when it is paused or stopped.

## Where a colour comes from

`src/codex_auto_resume/brand.py` and nowhere else — and since v0.6.3, every size, radius and
duration as well.

| Surface | How it gets the palette |
| --- | --- |
| The Codex panel | `mcpui.py` builds its `:root` block at import from `brand.LIGHT` and `brand.DARK`, `brand.css_scale()` and `brand.css_elevation()`, which writes the shadow recipes as CSS. |
| The Dashboard | `build/make_brand.py` generates `gui/Brand.cs`: every light token as a `Color`; the scale, the layout sizes, the shadow recipes and the state light's numbers as constants; and the state light's per-state rules as small generated methods. `gui/Controls.cs` reads the colours through one `Palette` class, which is also the one place High Contrast is honoured. The generated file is committed, so a contributor with no Python can still read what the window will look like. |
| The notification-area popup | `tray_popup.py` imports `brand` and draws with `brand.LIGHT`, the scale, the shadow recipes and `brand.glow()` directly. |
| The icon | `assets/make_icon.py` imports the four icon colours directly. |
| The plugin card | `.codex-plugin/plugin.json` carries `brandColor`, checked against `brand.BRAND`. |

`tests/test_brand.py` regenerates both generated files and compares, so a hand-edit fails
the suite instead of shipping. It also sweeps every tracked text file for the retired
green, because the way a colour survives a rebrand is in a document nobody reopened.

## The tokens

`LIGHT` and `DARK` hold the same key set — a token defined in one theme and not the other
renders one theme's text on the other theme's ground, which is the classic unreadable-panel
bug, and there is a test for it.

| Token | Light | Dark | Used for |
| --- | --- | --- | --- |
| `ink` | `#0F1B2D` | `#E8EEF6` | Text. A near-black carrying the same blue bias. |
| `muted` | `#536477` | `#9AACBF` | Secondary text, readable on the canvas as well as on a card. |
| `line` | `#D3DCE7` | `#2E3A4B` | Hairlines and card edges. |
| `surface` | `#F6F8FB` | `#191F29` | Cards. |
| `canvas` | `#E9EEF4` | `#0C1118` | The window behind them. |
| `raised` | `#FBFCFE` | `#212835` | A control resting on a card: a button, a chip, a toggle. |
| `inset` | `#E2E8F0` | `#121820` | Pressed, selected, or a well a value sits in. |
| `shadow_dark` | `#B7C4D4` | `#05080C` | The shadow below and right of a raised surface. |
| `shadow_light` | `#FFFFFF` | `#27303D` | The highlight above and left of it. |
| `accent` | `#1257B8` | `#5CA2EE` | Anything to read or to click. |
| `accent_hover` | `#135DC5` | `#62ADFF` | A primary button under the pointer: the accent brightened by 7%. |
| `accent_pressed` | `#1250A7` | `#5290D3` | A primary button being pressed: the accent mixed 12% toward the ink (light) or the dark shadow (dark). |
| `accent_soft` | `#DCE8F8` | `#1B2D45` | A quiet accent ground: a selected row, the active tab. |
| `on_accent` | `#FFFFFF` | `#08111C` | Text drawn *on* the accent. |
| `focus` | `#2F7DE1` | `#7DB6F5` | The keyboard focus ring. |
| `active` | `#06B6D4` | `#35B5CC` | Fill only: the state light while the watcher is running and recovery is on. |
| `idle` | `#94A3B8` | `#5F6E80` | Fill only: a stopped watcher's light. |
| `attention` | `#B45309` | `#E09B57` | Fill only: needs a person. |
| `success` | `#157045` | `#5CC98E` | State text: recovered. |
| `waiting` | `#1A5FA8` | `#7DB6F5` | State text: waiting for a reset or a retry. |
| `warning` | `#9A4A06` | `#E8A765` | State text: needs a decision soon. |
| `danger` | `#B42318` | `#F2877C` | State text: stopped, failed. |
| `paused` | `#55657A` | `#9AACBF` | State text: deliberately quiet. |

**The surfaces moved toward each other in v0.6.3.** The card came down from pure white and the
canvas down a step, because a raised card in a soft interface is the window's own material
lifted by light and shadow. The hairline stayed: a shadow alone is not an edge for everybody.

**`active` is a fill-only token.** Against white it measures 2.4:1, which is right for a
status dot and not enough for text. The five state colours are the other way round: each one
carries a word, so each is readable on a card, at 5.6:1 or better in the light theme and 6.7:1
or better in the dark. The tests assert contrast for text, secondary text, the accent and the
text on it, so a later adjustment "for looks" cannot quietly make the panel unreadable.

**`on_accent` exists because of a bug the tests found.** A dark theme needs a bright accent
to stand off its surface, and a bright accent cannot then carry white text: white on
`#5AA5F5` is 2.6:1. So the text on the accent is a token that goes dark exactly when the
accent goes light. Nobody noticed by looking; the assertion did.

## The scale

Everything that is not a colour, in device-independent pixels at 96 DPI, so a card in the
window and a card in Codex round their corners by the same amount.

| Table | Values | Used for |
| --- | --- | --- |
| `RADII` | card 16, control 11, chip 999, small 7 | Corners. A chip is a pill. |
| `SPACING` | 4, 8, 12, 16, 24, 32 (`xs` to `xxl`) | Padding and gaps. |
| `TYPE` | title 20, heading 14, body 12, small 11 | The Dashboard's and the popup's type sizes. |
| `TYPE_SCALE`, `LINE_HEIGHT`, `TYPE_ROLES` | display 21, title 15, body 14, small 12.5, mono 13 | The panel's type. The native surfaces keep `TYPE`: a notification-area popup and a fixed-size window read better with smaller text than a panel inside Codex. |
| `LAYOUT` | button 34 high, field 35, switch 40 × 22, chip 22, card padding 16 × 18, page gap 14, and the rest | The sizes of the shared control recipes, taken from the panel. |
| `SHADOWS` | light card: offset (4, 4), blur 14, `shadow_dark` at 0.55, and offset (−4, −4), blur 14, `shadow_light` at 0.90; control: the same at offset 2, blur 6; inset: offset 2, blur 6, inside the edge | A lifted card, a raised control and a well. Small on purpose: exaggerated embossing is what makes soft interfaces unreadable. |
| `STATUS_DOT`, `STATUS_FILL`, `GLOW` | dot radius: window 5, popup 4.5, panel 6; the glow reaches 7 beyond the dot | The state light: its size, its colour for each state, and its glow. |
| `MOTION` | transition 160 ms | Control transitions in the panel. |

The window gets these as constants in `gui/Brand.cs` - `RadiusCard`, `SpaceM`, `TypeBody`,
`ButtonHeight`, `FieldHeight`, the shadow recipes and the glow's numbers - and multiplies them
by its own scale factor. The popup reads the same tables from `brand.py`. The panel gets CSS
custom properties from `brand.css_scale()`: `--radius-*`, `--space-*`, `--type-*`, `--lh-*`,
`--size-*`, `--glow-*` and `--transition`.

The attention pulse's duration is `--glow-attention-ms`, never `--attention`, because the
palette already declares `--attention` as a colour on the same `:root`. Two custom properties
with one name raise nothing: the later declaration wins, the dark theme declares the colour
again, and an animation handed a colour for its duration simply does not run. v0.6.3 met this
and named the duration `--pulse`.

A shadow is data, not a stylesheet. `brand.shadow_alpha()` is the model - a CSS blur is a
Gaussian with a standard deviation of half the blur - and `brand.css_elevation()` writes the
recipes as the panel's `box-shadow` values. The Dashboard and the popup render the same recipes
into cached images and stamp them around each card and control, and tests hold what they draw to
the model within two levels of 255 at 100%, 150% and 200%. In the dark theme a lift is mostly the
hairline and a one-pixel top light, because a shadow on a near-black ground is invisible at best
and muddy at worst.

## Motion is a state

The state light says whether the watcher is alive, in the Dashboard's header, at the top of the
popup and at the top of the panel. It is a flat dot with a soft glow around it, and the glow is
the only thing that moves. `brand.glow()` defines it once, and all three surfaces are tested
against that one function:

| State | Colour | Glow |
| --- | --- | --- |
| Monitoring | `active` | Breathes slowly: opacity 0.14 to 0.30 over 3.6 s, the glow growing from 94% to its full size |
| Waiting | `active` | Still, at 0.20 |
| Checking a task that has come due | `active` | Still, at 0.20, with a thin arc turning once every 1.6 s (in the Dashboard and the popup) |
| Recovering | `active` | Breathes a little faster: 0.18 to 0.38 over 2.2 s |
| Needs a person | `attention` | One soft pulse from 0.20 to 0.42 and back over 1.4 s, then still |
| Paused, stopped | `paused`, `idle` | None |

The glow fades out over 7 pixels beyond the dot, with no edge anywhere. Nothing blinks, and the
light always has its word beside it.

All of it stops on request. The Dashboard and the popup stop every animation when **Reduce
motion** is on (Settings > Appearance) or when Windows' own animation-effects switch is off, and
the Dashboard also stops it in High Contrast. The panel follows the host's
`prefers-reduced-motion` instead, which is why the setting is not offered there.

## High Contrast, and a window that stays light

In High Contrast the Dashboard drops its shadows and tints, stops its motion and draws with
system colours throughout; `Palette` in `gui/Controls.cs` is where that swap happens. Since
v0.6.4 the popup makes the same swap, with the same mapping, and the panel has a forced-colors
style, so its lights, switch knobs and drop-down arrows stay visible. In all three the state
light becomes a solid dot in a system colour, with no glow.

The Dashboard is light-only, and that is a measurement rather than an opinion. A probe built for
v0.5.6 painted a card, a spin box, a drop-down, a check box and a button in the dark palette and
photographed the result. The body went dark; the parts Windows draws itself - the spinner's
buttons, the drop-down's arrow, the check-box glyph - stayed light, which is worse than an
honestly light window and not fixable without owner-drawing every native control. v0.6.3's soft
controls paint over the standard controls rather than replacing them, so that finding still
stands. The popup draws with the light palette too. The dark half of the palette is not unused:
the panel in Codex is HTML and follows Codex's own theme.

## The mark

A rounded-square badge in deep blue carrying an open ring with a bright head at its leading
end. The ring is the wait; the gap at the top is the interruption; the cyan head is the
moment it resumes.

`assets/brand/icon.svg` is the vector master and `assets/codex-auto-resume.ico` the Windows
raster set, both generated from the same nine numbers in `assets/make_icon.py` — one
geometry, not a drawing and a copy of it.

**Why this shape and not the other three.** Four concepts were built and rendered at all
nine icon sizes on both a light and a dark ground; `build/icon_concepts.py` still renders
the sheet, so the comparison can be repeated rather than believed.

| Concept | Why not |
| --- | --- |
| A **pause-then-play** pair | The most legible at 16px and the least distinctive anywhere. It is the most common glyph pair in software and it says "media player". |
| A **chevron inside a ring** | Handsome at 256 and gone by 24: the chevron and the ring merged into one blob. |
| An **arrowhead on an open arc** (the mark up to v0.5.1) | Reads as a flag at large sizes. A triangle joined to a curve at an angle stops looking joined. |
| An **open ring with a round head** | Chosen. It survives sixteen pixels *and* stays specific — a circle is the one shape that cannot lose its silhouette when it is four pixels across. |

The head sits at the end of the sweep rather than inside the gap, so it reads as leading
the ring rather than floating beside it.

## Rules that are not about colour

- **State leads.** In the Dashboard, the popup and the panel, what the watcher is doing is the
  first thing and the largest type. It used to be a muted sentence along the bottom of the
  window, under sixteen checkboxes — which put the one thing a person opens the window to check
  below everything they did not come for.
- **No colour without a word.** A state is a word on a chip tinted with its own colour, and the
  dot always has its word beside it. `active` never carries text, which is why the popup keeps
  separate tables for a dot's fill and its word's ink.
- **Nothing depends on seeing a shadow.** Every card and control keeps a hairline edge, and the
  keyboard focus ring has its own token, `focus`.
- **Order is an argument.** The panel runs: the state; then what is waiting, because it is the
  part that changes; then what is configured, general to particular; then what that
  configuration will say. The Dashboard's Settings is split into General, Automatic recovery,
  Continuation message, Appearance and Advanced.
- **Every status fact is its own label in its own cell.** A single concatenated string
  wraps or truncates as the window narrows, and what disappears first is the version — the
  part people are asked for when reporting a problem.
- **The card is one object, repeated.** Same ground, same hairline, same radius and the same
  lift on all three surfaces, so the eye reads a list of sections rather than a pile of boxes.
- **A standard control underneath.** In the Dashboard a button is still a `Button`, a switch is a
  `CheckBox` drawn as a switch, and a drop-down is a `ComboBox` whose closed face we draw; only
  the painting is ours, so the keyboard, focus and screen readers behave as they always did.

## Redrawing anything

```bash
python assets/make_icon.py     # icon, logos, vector master
python build/make_brand.py     # gui/Brand.cs: the palette and the scale
python build/icon_concepts.py  # the concept comparison sheet
```

Screenshots are captured with `build/capture_window.ps1`, which declares itself DPI aware
before measuring. A DPI-unaware capture is told a scaled-down window rectangle, allocates a
bitmap that size and returns a picture of the window's top-left corner — which looks
exactly like a window whose layout is broken, and cost an afternoon once.

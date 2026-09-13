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

## Where a colour comes from

`src/codex_auto_resume/brand.py` and nowhere else — and since v0.6.3, every size, radius and
duration as well.

| Surface | How it gets the palette |
| --- | --- |
| The Codex panel | `mcpui.py` builds its `:root` block at import from `brand.LIGHT` and `brand.DARK`, `brand.css_scale()`, and two elevation blocks of its own whose shadows are mixed from the `shadow_dark` and `shadow_light` tokens. |
| The Dashboard | `build/make_brand.py` generates `gui/Brand.cs`: every light token as a `Color`, and the scale as constants. `gui/Controls.cs` reads the colours through one `Palette` class, which is also the one place High Contrast is honoured. The generated file is committed, so a contributor with no Python can still read what the window will look like. |
| The notification-area popup | `tray_popup.py` imports `brand` and draws with `brand.LIGHT` and the scale directly. |
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
| `accent_soft` | `#DCE8F8` | `#1B2D45` | A quiet accent ground: a selected row, the active tab. |
| `on_accent` | `#FFFFFF` | `#08111C` | Text drawn *on* the accent. |
| `focus` | `#2F7DE1` | `#7DB6F5` | The keyboard focus ring. |
| `active` | `#06B6D4` | `#35B5CC` | Fill only: running, work in flight. |
| `idle` | `#94A3B8` | `#5F6E80` | Fill only: stopped. |
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
| `TYPE` | title 20, heading 14, body 12, small 11 | Type sizes. |
| `ELEVATION` | raised: 4 offset, 14 blur; inset: 2 offset, 6 blur; shadow opacity 0.55 | A raised surface, and a well. Small on purpose: exaggerated embossing is what makes soft interfaces unreadable. |
| `MOTION` | breathe 2400 ms, attention 1200 ms, transition 160 ms | The state dot, and control transitions. |
| `HALO` | opacity 0.12 to 0.34, radius 9 | The glow around the state dot. |

The window gets these as constants in `gui/Brand.cs` - `RadiusCard`, `SpaceM`, `TypeBody`,
`RaisedBlur`, `ShadowOpacity`, `BreatheMs`, `AttentionMs`, `HaloMin` and the rest - and
multiplies them by its own scale factor. The popup reads the same tables from `brand.py`. The
panel gets CSS custom properties from `brand.css_scale()`: `--radius-*`, `--space-*`,
`--type-*`, `--breathe`, `--pulse`, `--transition`, `--halo-min` and `--halo-max`.

The attention duration is `--pulse`, not `--attention`, because the palette already declares
`--attention` as a colour on the same `:root`. Two custom properties with one name raise
nothing: the later declaration wins, the dark theme declares the colour again, and an animation
handed a colour for its duration simply does not run.

The panel writes its shadows in its own stylesheet, from the shadow tokens. In the light theme
they use the offsets and blurs in the table; in the dark theme a lift is mostly the hairline and
a one-pixel top light, because a shadow on a near-black ground is invisible at best and muddy at
worst.

## Motion is a state

The state dot says whether the watcher is alive, in the Dashboard's header, at the top of the
popup and at the top of the panel. Monitoring breathes slowly; waiting holds a soft halo;
checking a task that has come due turns a small arc (in the Dashboard and the popup); recovering
pulses faster; paused is still, with no halo; a state that needs a person pulses once when it is
entered and then holds. Nothing blinks, and the dot always has its word beside it.

All of it stops on request. The Dashboard and the popup stop every animation when **Reduce
motion** is on (Settings > Appearance) or when Windows' own animation-effects switch is off, and
the Dashboard also stops it in High Contrast. The panel follows the host's
`prefers-reduced-motion` instead, which is why the setting is not offered there.

## High Contrast, and a window that stays light

In High Contrast the Dashboard drops its shadows and tints, stops its motion and draws with
system colours throughout; `Palette` in `gui/Controls.cs` is where that swap happens. The popup
does not make that swap: it draws with the light palette in every mode.

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
- **A standard control underneath.** In the Dashboard a button is still a `Button` and a check
  box a `CheckBox`; only the painting is ours, so the keyboard, focus and screen readers behave
  as they always did.

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

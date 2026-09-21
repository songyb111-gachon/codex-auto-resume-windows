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

v0.6.4 also made them one material in both themes. The panel had always followed Codex into dark;
the Dashboard and the popup now draw the panel's dark theme as well, from the same recipes, when
Windows or the **Theme** setting asks for it. And it added the two controls the surfaces did not
yet share: a check box, for picking the items of a list, and a soft scroll bar for the window's
pages and lists.

v0.6.5 let the material move and gave the popup depth. The state light blinks as the icon's head
does and spreads a little once it is lit, the notification-area icon moves in its own smaller language, switches glide and check
boxes fade on one curve (`MOTION`), what stands on the popup's card is raised and what holds a
value is sunken, and the drop-down's open list is drawn in the cards' material rather than by
Windows. A notification can appear as the popup's own card beside the notification area. The
mark's geometry moved into `brand.py` (`ICON_SHAPE`), because the watcher now draws the icon's
frames from it.

## Where a colour comes from

`src/codex_auto_resume/brand.py` and nowhere else — and since v0.6.3, every size, radius and
duration as well.

| Surface | How it gets the palette |
| --- | --- |
| The Codex panel | `mcpui.py` builds its `:root` block at import from `brand.LIGHT` and `brand.DARK`, `brand.css_scale()` - which also writes the check box's colours for each of its states - and `brand.css_elevation()`, which writes the shadow recipes of both themes as CSS. |
| The Dashboard | `build/make_brand.py` generates `gui/Brand.cs`: every light token as a `Color`, and in the nested class `Brand.Dark` the dark twin of everything that changes with the theme, under the same name; the scale, the layout sizes, the shadow recipes and the state light's numbers as constants; and the per-state rules of the state light, the shadows and the check box as small generated methods. `gui/Controls.cs` adopts one theme before its first control is made and reads the brand's colours through one `Tokens` class, the only place a light colour and its dark twin are read; its `Palette` class is also the one place High Contrast is honoured. The generated file is committed, so a contributor with no Python can still read what the window will look like. |
| The notification-area popup | `tray_popup.py` imports `brand` and draws with `brand.palette(theme)`, `brand.card_ground(theme)`, `brand.shadows(recipe, theme)`, the scale, `brand.glow()` and `brand.ease()` directly, in the theme it resolved when it opened. The notification card is the popup's card, drawn by the popup's own renderer. |
| The icon | `assets/make_icon.py` imports the four icon colours and `brand.ICON_SHAPE`, and rasterises with `brand.icon_render()`; the notification-area icon's motion frames come from the same geometry and rasteriser inside the watcher (`tray.py`). |
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
text on it, so a later adjustment "for looks" cannot quietly make the panel unreadable. Since
v0.6.4 they do it in both themes on every ground a word is drawn on - the canvas, a card, a raised
control, a well and `accent_soft` - and hold the focus ring to 3:1 against each.

**In dark, a card is not its surface.** On a near-black canvas a card that is only `surface`
reads as a hole, so a dark card's ground is `surface` moved 22% of the way toward `raised`,
`#1B212C`. The panel writes it as `color-mix()`, and the window and the popup fill with
`brand.card_ground()`, which is the same colour (`CARD_LIFT`). A light card is its surface.

**`on_accent` exists because of a bug the tests found.** A dark theme needs a bright accent
to stand off its surface, and a bright accent cannot then carry white text: white on
`#5AA5F5` is 2.6:1. So the text on the accent is a token that goes dark exactly when the
accent goes light. Nobody noticed by looking; the assertion did.

## The scale

Everything that is not a colour, in device-independent pixels at 96 DPI, so a card in the
window and a card in Codex round their corners by the same amount.

| Table | Values | Used for |
| --- | --- | --- |
| `RADII` | card 16, control 11, chip 999, small 7, check 5 | Corners. A chip is a pill. |
| `SPACING` | 4, 8, 12, 16, 24, 32 (`xs` to `xxl`) | Padding and gaps. |
| `TYPE` | title 20, heading 14, body 12, small 11 | The Dashboard's and the popup's type sizes. |
| `TYPE_SCALE`, `LINE_HEIGHT`, `TYPE_ROLES` | display 21, title 15, body 14, small 12.5, mono 13 | The panel's type. The native surfaces keep `TYPE`: a notification-area popup and a fixed-size window read better with smaller text than a panel inside Codex. |
| `LAYOUT` | button 34 high, field 35, switch 40 × 22, check box 18 with 10 to its label, chip 22, card padding 16 × 18, page gap 14, and the rest | The sizes of the shared control recipes, taken from the panel. |
| `SHADOWS` | light card: offset (4, 4), blur 14, `shadow_dark` at 0.55, and offset (−4, −4), blur 14, `shadow_light` at 0.90; control: the same at offset 2, blur 6; inset: offset 2, blur 6, inside the edge. Dark card: offset (0, 1), blur 2, `shadow_dark` at 0.70, offset (0, 6), blur 18, at 0.35, and a one-pixel `shadow_light` line at 0.45 inside the top edge; control: offset (0, 1), blur 2, at 0.60; inset: the same inside the edge, at 0.55 | A lifted card, a raised control and a well. Small on purpose: exaggerated embossing is what makes soft interfaces unreadable. |
| `STATUS_DOT`, `STATUS_FILL`, `GLOW` | dot radius: window 5, popup 4.5, panel 6; one cosine a cycle, taken in light and drawn through gamma 2.2; the dot keeps 35% of its light at the bottom; the glow rides it, reaching 0.6 of the radius at opacity 0.50 | The state light: its size, its colour for each state, its blink and its glow. |
| `MOTION` | transition 160 ms on one curve, `ease` = cubic-bezier(0.33, 1, 0.68, 1), an ease-out | A switch's glide and a check box's fade on every surface, and the rise of an open drop-down list. |
| `ICON_SHAPE` | ring 0.34 to 0.53 of the half-size; sweep from 125° round to 55°, leaving a 70° opening at the top; head radius 0.155; corners 0.30, or 0.24 below 32 px; 4 × 4 samples a pixel (`ICON_SUPERSAMPLE`) | The mark's geometry, in a square whose half-size is 1. |

The window gets these as constants in `gui/Brand.cs` - `RadiusCard`, `SpaceM`, `TypeBody`,
`ButtonHeight`, `FieldHeight`, the shadow recipes and the glow's numbers - and multiplies them
by its own scale factor. The popup reads the same tables from `brand.py`. The panel gets CSS
custom properties from `brand.css_scale()`: `--radius-*`, `--space-*`, `--type-*`, `--lh-*`,
`--size-*`, `--glow-*`, `--transition` and `--transition-ease`. The curve is solved the way
browsers solve a cubic-bezier - `brand.ease()` in the popup, `Brand.Ease` in the window - so all
three surfaces move a switch along the same path.

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
and muddy at worst. That makes a dark card's recipe a different shape from a light one's - three
shadows, one of them inside the edge - so every surface reads each shadow's own `inset` flag
rather than guessing it from the recipe's name.

## Motion is a state

The state light says whether the watcher is alive, in the Dashboard's header, at the top of the
popup and at the top of the panel, and since v0.6.5 it says what a notification card is about.
It is a flat dot that breathes, with a glow that rides its brightness. `brand.glow()` defines it
once - its numbers are `GLOW`, generated into the window's `gui/Brand.cs` and the panel's
stylesheet - and every surface is tested against that one function. Since v0.6.6 the shape is the
ordinary one a status light of this size is built from, and nothing of ours:

1. **One cycle, near a resting breath.** 4.4 seconds, about fourteen a minute. Quicker reads as a
   blink; much slower reads as a light that has stopped.
2. **One symmetric cosine across the whole cycle.** The light is never not moving, and has a
   corner nowhere. Half of it goes down, half comes back.
3. **A deep swing.** The dot keeps 35% of its light at the bottom, which is 62% of its colour as
   drawn. What makes a breath gentle is its speed and its curve, not a small swing.
4. **Taken in light, drawn through the screen's gamma.** A cosine walked straight along an alpha
   bunches at the top and rushes at the bottom; raised to 1/2.2 it is even to look at.
5. **A glow that rides the brightness.** Out at the top of the breath at opacity 0.50, gone at the
   bottom, and reaching 0.6 of the dot's radius past its edge - a share of the dot, so the
   window's 10-pixel light and the panel's 12-pixel one are the same light at two sizes.
6. **A dot whose size never changes.** A 10-pixel disc that scales reads as jitter.

A cycle begins and ends at the top, where a still light also sits, so a light that starts moving
does not jump in brightness; the glow is the one thing that arrives with the motion.

| State | Colour | Light |
| --- | --- | --- |
| Monitoring | `active` | The cycle, every 4.4 s |
| Waiting | `active` | Lit and still, with no glow |
| Checking a task that has come due | `active` | Lit, with no glow, and a thin arc turning once every 1.6 s (in the Dashboard and the popup) |
| Recovering | `active` | The cycle, every 2.8 s |
| Needs a person, failed | `attention`, `danger` | The cycle once, over 1.4 s, when it is first shown; then lit and still, with no glow |
| Paused, stopped | `paused`, `idle` | A grey dot that never moves |

Three cuts were wrong in three directions before this one, and the user named each: the first
breathed a glow round a dot that never changed, 7 pixels of it ("너무 많이 커지는거 같아"); v0.6.5
made the dot itself blink, deep and quick ("너무 빠르게 깜빡이는거 같아 / 은은한 느낌이 있어야해
부드럽고"); v0.6.6's first answer shrank the swing, which is the wrong lever ("지금은 너무 안
보여"). The fourth is the ordinary one above, chosen against the other three side by side. The glow
is a falloff, never a disc: at its peak its alpha is 0.50 times 0.67 at the dot's edge, 0.58 at 0.14 of the reach, 0.50 at 0.66 and nothing at
the reach, in straight lines between, so it holds near half strength and then fades; it never dips
and rises again, because a gap between a dot and a ring reads as a target. A smaller spread is the
same falloff drawn smaller about the centre, so the glow grows out from under the dot. The largest
reaches 8 pixels from the window's dot centre, well inside the 28-pixel column the window keeps
for it at every scaling. The notification card is drawn once and holds still, so it shows the still
light. The light always has its word beside it.

All of it stops on request. The Dashboard and the popup stop every animation when **Reduce
motion** is on (Settings > Appearance) or when Windows' own animation-effects switch is off, and
the Dashboard also stops it in High Contrast; a light that holds still is lit, with no glow. The panel follows the host's
`prefers-reduced-motion` instead, which is why the setting is not offered there. The
notification-area icon and the notification card stop under battery saver as well.

### Controls move, briefly

A switch glides when it changes - the knob slides and the track cross-fades between the grey well
and the accent - and a check box fades its fill and its mark, in `MOTION`'s 160 ms on its one
curve. The curve is an ease-out (easeOutCubic, `cubic-bezier(0.33, 1, 0.68, 1)`): the knob
leaves at once and settles, so a switch answers the moment a change is confirmed and still comes
to rest softly. A change that waits for a confirmation - the panel's per-conversation switch asks
you first; the Pending page's switch and the popup's wait for the control layer - moves once, when
it is confirmed, and never slides and snaps back. At rest a switch and a box are exactly what they
were before, and nothing slides under Reduce motion, Windows' animation setting or High Contrast.

### The icon's motion

The notification-area icon is sixteen pixels across and glanced at, so it does not copy the
six-state light; it speaks a smaller language with the mark it already has. The head - the bright
dot at the leading end of the ring - is what moves. While the watcher watches it breathes three
times, dimming toward the badge's deep blue and back on `GLOW`'s monitoring rhythm, and then sweeps
along the ring's white stroke and back in a slot of two more breaths, at full brightness, eased in
and out: 3.52 s out, a moment held at the stroke's far end, 3.52 s back and 1.54 s at home - a loop
of five slots, each one breath long. It leaves its place clockwise and stays on the stroke, never
crossing the gap at the top of the ring, so the head is always somewhere the ring is drawn. It never
breathes while it travels, and every hand-over is at full brightness, where a breath and the sweep's
slot both begin and end. While a recovery is in progress it sweeps out and back over and over, twice
as quickly - 1.76 s out, a moment at the far end, 1.76 s back and 0.33 s at home, a sweep every
3.96 s - at full brightness and without breathing; paused it is grey and still; a problem is its
colour, one pulse on `GLOW`'s attention rhythm, then held. The motion adds no shape and no colour:
the frames are the mark itself, drawn from `ICON_SHAPE` by the same rasteriser as the `.ico`, with
the head moved - 24 positions round the ring, fifteen degrees apart, of which the 20 from its own
place clockwise to the stroke's far end are the ones a sweep uses - and recoloured - 24 levels of
brightness, a tint of the head and never a stored frame - and at rest the icon is exactly the icon
it has always been. Of `GLOW` the icon reads two rhythms and nothing else: the monitoring breath,
which is every slot of its loop and of recovering's sweep, and the attention pulse. Its own few
numbers - how many breaths come before a sweep, how long its slot is and how that slot is spent, the
head's positions, the breath's levels and the frame rates - are `tray.py`'s `ICON_MOTION`,
deliberately not `brand.py`'s, because every `GLOW` key is generated into the window's status light,
and the window's taskbar button reads the icon's own from `Brand.Mark`. The README shows the motion
as an animated PNG drawn from the icon's own frames (`docs/images/icon-motion.png`, made by
`build/make_screenshots.py`). It holds still under Reduce motion, Windows' animation setting, High
Contrast, battery saver, a locked session, and while Windows' own settings for the icon say it sits
in the overflow area (`tray_place.IconPlacement`, which reads them and writes nothing): the icon's
rectangle cannot say, because Windows 11 build 26200 gives an icon in the overflow area the overflow
button's own rectangle rather than none, and the icon moved there unseen.

## Light, dark and High Contrast

**Theme**, under Settings > Appearance, is *Use system setting*, *Light* or *Dark*. For the
Dashboard and the popup, *Use system setting* means the app mode Windows is set to - the
`AppsUseLightTheme` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize`,
where 0 is dark and a missing value is light. For the panel it means Codex's own theme: the page
carries no theme of its own and follows `prefers-color-scheme`, while *Light* and *Dark* stamp its
root with `data-theme`.

Since v0.6.6 the panel has a theme of its own beside that one, **Theme in Codex**: *Same as Theme*,
*Codex's theme*, *Light* or *Dark*. *Same as Theme* is the default and is the paragraph above, word
for word - so the Theme draws the panel only while the panel's own says so, and draws the Dashboard,
the popup and the notification card always. Only the panel reads it, so the resolution is one
function, the panel's `applyTheme`, and anything it does not know is *Same as Theme*.

The notification-area icon and its badge do not change with either setting;
they sit on the taskbar, not on any of the three surfaces. When the icon's head takes a state's
colour it is the one made to read on the icon's own deep-blue badge: the dark palette's
`attention` and `danger`, and the light palette's `idle` grey, whose dark value all but vanishes
into the badge.

Dark is the panel's dark theme on all three surfaces, from one set of numbers: `DARK`, the dark
shadow recipes and the dark card ground. The window adopts its theme once, before its first
control exists, and a test walks every control on every page of the dark window and finds no
light colour; its title bar goes dark through `DWMWA_USE_IMMERSIVE_DARK_MODE`, and a text box's
own scroll bars through Windows' dark style. The window builds its colours when it opens, so a
changed theme reopens it rather than repainting it. The popup resolves its theme each time it
opens, and while it is dark the watcher asks Windows for dark context menus too. What Windows
draws itself stays Windows' own: message boxes, the file dialog, a text box's context menu, and
Windows' own notifications. Since v0.6.5 the open drop-down list and the notification card are
ours, so both are dark in dark.

The Dashboard was light-only until v0.6.4, and that was a measurement rather than an opinion. A
probe built for v0.5.6 painted a card, a spin box, a drop-down, a check box and a button in the
dark palette and photographed the result. The body went dark; the parts Windows draws itself -
the spinner's buttons, the drop-down's arrow, the check-box glyph - stayed light, which is worse
than an honestly light window and not fixable without owner-drawing every native control.
v0.6.3's soft controls painted over the standard controls rather than replacing those parts.
v0.6.4 draws each of them: the spin buttons are two wedges on the well, the drop-down's closed
face is ours, a switch and a check box are drawn whole, and the scroll bar is our own. That is
what made a dark window honest, and why it arrived with them rather than before.

High Contrast wins over any theme. In it the Dashboard drops its shadows and tints, stops its
motion and draws with system colours throughout; `Palette` in `gui/Controls.cs` is where that swap
happens. The popup makes the same swap, with the same mapping, and the panel has a forced-colors
style, so its lights, switch knobs, check boxes and drop-down arrows stay visible. In all three the
state light becomes a solid dot in a system colour, with no glow.

## Switches and check boxes

A switch turns something that runs on or off: notifications, the notification-area icon, Reduce
motion, Run at Windows sign-in, and automatic recovery for one conversation. A check box picks
which items of a list apply: which kinds of interruption are recovered (`recover_<kind>`) and,
under the notifications switch, which events notify (`notify_<event>`). A setting is the same kind
on every surface that shows it, and a check box sits to the left of its label everywhere. A switch
sits where its surface puts switches: at the bottom right of its row in the panel and the popup,
level with the last line of its label, and before its label in the Dashboard.

The check box is the switch's material, written down in `brand.CHECKBOX`:

| State | Fill | Edge | Mark |
| --- | --- | --- | --- |
| Unchecked | `inset`, with the inset shadow inside the edge | `muted` | - |
| Checked | `accent` | `accent` | `on_accent` |
| Unchecked, disabled | `surface` | `line` | - |
| Checked, disabled | `surface` | `line` | `muted` |

The box is 18 pixels - the switch's 16-pixel knob in a one-pixel frame - with corners of 5 and 10
pixels to its label, so a row of check boxes is never taller than a row with a switch. Its edge
unchecked is `muted`, not the `line` a field has: a switch that is off is still told apart by its
knob, an empty box has nothing inside it, and a `line` hairline on a card measures 1.3:1, well
under the 3:1 a control's outline needs. The tick is one polyline, `brand.CHECK_MARK`: two arms
at 45 degrees meeting at a right angle, the long arm twice the short one, stroked 2 pixels wide
with flat ends and a mitred corner. The window strokes it; the panel clips a layer to the same
outline (`--check-mark-shape`). In High Contrast the box is `brand.CHECKBOX_SYSTEM` - a Window box
with a WindowText edge, Highlight with a HighlightText tick when checked, GrayText when disabled -
and never has a shadow. Its focus ring is every control's.

## The scroll bar

The window's pages, its Settings sections, Pending's **Why it is waiting** and every list scroll on
a soft bar of the window's own rather than on Windows' scroll bar. The track is a pill 12 pixels
wide in a 3-pixel margin, drawn as a well - `inset` with a `line` edge - and the thumb is a
`raised` pill resting in it, with a control's lift kept inside the groove; its edge moves a step
toward `muted` under the pointer and another while it is dragged. The thumb is as long as the
share of the page that shows, and never shorter than 32 pixels. A wheel notch moves three lines
of 33 pixels, which is what the panel's page moves; a press on the track moves a page; and a
control the keyboard moves to is brought into view with 16 pixels around it, moving as little as
it can. The bar shows only while there is more than fits, and glides unless motion is reduced. In
High Contrast the track is Window with a WindowFrame edge and the thumb GrayText, Highlight under
the pointer, with no shadow. A list's own scroll bar is clipped away behind the soft one. The bar
is the Dashboard's alone: the popup does not scroll, and the panel scrolls in the page Codex shows
it in.

Since v0.6.5 the same holds across a list's bottom. A list's columns share its width at every
ordinary size, what cannot fit ending in an ellipsis, so a list overflows sideways only in a window
narrower than its columns can shrink to; then, and only then, the soft bar lies along its bottom,
and Windows' own horizontal bar - which showed white on a dark card - is clipped away too.

Since v0.6.6 it is every bar, wherever one appears and on either axis, in the window and in the
panel alike: a bar that arrives in Windows' or the browser's grey is a hole in the design, and it
arrives by default, so the rule has to be the default too. The panel's stylesheet says it for the
document rather than for one class, corner included, with `scrollbar-width` behind it for a browser
that draws no `::-webkit-scrollbar`. The window's message box was the last control still scrolling
on Windows' bar: it keeps that bar - it is what actually scrolls the text, and what the wheel and
the keys talk to - and hides it outside a clip, while the soft bar is drawn in the gutter that
leaves, from the box's own scroll position.

And the track takes its colour from the ground it runs over. Over a card the groove is `inset`, as
above; in a well that is itself `inset` - the message box - an inset track would *be* the ground
and the thumb would float on nothing, so there the track is `surface`. A groove is a step away from
what surrounds it, and which way that step goes depends on what surrounds it.

## Asking, and telling

Windows' message box was the window's last native control, and it broke three rules at once: a
square grey sheet in nobody's material, a system font in a window with its own, and a title bar
that ignores the theme - in dark, a white card in the middle of a dark window. Since v0.6.6 a
question and a notice are both a dialog of the window's own: canvas, the window's font, its title
bar, a sentence at a 420-pixel measure inset 16 on every side, and a button row inset the same.

Its buttons say what will happen. "Yes" and "No" name nothing, so the affirming button carries the
words of the button that was pressed to ask - *Clear history*, *Stop watcher*, *Install* - beside
`action.cancel`, or `action.close` where the action itself is called Cancel and the two words would
be the same. It is the accent button, and the only one; it is the rightmost; Enter presses it and
Escape presses the other. A notice has one button, *Close*, and Enter and Escape both press it.
The panel settled this first, on the pending row that asks before it switches a conversation off,
and the window follows the panel rather than the other way round.

One message box is left, and deliberately: the one raised before there is a window, a theme or a
catalog, to say that nothing is installed in that location.

## Depth in the popup

v0.6.5 gave the inside of the popup's card the depth its outside had. What stands on the card is
raised and what holds a value is sunken, and every part of it is one of `brand.py`'s recipes -
the popup adds no number of its own:

| What | How it is drawn |
| --- | --- |
| A waiting task | A tile on `raised`, the ground the panel's rows and a resting button stand on, with a `line` hairline. Light: `SHADOWS["light"]["control"]`, a short drop down and right and the white highlight up and left. Dark, where a drop alone does not show at a tile's size: the dark `control` drop plus the one-pixel top light of the dark `card` recipe, inside the hairline. |
| The three counts | One well - the `inset` fill with the `inset` recipe inside its border - with a hairline between the counts. |
| Nothing to list, and a failed read | Said from a well, as an empty field is. |
| A button | Stands with the `control` lift, and sinks into a well (`inset`) while it is pressed. |
| A switch that is off | A well on its raised tile, as the panel's is. |

The card's own recipe does not transfer: at its 14-pixel blur a tile eight pixels from the next
would share one grey smear with it, where the `control` recipe keeps each tile its own. The panel's
tiles - a waiting conversation's row and the Automatic recovery switch's - take the same lift
(`--elev-tile`), and so does the notification card's tile. The Dashboard's Pending and History
lists stay flat rows closed by a hairline, the chosen row filled softly: raised tiles were tried
there during v0.6.5 and taken out again, because the flat rows read better. High Contrast draws
none of it - system colours, hairlines, no shadow.

## The drop-down list

Closed, a drop-down is a well a value sits in, as in v0.6.4: `LAYOUT`'s `field_height` of 35 with
`select_pad`, and the chevron a `muted` wedge `chevron_width` 10 by `chevron_height` 5, set
`chevron_right` 13 from the well's inside edge. Since v0.6.5 the list it opens is drawn by the
product too, in the window and in the panel, where it used to be Windows' - square corners, a thin
grey border, no shadow, a flat blue band, and light even in dark:

- **The list is a card.** The cards' own ground (`card_ground`), their `RADII` corner and hairline
  and, in dark, their one-pixel top light, lifted by the `card` recipe of `SHADOWS`, whose shadow
  spills outside it over whatever is behind. It floats just under the field, its words starting
  under the field's own, and opens above instead where the screen has no room below.
- **The items are pills**, set in the field's font with the field's padding, `SPACING`'s `xs`
  apart. The item chosen now is a sunken pill - a well with the `inset` recipe - with its words in
  `accent`; the item under the pointer rises with the `control` lift; the item the keyboard is on
  has the focus ring every control has (`focus`, `focus_width`, `focus_offset`).
- **It moves once.** It fades in and rises `SPACING`'s `xs` into place over `MOTION`'s time on its
  curve, and closes at once; with motion reduced it is simply there.
- **High Contrast** draws it in system colours with no shadow anywhere: in the window a `Window`
  card with a `WindowFrame` edge, the chosen item in `Highlight` with `HighlightText` and the item
  under the pointer with a `Highlight` edge.

Under the paint it is still the drop-down it was: the keys are Windows' - it opens on a click, F4,
Alt+Down, Alt+Up or Space, the arrows, Home, End, Page Up and Page Down move, typing finds, Enter
or Tab takes an item, Escape closes it as it was - the focus never leaves the field, and a screen
reader hears a combo box with its choice and the item the keyboard is on.

## The mark

A rounded-square badge in deep blue carrying an open ring with a bright head at its leading
end. The ring is the wait; the gap at the top is the interruption; the cyan head is the
moment it resumes.

`assets/brand/icon.svg` is the vector master and `assets/codex-auto-resume.ico` the Windows
raster set, both generated by `assets/make_icon.py` from the same numbers — one geometry, not a
drawing and a copy of it. Until v0.6.5 those numbers lived in `make_icon.py`; now they are
`brand.ICON_SHAPE`, with the rasteriser beside them (`brand.icon_render()`), because the watcher
draws the notification-area icon's motion frames from them, and `make_icon.py` imports them.

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
  configuration will say; then how it looks. The Dashboard's Settings is split into General,
  Automatic recovery, Continuation message, Appearance and Advanced.
- **What a card leads to closes it.** A button or a switch at the right of a card or a row is
  pinned to its bottom-right corner: the heading and the text come first, from the top left, and
  the control ends the block - beside the last line where there is room, and under it, still on
  the right, where there is not. A card taller than what it holds - the Overview's, whose two rows
  share the page's height - keeps the text at its top and the control in its corner. Text wraps
  rather than running under a control, and the keyboard reaches the control after the text.
  Buttons already along the bottom, drop-downs, chips and check boxes keep their places, and so do
  the Dashboard's switches that sit before their labels.
- **Every status fact is its own label in its own cell.** A single concatenated string
  wraps or truncates as the window narrows, and what disappears first is the version — the
  part people are asked for when reporting a problem.
- **The card is one object, repeated.** Same ground, same hairline, same radius and the same
  lift on all three surfaces, so the eye reads a list of sections rather than a pile of boxes.
- **A standard control underneath.** In the Dashboard a button is still a `Button`, a switch and
  a check box are each a `CheckBox` drawn as one, and a drop-down is a `ComboBox` whose closed face
  and, since v0.6.5, open list we draw; only the painting is ours, so the keyboard, focus and screen
  readers behave as they always did, and the list answers every way Windows' list could be opened
  and every question a screen reader asks it. In the panel a check box is an
  `<input type="checkbox">`, a switch the same input with `role="switch"`, and a drop-down a
  combobox over a hidden `<select>`. The soft scroll bar is the one part with no standard control
  under it, and it takes no focus: the keyboard goes to what it scrolls, which comes into view.

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

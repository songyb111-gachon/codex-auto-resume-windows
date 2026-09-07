# The look of it

One palette, one mark, four surfaces. This is where the decisions are written down so a
future change can argue with them rather than guess at them.

## The idea

The product waits, and then it acts. That is the whole behaviour, so it is the whole
palette: **deep blue at rest, cyan at the moment it does something.** The ramp is not
decoration — a reader who learns that bright means active has learned what the tool does.

Until v0.5.2 the product was green, and each surface carried its own copy of the colours:
the settings window in C# literals, the Codex panel in a stylesheet, the icon renderer,
the plugin manifest. They had already drifted — the manifest's brand colour and the panel's
accent agreed with each other and with nothing else.

## Where a colour comes from

`src/codex_auto_resume/brand.py` and nowhere else.

| Surface | How it gets the palette |
| --- | --- |
| The Codex panel | `mcpui.py` builds its `:root` block from `brand.LIGHT` and `brand.DARK` at import. |
| The settings window | `build/make_brand.py` generates `gui/Brand.cs`. The generated file is committed, so a contributor with no Python can still read what the window will look like. |
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
| `ink` | `#0F1B2D` | `#E6EDF5` | Text. A near-black carrying the same blue bias. |
| `muted` | `#5A6B7F` | `#93A4B8` | Secondary text. |
| `line` | `#DCE3EC` | `#24303F` | Hairlines and card edges. |
| `surface` | `#FFFFFF` | `#161D27` | Cards. |
| `canvas` | `#F2F5F9` | `#0E141C` | The ground behind them. |
| `accent` | `#1257B8` | `#5AA5F5` | Anything to read or to click. |
| `on_accent` | `#FFFFFF` | `#0B1220` | Text drawn *on* the accent. |
| `active` | `#06B6D4` | `#22D3EE` | Fill only: running, work in flight. |
| `idle` | `#94A3B8` | `#5C6B7C` | Fill only: stopped. |
| `attention` | `#B45309` | `#F0A45C` | Fill only: needs a person. |

**`active` is a fill-only token.** Against white it measures 2.4:1, which is right for a
status dot and not enough for text. Every readable pairing carries a contrast assertion, so
a later adjustment "for looks" cannot quietly make the panel unreadable.

**`on_accent` exists because of a bug the tests found.** A dark theme needs a bright accent
to stand off its surface, and a bright accent cannot then carry white text: white on
`#5AA5F5` is 2.6:1. So the text on the accent is a token that goes dark exactly when the
accent goes light. Nobody noticed by looking; the assertion did.

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

- **State leads.** On both the settings window and the Codex panel, what the watcher is
  doing is the first thing and the largest type. It used to be a muted sentence along the
  bottom of the window, under sixteen checkboxes — which put the one thing a person opens
  the window to check below everything they did not come for.
- **Order is an argument.** Cards run: what may be recovered, then how hard it will try,
  then what it will tell you, then when it starts.
- **Every status fact is its own label in its own cell.** A single concatenated string
  wraps or truncates as the window narrows, and what disappears first is the version — the
  part people are asked for when reporting a problem.
- **The card is one object, repeated.** Same edge, same accent rail, same inner padding
  across both surfaces, so the eye reads a list of sections rather than a pile of boxes.

## Redrawing anything

```bash
python assets/make_icon.py     # icon, logos, vector master
python build/make_brand.py     # gui/Brand.cs
python build/icon_concepts.py  # the concept comparison sheet
```

Screenshots are captured with `build/capture_window.ps1`, which declares itself DPI aware
before measuring. A DPI-unaware capture is told a scaled-down window rectangle, allocates a
bitmap that size and returns a picture of the window's top-left corner — which looks
exactly like a window whose layout is broken, and cost an afternoon once.

# Codex Auto Resume roadmap: v0.6.7 → v0.6.12

This is the current development direction for Codex Auto Resume after v0.6.6.

This is a **planned roadmap, not a promise**. Details may change as Codex evolves or as testing
reveals better or safer implementation paths.

The overall direction is:

**finish the UI → add compatibility intelligence → add advanced features, more than any program
like this → clean up and stabilize Python → replace the core with Rust and make it Rust-native →
stabilize Rust**

The default recovery behavior stays as conservative as it has always been, through every release
here: what v0.6.9 adds is there for a person to turn on, never on by itself.

---

## v0.6.3 — Released ✅

v0.6.3 was the major feature and UX expansion release.

It added, among other things:

- nine interface languages,
- separate interface and continuation-message languages,
- reason-aware continuation messages,
- Minimal / Standard / Detailed / Custom message styles,
- global and per-reason Custom messages,
- richer Dashboard and Tray controls,
- improved notifications,
- broader Python CI coverage.

The recovery safety model remained deliberately conservative.

---

## v0.6.4 — Design consistency, neumorphic refinement, and responsiveness ✅

**Released.**

v0.6.4 finished the UI introduced in v0.6.3 rather than expanding the recovery engine:

- one neumorphic design across the Dashboard and Settings window, the notification-area popup
  and the panel in Codex, taken from the panel,
- light and dark themes that follow Windows by default, with a choice in Settings,
- a window that opens at 1000 × 632 with a first screen that never scrolls,
- soft scroll bars in place of Windows' own,
- switches for things that run, check boxes for picking items from a list,
- language and theme changes applied at once, with the window reopening itself where it has to,
- page switches from about 100 ms to about 22 ms, and a usable window about 3 seconds sooner,
- the status light back in its pre-v0.6.3 colour, with a gentle glow.

Recovery decides exactly what it decided in v0.6.3.

### Screenshots

#### Dashboard — Overview

<img src="images/dashboard-overview.png" alt="The Dashboard's Overview page" width="680">

#### Dashboard — Pending

<img src="images/dashboard-pending.png" alt="The Dashboard's Pending page" width="680">

#### Notification-area popup

<img src="images/tray-popup.png" alt="The notification-area popup" width="360">

#### Settings — Korean

<img src="images/settings-window-ko.png" alt="The Dashboard's Settings page in Korean" width="680">

---

## v0.6.5 — Codex Compatibility Registry, interface polish, and groundwork for the split ✅

**Released.**

v0.6.5 carries the Codex Compatibility Registry and the interface work that came out of using
v0.6.4, and lays the groundwork for splitting the Python implementation, which moved to v0.6.10's alpha.

### Codex Compatibility Registry

This release is also planned to introduce explicit Codex compatibility states:

- **VERIFIED** — maintainer-tested
- **COMPATIBLE** — local structural checks pass, but not yet formally verified
- **INCOMPATIBLE** — known unsafe or incompatible
- **UNKNOWN** — compatibility cannot be established

Where useful, compatibility should be tracked per capability rather than only per whole Codex
version.

For example:

```text
Codex x.y.z

Usage-limit detection   ✓ Verified
Exact-thread recovery   ✓ Verified
Recovery-turn tracking  ✓ Verified
Empty-response recovery ? Unverified
notLoaded recovery      — Unsupported
```

Remote compatibility data must **never override failed local safety checks**.

If the registry cannot be reached, the intended fallback is:

```text
validated cache
    ↓
local structural checks
    ↓
UNKNOWN / fail closed if still uncertain
```

No telemetry is required for this system.

The Compatibility Registry's data ships inside each release and is refreshed only when you ask -
from Diagnostics, or when you check for updates. There is no background traffic. The first
release that carries it lists no capability as VERIFIED: that state needs recorded evidence.

### Interface

Interface work that came out of using v0.6.4:

- a status light you can actually see breathing,
- motion on the notification-area icon itself: a slow breathe with an occasional slow turn while
  watching, and a turning arc while a recovery is being sent,
- a notification card in the product's own design, with a silent copy in Action Center, and
  Windows' own notification wherever a card must not appear (a locked session, a full-screen
  app, Do Not Disturb, a running screen reader),
- real depth inside the notification-area popup,
- the first screen's card buttons back at the bottom-left, with its proportions redone,
- drop-down lists drawn in the same neumorphic material as the cards, in the window and in the panel,
- switches that glide when they change,
- lists that never overflow sideways.

### Fixes and groundwork for the split

- three fixes found while planning the refactor,
- tests that keep every safety check reading the whole package, so that moving code can never
  quietly take it out of a check's sight,
- screenshot checks keyed on what the window is shown rather than on which files changed.

---

## v0.6.6 — The ordinary breath, a taskbar button that moves where it is installed, and the last native controls ✅

**Released.**

What a day of real use turned up. Nothing about recovery changed.

The status light is the ordinary breath now: one symmetric cosine over 4.4 seconds, taken in
light and drawn through the screen's gamma, with a deep swing and a glow that rides the
brightness and reaches a share of the dot rather than a count of pixels. One table serves the
window, the notification-area popup, the panel in Codex and the notification card, so all four
breathe alike, and the icon's own breath and sweep read the same rhythm.

v0.6.5 moved the mark on the window's taskbar button, and it never moved on an installed one: an
installed window is resolved to the application the installer registered, and such a button wears
the icon that identity carries rather than the window's own. The window now takes a taskbar
identity of its own, and the button moves where people actually have it.

And the controls that were still Windows' or the browser's are the product's: every scroll bar,
on either axis and wherever one appears, with its track coloured against the ground it runs over;
and the message box, which is now a dialog in the window's own material whose buttons say what
will happen rather than Yes and No. The documentation's pictures move, and they no longer carry
the black frame `PrintWindow` never drew - they are cut to the window and the corners Windows
rounds are rounded in them.

The panel in Codex gets a theme of its own, Theme in Codex, right under the Theme: Same as Theme,
which is the default and what every panel did before, Codex's theme, Light or Dark. The window,
the popup and the notification card keep the Theme.

---

## v0.6.7 — Compatibility in tiers, Failed here, and a notification card that breathes ✅

**Released.**

The Compatibility Registry learns to say how much stands behind its word, and the notification
card's light joins the others. For a Codex version the data says nothing about, recovery decides
exactly what it decided in v0.6.6.

Each capability, on each exact Codex version, now resolves to one of six states, in this order:

- **VERIFIED** — a real recovery on this exact version exercised it, and none failed
- **CHECKED** — new: the maintainer's local checks passed on this exact version, and nothing
  confirmed more
- **COMPATIBLE** — the data makes no claim, and the checks on this computer pass
- **FAILED_HERE** — new: the data checked or verified this exact version, but a check on this
  computer failed, so the cause is most likely this computer rather than the Codex version
- **INCOMPATIBLE** — a check on this computer failed on a version nobody checked, or the data says
  it does not work
- **UNKNOWN** — compatibility cannot be established

The rules stay as they were: a failed local check always wins, and is now INCOMPATIBLE or
FAILED_HERE; data can only restrict, or raise a local pass - to CHECKED or VERIFIED - for an exact
version. CHECKED sends exactly as COMPATIBLE and VERIFIED do; like VERIFIED, it needs recorded
evidence and expires with the fetched data. FAILED_HERE blocks every send exactly as INCOMPATIBLE
does, and says so: a recovery it holds says *Codex checks failed on this computer*, and the
notification-area popup and its icon ask for attention. The advanced tier planned for v0.6.9 stays
VERIFIED-only.

The data on main is fetched by every installed release, so each must take the newest whole, with
its own validator: v0.6.5 and v0.6.6 skip CHECKED, a state they do not know, and nothing they decide
moves. And new data can be published between releases without turning main red: the behaviour
tests and the pictures read a frozen copy of v0.6.6's data, while the live file is still held to its
evidence rules.

The notification card's status light breathes on the same table as the window, the popup and the
panel in Codex, where v0.6.6 drew it lit and still on purpose. Reduce motion and High Contrast keep
it still.

---

## v0.6.8 — A tray icon without its badge, and lights that never stop 🚧

**In development, on the `dev` branch.**

The notification-area icon wore a small status dot in its corner that the window's taskbar button
never had, so during a recovery the tray showed a second light the taskbar did not. The dot is gone:
the head of the mark says the state on its own, and the tray icon and the taskbar button are one
picture.

Needing attention and a failure pulsed once and then held still. Now neither stops for as long as
it lasts: attention's amber light breathes slowly, every 5.6 seconds - slower than monitoring's
4.4 - and a failure's red light quickly, every 1.2 seconds. The tray icon and the taskbar button,
which nothing put in the failed state before, now turn red when a recovery fails, their head
sweeping along the ring twice as quickly as a recovery's and blinking as it goes, and stay red until
you have seen it.
Reduce motion and High Contrast still hold every light still.

---

## v0.6.9 — Advanced features: more than any program like this offers

v0.6.9 goes further than every release so far. It is planned to offer, aggressively, as many
capabilities as any comparable program does, and more: before it is built, the tools that do anything
like this are surveyed, and everything any of them offers goes on the list.

Two rules, the user's own:

- **Everything the product does today keeps today's constraints.** Nothing it already does is
  loosened, and the default does not change - it never sends a continuation again when the first
  may already have been delivered, as it never has.
- **Everything those constraints made impossible is built, and only those who want it use it.** Each
  such capability is off until a person turns it on, one by one, and says plainly what it does before
  they do - sending again when the first may have been delivered included. The limits the earlier
  plan put on what may be offered this way - only what is proven safe, availability for VERIFIED
  Codex versions only, "candidates, not guaranteed" - no longer bind it.

### Two editions, released together

A switch that is off is still code that is there. If the new capabilities shipped inside the one
product, what has set it apart from the start - that it never sends a continuation twice, that it
reads and sends through exactly one conversation, that it fails closed - would hold only while a
setting said so, not in the code. So from v0.6.9 there are two editions, built from one repository
and released at the same time, with the same version:

- **Standard** is the product as it is. The new capabilities are not in it at all: their code is
  left out of its archive, and a test proves the archive it builds holds none of it.
- **Advanced** is everything, each new capability off until its user turns it on.

Each has its own archive, pinned digest and build attestation. An installation updates within its
edition only; moving between them is a deliberate reinstall, never an update. The Rust core carries
both (v0.6.11).

Where the list starts, from the earlier plan:

- notLoaded recovery,
- empty-response recovery,
- Goal-like continuation,
- subagent recovery,
- every further failure category that can be recovered,
- broader recovery wherever Codex allows it.

### Also planned for v0.6.9

- a design audit of the panel in Codex, the app and the notification-area popup, side by side in
  light and dark, fixing everything that does not yet look like one product,
- a choice of appearance: today's design, the same without motion, v0.6.2's plainer look (with
  today's status light), and a fully plain one - each in light and dark,
- responsiveness: the lag the window still has, worst on some pages, and the loading that feels
  slower in every language but English (reported with v0.6.8) - measured where it happens, its causes
  found and fixed.

---

## v0.6.10 — Python modularization, then the final Python audit

v0.6.10 is the last Python release, and it arrives in two stages: **v0.6.10-alpha**, a pre-release,
carries the modularization; the final **v0.6.10** follows once the whole repository has been through
its bug hunt, and it is the Python reference implementation the Rust migration reproduces.

### v0.6.10-alpha — Python modularization (a pre-release)

The alpha is planned as the major structural cleanup of the Python implementation. It was the main
part of v0.6.5 in the earlier plan, and then of v0.6.8 and v0.6.9; v0.6.5 ships its groundwork, and
the split itself lands here. Until it does, the line ceilings hold nothing back: a module may grow as
the features before it need.

Before anything moves:

- golden copies of the replies the window and the panel in Codex receive, so a split that changes
  a single byte of them fails,
- one implementation of rules that were written more than once, shared identifiers and
  vocabularies, and typed contracts between the layers.

Main goals:

- split oversized modules,
- separate responsibilities more clearly,
- clarify boundaries between engine, state, store, adapters, and control layers,
- remove duplication,
- strengthen typed contracts,
- isolate more pure/testable logic,
- prepare clean boundaries for the later Rust migration.

The window's largest C# files may be split the same way, behind the same kind of safety net.

The repository's landing page on GitHub is tidied in the same stage, while paths are moving
anyway, so that fewer files sit at its root.

Bugs discovered during this refactor will be fixed with regression tests, but the alpha is
**not intended to be the full repository-wide bug hunt**; the final is.

### v0.6.10 — Final Python audit and stabilization

The final v0.6.10 is planned as the final comprehensive audit of the Python implementation.

Unlike the alpha, it is intentionally a broad bug hunt.

Expected areas include:

- state machine behavior,
- race conditions and concurrency,
- retry and recovery-chain accounting,
- SQLite and schema migration,
- crash and restart behavior,
- installer / update / repair / uninstall,
- MCP / Tray / Dashboard / CLI,
- Windows process lifecycle,
- sleep / resume,
- malformed, stale, or corrupted state,
- fault injection,
- real Codex integration,
- Advanced / Experimental recovery paths,
- responsiveness, in every language: whatever lag v0.6.9 left.

Confirmed bugs should receive regression tests.

The resulting behavior becomes the:

> **final Python reference implementation**

for the Rust migration.

---

## v0.6.11 — Rust: the core replaced as it is, then made Rust-native

v0.6.11 arrives in two stages too: **v0.6.11-alpha**, a pre-release, replaces the production Python
core with Rust as it is; the final **v0.6.11** is that core made naturally Rust-oriented.

### v0.6.11-alpha — Complete Rust core replacement (a pre-release)

The alpha is planned to replace the production Python core with Rust, as it is.

The migration may happen incrementally during development, but the release itself is intended
to switch to the completed Rust core rather than ship a long-lived mixed Python/Rust product.

The rule is:

> **Replace the implementation, not the behavior.**

The Rust implementation should reproduce the final v0.6.10 as closely as practical.

Goals include:

- Python/Rust differential testing,
- existing database compatibility,
- existing settings compatibility,
- preservation of Conservative and Advanced behavior, and of the two editions: the standard one
  built without the advanced code at all,
- preservation of Compatibility Registry semantics,
- preservation of exact-thread and fail-closed safety guarantees,
- removal of the production Python core/runtime when ready.

The Windows UI is **not** planned to move to Rust.

The intended stack is:

```text
C# / .NET
- Dashboard
- Settings
- Tray
- Notifications
- Native Windows UI

        │
        ▼

Rust
- Watcher
- Recovery engine
- Classifier / Policy
- State machine
- Scheduler / Reconciliation
- Persistence
- Codex adapters
- Control / MCP backend
```

PowerShell may remain as a thin layer for bootstrap, installation, updating, or similar Windows
deployment work.

### v0.6.11 — Rust-native restructuring and optimization

The alpha prioritizes behavioral parity.

That may leave some Python-shaped architecture inside the first Rust implementation.

The final v0.6.11 is planned to make the codebase more naturally Rust-oriented.

Potential work includes:

- ownership-oriented data flow,
- stronger enums and newtypes,
- clearer error types,
- improved concurrency architecture,
- cleaner module / crate boundaries,
- removing unnecessary cloning and serialization,
- cleaner SQLite / IPC / process abstractions,
- removal of Python-era structural assumptions,
- startup, memory, and performance improvements.

Bugs found during this restructuring will be fixed with regression tests.

This is not intended to be the final full-system bug hunt.

---

## v0.6.12 — Final Rust audit and stabilization: the Rust bug hunt

v0.6.12 is planned as the final comprehensive stabilization pass.

Expected focus includes:

- race conditions and deadlocks,
- panic paths,
- thread / handle / memory / resource leaks,
- process lifecycle,
- SQLite transaction behavior,
- IPC and control protocol,
- long-running watcher stability,
- restart and sleep / resume,
- Explorer restart,
- installer / update / repair / uninstall,
- malformed or corrupted state,
- Compatibility Registry cache/offline/failure behavior,
- Advanced / Experimental capabilities,
- real Codex recovery,
- fuzz or property testing where useful.

The intended result is the:

> **final stable Rust baseline**

for the project.

---

## Long-term direction

The intended final stack is:

- **Rust** — recovery core and backend
- **C# / .NET** — native Windows UI
- **minimal PowerShell** — deployment-related work where it remains useful

There is currently **no planned v0.7.0 feature cycle**.

After v0.6.12, the project is expected to move primarily into maintenance:

- Codex compatibility updates,
- Compatibility Registry updates,
- bug fixes,
- security fixes,
- changes required by future Codex behavior.

---

## Summary

```text
v0.6.3  ✅ Released
Feature / UX expansion

        ↓

v0.6.4  ✅ Released
UI design consistency
Light and dark themes
Settings / Tray / MCP unification
UI lag reduction

        ↓

v0.6.5  ✅ Released
Codex Compatibility Registry
+ icon motion, notification card, UI polish
+ groundwork for the Python split

        ↓

v0.6.6  ✅ Released
The light softened
+ a taskbar button that moves where it is installed

        ↓

v0.6.7  ✅ Released
Compatibility in tiers: Verified, Checked, Compatible
+ Failed here, and a notification card that breathes

        ↓

v0.6.8  🚧 In development, on the dev branch
The tray icon without its badge
+ attention breathing slowly, a failure moving quickly

        ↓

v0.6.9
Advanced features: more than any program like this
+ design audit, a choice of appearance

        ↓

v0.6.10-alpha → v0.6.10
Python modularization and a tidier landing page on GitHub, in a pre-release
+ the final Python audit, in the final
→ freeze Python reference behavior

        ↓

v0.6.11-alpha → v0.6.11
Complete Rust core replacement, in a pre-release
+ Rust-native restructuring and optimization, in the final

        ↓

v0.6.12
Final Rust audit and stabilization: the Rust bug hunt
→ final stable Rust baseline

        ↓

Maintenance
```

This document records the current direction; v0.6.7 is out, and v0.6.8 is built on the `dev` branch.

# Codex Auto Resume roadmap: v0.6.5 → v0.6.11

This is the current development direction for Codex Auto Resume after v0.6.4.

This is a **planned roadmap, not a promise**. Details may change as Codex evolves or as testing
reveals better or safer implementation paths.

The overall direction is:

**finish the UI → add compatibility intelligence → clean up Python → add optional advanced
recovery → stabilize Python → replace the core with Rust → make it Rust-native → stabilize Rust**

The default recovery behavior will remain conservative throughout this process.

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

## v0.6.5 — Codex Compatibility Registry, interface polish, and groundwork for the split 🚧

**In development, on the `dev` branch.**

v0.6.5 carries the Codex Compatibility Registry and the interface work that came out of using
v0.6.4, and lays the groundwork for splitting the Python implementation, which moves to v0.6.6.

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

## v0.6.6 — Python modularization

v0.6.6 is planned as the major structural cleanup of the Python implementation. It was the main
part of v0.6.5 in the earlier plan; v0.6.5 ships its groundwork, and the split itself moves here.

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

Bugs discovered during this refactor will be fixed with regression tests, but this release is
**not intended to be the full repository-wide bug hunt**.

---

## v0.6.7 — Advanced / Experimental recovery capabilities

The existing conservative behavior will remain the default.

v0.6.7 is planned to revisit recovery capabilities that were previously excluded because they
required weaker assumptions, insufficient evidence, or unsupported Codex behavior.

Potential candidates include:

- notLoaded recovery,
- empty-response recovery,
- Goal-like continuation,
- subagent recovery,
- additional recoverable failure categories,
- broader recovery behavior where newer Codex capabilities make it safe enough.

These are **candidates, not guaranteed features**.

Each capability should be independently classified where practical:

- Conservative
- Advanced
- Experimental
- Unsupported

Per-feature opt-in is preferred over one global "unsafe mode".

Availability should integrate with the Compatibility Registry introduced in v0.6.5.

The principle remains:

> Keep the safe default small, while giving informed users more control when they explicitly
> choose it.

### Also planned for v0.6.7

- a design audit of the panel in Codex, the app and the notification-area popup, side by side in
  light and dark, fixing everything that does not yet look like one product,
- a choice of appearance: today's design, the same without motion, v0.6.2's plainer look (with
  today's status light), and a fully plain one - each in light and dark.

---

## v0.6.8 — Final Python audit and stabilization

v0.6.8 is planned as the final comprehensive audit of the Python implementation.

Unlike v0.6.6, this release is intentionally a broad bug hunt.

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
- Advanced / Experimental recovery paths.

Confirmed bugs should receive regression tests.

The resulting behavior becomes the:

> **final Python reference implementation**

for the Rust migration.

---

## v0.6.9 — Complete Rust core replacement

v0.6.9 is planned to replace the production Python core with Rust.

The migration may happen incrementally during development, but the release itself is intended
to switch to the completed Rust core rather than ship a long-lived mixed Python/Rust product.

The rule is:

> **Replace the implementation, not the behavior.**

The Rust implementation should reproduce v0.6.8 as closely as practical.

Goals include:

- Python/Rust differential testing,
- existing database compatibility,
- existing settings compatibility,
- preservation of Conservative and Advanced behavior,
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

---

## v0.6.10 — Rust-native restructuring and optimization

v0.6.9 will prioritize behavioral parity.

That may leave some Python-shaped architecture inside the first Rust implementation.

v0.6.10 is planned to make the codebase more naturally Rust-oriented.

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

## v0.6.11 — Final Rust audit and stabilization

v0.6.11 is planned as the final comprehensive stabilization pass.

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

After v0.6.11, the project is expected to move primarily into maintenance:

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

v0.6.5  🚧 In development, on the dev branch
Codex Compatibility Registry
+ icon motion, notification card, UI polish
+ groundwork for the Python split

        ↓

v0.6.6
Python modularization

        ↓

v0.6.7
Advanced / Experimental recovery capabilities
+ design audit, a choice of appearance

        ↓

v0.6.8
Final Python audit and stabilization
→ freeze Python reference behavior

        ↓

v0.6.9
Complete Rust core replacement

        ↓

v0.6.10
Rust-native restructuring and optimization

        ↓

v0.6.11
Final Rust audit and stabilization
→ final stable Rust baseline

        ↓

Maintenance
```

This document records the current direction; v0.6.5 is being built on the `dev` branch.

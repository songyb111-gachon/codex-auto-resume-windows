---
name: codex-auto-resume-advanced
description: What the advanced edition of Codex Auto Resume adds to the standard one, and the rule for its opt-in capabilities - only the user turns one on, in the Dashboard. Use alongside codex-auto-resume when the user asks about the advanced edition, which edition is installed, or an advanced capability.
---

<!-- ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's. -->

# Codex Auto Resume, advanced edition

The advanced edition is the standard edition plus capabilities that go further than the
standard edition's own rules allow. Each one is off until the user turns it on, one at a time,
after reading a plain statement of what it does, what the standard edition does instead, which
rules it departs from, what can go wrong and how to stop it.

Everything in the `codex-auto-resume` skill applies here unchanged: the tools, the commands,
the two kinds of id, how to report results and how to remove the product. This file adds only
what the advanced edition changes.

Windows only.

## Which edition is installed

An installation names its edition in one word: `Standard`, `Advanced`, or
`Advanced - not loaded`. The last means the advanced edition is installed but its own code
could not be loaded, so the installation is doing exactly what the standard edition does and
nothing more. Say so plainly and offer the setup script's repair path from the
`codex-auto-resume` skill. Never describe an installation in that state as having any advanced
capability.

## What it can do

Every capability is off until the user turns it on, so an advanced installation with nothing
turned on behaves exactly as the standard edition does. Do not describe capabilities from
anywhere else, and do not present one as active unless `list_advanced_capabilities` says it is.

- **Start with Codex.** When the user has turned this on, the watcher starts as Codex starts,
  even though Codex runs this plugin inside a job it closes when it quits - which would stop a
  watcher started there within seconds. It asks Windows (WMI) to start the watcher outside that
  job, so it keeps running after Codex closes; it registers nothing and leaves nothing behind.
  The standard edition starts nothing there and only notes why. It departs from two of the
  standard edition's rules (nothing starts on its own at Codex start; no process-creation route
  beyond the listed ones), which is why it is off until turned on. If Windows Management
  Instrumentation is off, or a policy blocks process creation through it, nothing starts and the
  reason is logged; never tell the user to change that policy.
- **Goal continuation.** When the user has turned this on and a usage limit paused a
  conversation's Codex goal, then once the limit has reset and the conversation is due to continue
  while the Codex app does not have it open, the goal is set active again through Codex's own app
  server, so Codex carries the goal on when the app next opens the conversation. Only a goal that
  exists and was paused by the usage limit is resumed; no goal is ever created, and what the goal
  says is never read or changed. While the app has the conversation open, the continuation goes
  through Codex's queue as in the standard edition, and while a goal is carrying a conversation on
  the standard continuation waits up to ten minutes so the two do not both run. Only where
  measurement M2b passed for the installed Codex is the goal also set active before a queued
  continuation in a conversation the app has open. It departs from five of the standard edition's
  rules (goals are never touched; one channel only; nothing is done for a conversation the app does
  not have open; Codex's state changes only through its queue; the app server's three requests).
  When its result cannot be confirmed, that interruption is never tried again and the capability
  turns itself off. A goal it set active stays active after it is turned off; tell the user to
  pause the goal in Codex if they want it to stop.
- **Marker-free continuation.** When the user has turned this on, each continuation is sent
  without the `[codex-auto-resume:<16 hex>]` marker the standard edition ends it with. It is added to the
  conversation's queue through Codex's own app server under an id made from the interruption, and
  that id, which Codex keeps on the message, is how the product proves it arrived. It departs from
  four of the standard edition's rules (one channel only, Codex's queue command; the marker proves
  delivery; Codex's state changes only through its queue; the app server's three requests). Past
  its daily limits a continuation goes with the marker, as in the standard
  edition. When arrival cannot be proven, the continuation is treated as uncertain and never sent
  again, and the capability turns itself off; the user can turn it on again in the Dashboard.

## Turning capabilities on and off

- **Never turn a capability on** - not with a tool, a command, a setting or a file, and not when
  the user asks you to. A capability is turned on only in the Dashboard, by the user, after its
  statement; if they ask, tell them that is where it is.
- Turning a capability off, or all advanced features at once, is always allowed, and only ever
  does less. When the user asks, use `disarm_advanced_capability` with the exact id
  `list_advanced_capabilities` gives, or `disarm_all_advanced`. `list_advanced_capabilities`
  only reads.
- A statement may show warnings: a measurement the capability relies on failed or was never
  made for this version of Codex, or its compatibility check failed or is unknown. A warning
  does not stop the user turning the capability on; turning it on confirms they read it. Never
  call a capability unavailable because of a warning. Only an administrator's policy can keep
  one from being turned on.
- A capability that turned itself off after a problem appeared can be turned on again in the
  Dashboard, by the user, like any other.
- **Keep it on** (a capability that does not turn itself off, with or without *Also send again when
  unsure*) and **Send now** (one waiting recovery sent at the next look) are the Dashboard's, set or
  asked for there by the user and nowhere else. No tool sets either, so never claim to have kept a
  capability on or sent a recovery now; `list_advanced_capabilities` shows whether one is kept on.
  Turning a capability off always works, kept on or not.
- Pause stops every capability along with everything else.

## Moving between editions

Moving between the standard and the advanced edition is a deliberate reinstall, never an update:
an update keeps the edition that is installed. Never change the installed edition on your own
initiative. Do it only when the user names the edition they want, and say first what it is.

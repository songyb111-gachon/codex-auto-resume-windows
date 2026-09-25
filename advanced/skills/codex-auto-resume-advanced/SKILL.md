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

In this version, nothing the standard edition cannot: it carries the edition and no capability
yet, so with nothing to turn on it behaves exactly as the standard edition does. If the user
asks what the advanced edition does, say that. Do not describe capabilities from anywhere else.

## Turning capabilities on and off

- **Never turn a capability on** - not with a tool, a command, a setting or a file, and not when
  the user asks you to. A capability is turned on only in the Dashboard, by the user, after its
  statement; if they ask, tell them that is where it is.
- Turning a capability off, or all advanced features at once, is always allowed, and only ever
  does less. When a tool for it is available and the user asks, use it.
- Pause stops every capability along with everything else.

## Moving between editions

Moving between the standard and the advanced edition is a deliberate reinstall, never an update:
an update keeps the edition that is installed. Never change the installed edition on your own
initiative. Do it only when the user names the edition they want, and say first what it is.

# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The advanced edition's own code: the standard edition is everything else.

Core takes this package only from beside itself, in the same `src` directory as
`codex_auto_resume` (codex_auto_resume/edition.py), and reaches it only through `plug.py`, the
one module it imports from here. Every capability plugs in there, off until a person turns it
on in the Dashboard after reading what it does. There is none yet: v0.6.11-alpha builds the
edition and nothing the edition can do, so its plug answers every decision as the standard
edition's does.

    plug         the hooks core calls, each handed to the runtime
    runtime      the registry's capabilities, asked in the state each one is in
    registry     what a capability is: its points, statement revision, departures, ceilings
    statement    the five fields a person reads, in nine languages (locales/)
    standards    the ids a capability may depart from
    arming       who turns a capability on and off, and the tripwires
    policy       what an administrator's policy keys allow, read only
    ledger       the one claim, counted across both editions' records and paid for (P11)
    surfaces     the Dashboard's bridge commands and a model's MCP tools (P10)
    state/       config/advanced/advanced.sqlite, the edition's one file of state
    credentials  where a secret would go: Windows Credential Manager, and nowhere else
    vocabulary   every word the rest of it stores, journals or answers with

In the repository this lives under `advanced/`, outside every tree the standard build copies
(build/make_release.py, APP_TREES), so the standard archive has no way to hold it; only the
advanced build adds it, at payload/app/src. Every shipped file under `advanced/` carries the
line at the top of this one, so an audit of the standard archive can look for it.

Nothing is imported here. Importing the package runs this file, and core does that before it
knows whether it will take the plug.
"""

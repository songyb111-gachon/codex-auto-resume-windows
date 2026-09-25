# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The advanced edition's own code: the standard edition is everything else.

Core takes this package only from beside itself, in the same `src` directory as
`codex_auto_resume` (codex_auto_resume/edition.py), and reaches it only through `plug.py`, the
one module it imports from here. Every capability plugs in there, off until a person turns it
on in the Dashboard after reading what it does. There is none yet: v0.6.11-alpha builds the
edition and nothing the edition can do, so its plug answers everywhere as the standard
edition's does.

In the repository this lives under `advanced/`, outside every tree the standard build copies
(build/make_release.py, APP_TREES), so the standard archive has no way to hold it; only the
advanced build adds it, at payload/app/src. Every shipped file under `advanced/` carries the
line at the top of this one, so an audit of the standard archive can look for it.

Nothing is imported here. Importing the package runs this file, and core does that before it
knows whether it will take the plug.
"""

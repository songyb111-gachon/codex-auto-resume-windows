# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The App Server methods that live only in the advanced edition, and the session that speaks them.

Core talks to Codex through two things and no more: `codex queue`, and a finite helper opened
for the three methods in `codex/appserver.PROTOCOL_METHODS` and shut again. Everything the
measurement harness needs beyond those three is here, in the advanced package, so the standard
archive names none of it: `protocol` holds the extra method names and which measurement may call
which, and `session` is the one-turn helper that speaks them, follows a turn's notifications,
declines every request Codex makes of it, and always unsubscribes.

Nothing here runs on its own. The harness (measure.py) opens a session only when a person runs a
measurement, and the marker-free continuation's channel (engine/markerfree.py) and the goal
continuation (engine/goal.py) open one for their calls only when core hands them a send or calls
their route; the tests give each a fake, so no test opens a real Codex. `goals` reads Codex's goals
database, read-only and never a goal's words, for the goal continuation. `inuse` is which Codex
all of them are of: the one the watcher drives, as it told the plug.
"""
from .protocol import ADVANCED_METHODS, MEASUREMENT_METHODS, SessionRefused  # noqa: F401

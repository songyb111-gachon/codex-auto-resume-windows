# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The advanced edition's engine-side code: the plug points core asks as it sends a continuation.

P5 and P15 together are the marker-free continuation (engine/markerfree.py): a channel core
hands the one send to, and the answer that it carries no marker and is proven by the client id
core derives from the interruption. P16, P3 and P5 are the goal continuation (engine/goal.py): a
route core carries out for a conversation the app does not hold, which sets its goal - paused by a
usage limit - active again; the standard continuation held back while that goal carries the
conversation on; and, only where measurement M2b passed, a channel that sets the goal active before
the continuation it queues. P17 and P3 together (v0.6.13) are the capabilities that take up a
failure the standard edition handles otherwise, and relax its record at known_failure: the short
retries when Codex is at capacity (engine/capacity.py), and the rules for Codex's error codes and
the retries of failures nothing classified (engine/admitted.py).
"""

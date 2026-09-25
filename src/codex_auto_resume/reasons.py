"""What each interruption category is called, and what may be said or configured about it.

The classifier in `failures.py` decides WHAT happened, and nothing here may change that.
This is the other half: for a category the classifier produced, which label a person
sees, which continuation text is sent, which notification is raised, and whether the
category is even a legitimate thing to offer a Custom message for.

It exists because that half had been written five times. The engine knew that a usage
limit was different from a dropped stream; the settings schema knew six categories were
switchable; the Dashboard, the Codex panel and the notifications each carried their own
idea of how to word them. Five copies of one mapping is how a category ends up
recoverable, unswitchable and unnamed at the same time - which is what `auth_service_transient`
looked like between v0.5 and v0.6.2. It was worse than that: nothing ever produced it, so the
switch v0.6.3 gave it could never fire. v0.6.10 reserves it (failures.RESERVED).

Two rules keep this from becoming a second classifier:

* Every entry's `category` is a category `failures.py` produces or reserves, and every
  category the classifier can recover has an entry. `tests/test_reasons.py` asserts
  both directions, so neither file can grow a category the other has not heard of, and
  that every recoverable category is one something produces.
* Nothing here decides whether a recovery may proceed. `recoverable` restates what the
  classifier already concluded so that a surface can ask one question instead of
  importing two modules; it is not consulted by the engine's gates and cannot widen
  them. A category that is not recoverable has no continuation keys at all, which is
  the structural reason a Custom message can never be attached to one.
"""
from __future__ import annotations

from . import failures


class Reason:
    """One interruption category, as the product presents and configures it."""

    __slots__ = ("category", "recoverable", "label_key",
                 "standard_key", "detailed_key",
                 "has_reset_time", "configurable", "order")

    def __init__(self, category, *, recoverable, order=0, has_reset_time=False,
                 configurable=False):
        self.category = category
        self.recoverable = recoverable
        self.order = order
        # A usage limit is the one interruption that carries a real timestamp to wait
        # for. Everything else waits on a bounded ladder and has nothing to show, so a
        # surface that offers a countdown has to ask rather than assume.
        self.has_reset_time = has_reset_time
        # Whether a user may turn recovery of this category off. Kept beside the rest
        # so the settings surface and the message surface read one table.
        self.configurable = configurable
        self.label_key = "reason.%s" % category
        # Only a recoverable category is ever continued, so only a recoverable category
        # has text to send. This is what makes "Custom message for an unknown failure"
        # unrepresentable rather than merely discouraged.
        self.standard_key = "continuation.standard.%s" % category if recoverable else None
        self.detailed_key = "continuation.detailed.%s" % category if recoverable else None

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Reason(%r, recoverable=%r)" % (self.category, self.recoverable)


def _reason(category, **kwargs):
    return Reason(category, **kwargs)


# Order is presentation order: the one a person meets most often first, then the rest
# roughly by how familiar the words are. It is stable so a settings page, a preview
# dropdown and a notification never disagree about sequence.
_ENTRIES = (
    _reason(failures.USAGE_LIMIT, recoverable=True, order=1,
            has_reset_time=True, configurable=True),
    _reason("rate_limit_transient", recoverable=True, order=2, configurable=True),
    _reason("network_transient", recoverable=True, order=3, configurable=True),
    _reason("timeout", recoverable=True, order=4, configurable=True),
    _reason("server_5xx", recoverable=True, order=5, configurable=True),
    _reason("stream_interrupted", recoverable=True, order=6, configurable=True),
    # Present so that every category the classifier can produce has a label - a
    # Dashboard row for a failure nobody can recover still has to say something. None
    # of these carries continuation text, and none may be given a Custom message.
    _reason(failures.UNKNOWN, recoverable=False, order=50),
    _reason("terminal_auth", recoverable=False, order=51),
    _reason("terminal_permission", recoverable=False, order=52),
    _reason("terminal_policy", recoverable=False, order=53),
    _reason("terminal_user", recoverable=False, order=54),
    _reason("terminal_invalid", recoverable=False, order=55),
    _reason("terminal_failure", recoverable=False, order=56),
    # Reserved (failures.RESERVED): nothing produces it. Its label stays so a row that names
    # it still reads; it has no switch, no continuation text and no Custom message.
    _reason("auth_service_transient", recoverable=False, order=57),
)

REASONS = {entry.category: entry for entry in _ENTRIES}

# The categories a continuation may be built for, in presentation order. This is the
# list a Preview dropdown offers and the list per-reason Custom editors are generated
# from, so a surface cannot offer a Custom message for something that is never sent.
RECOVERABLE = tuple(entry.category for entry in
                    sorted((e for e in _ENTRIES if e.recoverable),
                           key=lambda e: e.order))

ALL = tuple(entry.category for entry in sorted(_ENTRIES, key=lambda e: e.order))


def get(category) -> Reason:
    """The entry for a category, falling back to `unknown`.

    A category this table has not heard of is a bug the tests catch, and it is still
    not a reason to show a person an empty label.
    """
    return REASONS.get(category) or REASONS[failures.UNKNOWN]


def is_recoverable(category) -> bool:
    entry = REASONS.get(category)
    return bool(entry and entry.recoverable)


def label_key(category) -> str:
    return get(category).label_key


def has_reset_time(category) -> bool:
    return get(category).has_reset_time


def configurable() -> tuple:
    """Categories with a user-facing on/off switch, in presentation order."""
    return tuple(entry.category for entry in
                 sorted((e for e in _ENTRIES if e.configurable), key=lambda e: e.order))

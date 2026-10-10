# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Codex's usage read as the reset actions keep it: core's windows, how many reset credits there are,
and when the soonest of them expires - and nothing else.

Core reads usage to an allowlist of numbers and drops the credits (codex/usage.py, B10). The reset
actions need two more numbers from the same reply - `rateLimitResetCredits.availableCount`, and the
soonest `expiresAt` of the credits it lists - so they are read here, over core's own parse: the
windows are exactly what core keeps (domain/usage.windows_of), and of the credits nothing but those
two numbers survives. Never a credit's id, title, description, grant time or type, never the account
or the plan: a reply that grows cannot start carrying something this edition then keeps. The reply's
`ordinaryUsageAllowed` is read as the boolean it is, for the measurements alone (measure._mr).

Codex's schema (0.159.0-alpha.12.1, GetAccountRateLimitsResponse): `credits` is null where only the
count is known - asked with `excludeResetCreditDetails`, say - and a list where the details were read;
the list may be capped below the count; a credit's `expiresAt` is null where it never expires. So the
expiry is known only from a list that holds an available credit, or where there is none to expire; a
null list, a list with no available credit beside a count above zero, and anything of another shape
are an expiry that cannot be read - and the owner's rule is that no credit is spent then
(engine/credits.py).

Pure: nothing is read here but the reply it is handed.
"""
from __future__ import annotations

from codex_auto_resume import machine
from codex_auto_resume.codex.usage import parse_usage
from codex_auto_resume.domain import usage as readings

from ..vocabulary import SpendOutcome

READ = "account/rateLimits/read"
CONSUME = "account/rateLimitResetCredit/consume"
# The read's params: a detailed read, and one that leaves the credits' details out - the count stays
# (the schema's `excludeResetCreditDetails`, for a background poll), sent only where MU passed.
DETAILED = {}
LIGHT = {"excludeResetCreditDetails": True}
# Codex's words for what a consume came to, as this edition stores them.
OUTCOMES = {"reset": SpendOutcome.RESET, "nothingToReset": SpendOutcome.NOTHING_TO_RESET,
            "noCredit": SpendOutcome.NO_CREDIT, "alreadyRedeemed": SpendOutcome.ALREADY_REDEEMED}
AVAILABLE = "available"
# More credits than anyone holds is no count this edition believes.
MAX_COUNT = 1000


def _count(value):
    return value if type(value) is int and 0 <= value <= MAX_COUNT else None


def _expiry(value):
    """A credit's `expiresAt` as kept: whole seconds, None for one that never expires - or False for
    anything else, which is an expiry that cannot be read."""
    if value is None:
        return None
    return value if machine.epoch(value, *machine.EPOCH_USAGE, integer=True, exact=True, finite=False) else False


def _soonest(count, listed):
    """(whether the expiry is known, the soonest one or None) of `count` credits whose details are
    `listed`."""
    if count is None:
        return False, None
    if count == 0:
        return True, None                             # nothing to expire
    if not isinstance(listed, list):
        return False, None                            # only the count is known
    expiries = []
    for credit in listed:
        if not isinstance(credit, dict) or not isinstance(credit.get("status"), str):
            return False, None
        if credit["status"] != AVAILABLE:
            continue
        found = _expiry(credit.get("expiresAt"))
        if found is False:
            return False, None
        expiries.append(found)
    if not expiries:
        return False, None                            # a capped list: the available ones are not shown
    dated = [at for at in expiries if at is not None]
    return True, (min(dated) if dated else None)


def parse(reply) -> dict:
    """What the reset actions keep of one usage reply:

        windows                 core's windows (domain/usage.windows_of), or None for no reading
        credits                 the count of reset credits, or None where it cannot be read
        expiry_known            whether when the soonest of them expires can be read
        nearest_expiry          that moment, in whole seconds, or None - none to expire, or none expires
        ordinary_usage_allowed  Codex's own boolean, or None

    Nothing else of the reply, whatever it holds."""
    windows = readings.windows_of(parse_usage(reply))
    summary = reply.get("rateLimitResetCredits") if isinstance(reply, dict) else None
    count = _count(summary.get("availableCount")) if isinstance(summary, dict) else None
    known, soonest = _soonest(count, summary.get("credits") if isinstance(summary, dict) else None)
    allowed = reply.get("ordinaryUsageAllowed") if isinstance(reply, dict) else None
    return {"windows": windows, "credits": count, "expiry_known": known, "nearest_expiry": soonest,
            "ordinary_usage_allowed": allowed if type(allowed) is bool else None}


def details_listed(reply) -> bool:
    """Whether the reply carries the credits' details - a list, empty or not - rather than only their
    count (MU: a detailed read has them, a light one does not)."""
    summary = reply.get("rateLimitResetCredits") if isinstance(reply, dict) else None
    return isinstance(summary, dict) and isinstance(summary.get("credits"), list)


def outcome(reply) -> SpendOutcome:
    """What a consume came to: one of Codex's four outcomes in this edition's words, or UNKNOWN for a
    reply of any other shape - never taken for one of the four."""
    found = reply.get("outcome") if isinstance(reply, dict) else None
    return OUTCOMES.get(found, SpendOutcome.UNKNOWN) if isinstance(found, str) else SpendOutcome.UNKNOWN


def full(windows) -> list:
    """The windows of a reading that are full: at 100 % or more, with a reset time."""
    return [window for window in windows or () if window["used_percent"] >= 100 and window["reset_at"] is not None]

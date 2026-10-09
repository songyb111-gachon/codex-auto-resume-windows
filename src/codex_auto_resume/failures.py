"""Classification of a failed Codex turn into one recovery category.

Everything here is decided from *structured* values that Codex itself writes:
the `codexErrorInfo` variant first, then an HTTP status carried by that variant.
A message is consulted only when there is no structured code at all, and only to
recognise a short list of unambiguous transport failures that have no code.

The rule that matters: an error this module cannot place is `unknown`, and
`unknown` is never retried. Adding a code to the wrong bucket is far worse than
leaving it unclassified, so anything doubtful is left out on purpose.

No error text leaves this module. Callers receive a category name only - and, from v0.6.14, for
the edition's plug (domain/plug.py, P17) the error's shape: Codex's own code, a status number, the
form the error took and whether it had a message, never the message (`shape`). What core would take
up of a failure it never recovers alone is decided here too, by a fence no plug can widen (`admits`).
"""
from __future__ import annotations

import re

from .domain.plug import PACED_AS, TAKE_UP, Alternative, FailureForm
from .domain.vocabulary import FailureCategory

USAGE_LIMIT = "usage_limit"
UNKNOWN = "unknown"

# Recovered automatically, with a bounded backoff (never the usage-limit policy). Each one is
# produced by a CODES entry, a status rule or a message pattern below; a name nothing produces
# does not belong here (tests/test_reasons.py, ReachabilityTests).
TRANSIENT = frozenset({
    "network_transient", "timeout", "rate_limit_transient",
    "server_5xx", "stream_interrupted",
})
# Words the vocabulary keeps and nothing here produces. `auth_service_transient` was in TRANSIENT
# from v0.4.0 to v0.6.9 - with a switch, a reason and a Custom message from v0.6.3 - yet no code,
# status or message ever mapped to it, so the switch could never fire. v0.6.10 reserves it: it is
# never classified and never recovered, it is offered nowhere, and the word stays so a row or a
# settings file that names it still reads. It comes back through CODES only when a real,
# structured Codex error is seen to carry it.
RESERVED = frozenset({"auth_service_transient"})
# Known, and known to need a person. Never retried, but not "unknown" either.
TERMINAL = frozenset({
    "terminal_user", "terminal_permission", "terminal_policy",
    "terminal_invalid", "terminal_auth", "terminal_failure",
})
# Every category, each one of the above, the usage limit or unknown (tests/test_vocabulary.py).
# RESERVED is among them: a stored row may name it, and it is read as the word it is.
CATEGORIES = frozenset(FailureCategory)

# The `CodexErrorInfo` variants this engine build actually defines. Verified against
# codex-cli 0.153.4; an unlisted variant classifies as `unknown` and stops.
CODES = {
    "usageLimitExceeded": USAGE_LIMIT,
    # Transient
    "rateLimitExceeded": "rate_limit_transient",
    "serverOverloaded": "server_5xx",
    "internalServerError": "server_5xx",
    "httpConnectionFailed": "network_transient",
    "responseStreamConnectionFailed": "stream_interrupted",
    "responseStreamDisconnected": "stream_interrupted",
    # Terminal: a person has to decide something
    "contextWindowExceeded": "terminal_invalid",
    "sessionBudgetExceeded": "terminal_invalid",
    "badRequest": "terminal_invalid",
    "cyberPolicy": "terminal_policy",
    "misalignmentPolicyViolation": "terminal_policy",
    "unauthorized": "terminal_auth",
    # Terminal: retrying cannot help. `responseTooManyFailedAttempts` in particular
    # means Codex already retried and gave up, so trying again is not a fresh attempt.
    "responseTooManyFailedAttempts": "terminal_failure",
    "threadRollbackFailed": "terminal_failure",
    "sandboxError": "terminal_failure",
    "activeTurnNotSteerable": "terminal_failure",
}

# Keys a tagged-enum payload may use to name its variant.
_TAG_KEYS = ("type", "kind", "tag", "variant", "code")
_STATUS_KEYS = ("httpStatusCode", "http_status_code", "status", "statusCode", "status_code")

# Consulted ONLY when no structured code exists. Deliberately short: each phrase must
# be a transport failure that cannot also describe a permanent, request-level problem.
_MESSAGE_PATTERNS = (
    (re.compile(r"\b(deadline exceeded|timed out|timeout)\b"), "timeout"),
    (re.compile(r"\b(connection reset|connection refused|connection closed|broken pipe)\b"), "network_transient"),
    (re.compile(r"\b(name resolution|dns (?:error|failure)|temporary failure in name resolution)\b"), "network_transient"),
    (re.compile(r"\b(tls handshake|handshake failed)\b"), "network_transient"),
    (re.compile(r"\b(stream (?:disconnected|ended unexpectedly)|incomplete stream)\b"), "stream_interrupted"),
)


def _status_category(status) -> str:
    if type(status) is not int:
        return UNKNOWN
    if status in (408, 425):
        return "timeout"
    if status == 429:
        return "rate_limit_transient"
    if 500 <= status <= 599:
        return "server_5xx"
    if status in (401, 403):
        return "terminal_auth"
    if status == 404:
        return "terminal_invalid"
    if 400 <= status <= 499:
        return "terminal_invalid"
    return UNKNOWN


def _tag_and_status(info):
    """Accept both shapes: a bare variant name, or a tagged object with a payload."""
    if isinstance(info, str):
        return info, None
    if not isinstance(info, dict):
        return None, None
    tag = None
    for key in _TAG_KEYS:
        value = info.get(key)
        if isinstance(value, str) and value:
            tag = value
            break
    if tag is None and len(info) == 1:
        # Serde's externally tagged form: {"httpStatusCode": 503}
        (tag, payload), = info.items()
        if type(payload) is int:
            return tag, payload
        info = payload if isinstance(payload, dict) else {}
    status = None
    for key in _STATUS_KEYS:
        value = info.get(key) if isinstance(info, dict) else None
        if type(value) is int:
            status = value
            break
    return tag, status


def classify(error_info, message=None) -> str:
    """Return exactly one category name. Never raises, never returns error text."""
    tag, status = _tag_and_status(error_info)
    if tag == "responseTooManyFailedAttempts" and status == 429:
        # Codex gave up after its own retries, and the last thing the service said was
        # "slow down". That is a rate limit, not a broken request, so it waits out a
        # backoff like one - bounded by the per-task continuation cap, and switched off
        # with the rate-limit category. Any other status, or none, stays terminal.
        return "rate_limit_transient"
    if isinstance(tag, str):
        category = CODES.get(tag)
        if category is not None:
            return category
        # A variant that carries a status but is not in CODES is still classifiable
        # from the status itself; anything else stays unknown.
        if status is not None:
            return _status_category(status)
        return UNKNOWN
    if status is not None:
        return _status_category(status)
    if error_info is not None:
        return UNKNOWN            # present but unrecognisable: never guess from text
    if isinstance(message, str) and 0 < len(message) <= 4096:
        text = message.lower()
        for pattern, category in _MESSAGE_PATTERNS:
            if pattern.search(text):
                return category
    return UNKNOWN


# v0.6.11: a wait the service named - a Retry-After - where Codex carries one in the structured error
# itself. Whole seconds, at most a day; never read from message text, and only ever a floor under the
# first wait of a temporary failure (ladder.py), never a reason to go sooner.
_RETRY_AFTER_KEYS = ("retryAfterSeconds", "retry_after_seconds", "retryAfter", "retry_after")
MAX_RETRY_AFTER = 86400


def wait_seconds(value):
    """A named wait as it is kept: whole seconds from 1 to a day, or None."""
    return value if type(value) is int and 0 < value <= MAX_RETRY_AFTER else None


def retry_after(error_info):
    """The wait in seconds a structured error names, or None. No Codex build has been seen to write
    one; this reads it where one does, in the variant's own payload, and nowhere else."""
    payload = error_info
    if isinstance(payload, dict) and len(payload) == 1 and not any(key in payload for key in _TAG_KEYS):
        (_tag, payload), = payload.items()
    if not isinstance(payload, dict):
        return None
    for key in _RETRY_AFTER_KEYS:
        found = wait_seconds(payload.get(key))
        if found is not None:
            return found
    return None


def is_recoverable(category: str) -> bool:
    return category == USAGE_LIMIT or category in TRANSIENT


# v0.6.14 (stage 3b): what the edition's plug may take up (domain/plug.py, P17) of a failure the
# standard edition never recovers alone, and the fence core holds every answer to. A code is a
# structured value Codex chose - letters and digits - and never message text (B9).
TAG_SHAPE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")
ADMISSIBLE = frozenset({UNKNOWN, "terminal_auth", "terminal_failure"})
# A code containing one of these, ignoring case, may name something a person decides or must fix -
# a policy, a budget, a permission, a sign-in, a cancel - so nothing ever takes it up or relaxes it.
# Broad on purpose: a false match leaves a failure for the person, a miss could retry a refusal.
DECISION_FRAGMENTS = (
    "policy", "budget", "quota", "limit", "permission", "forbidden", "denied", "deny", "refus",
    "approv", "auth", "sign", "login", "credential", "token", "cancel", "abort", "interrupt", "user",
    "billing", "payment", "credit", "plan", "safety", "violation", "moderat", "blocked", "sandbox",
    "context",
)


def decision_tag(code) -> bool:
    """Whether a code may name a decision of a person's (DECISION_FRAGMENTS)."""
    return isinstance(code, str) and any(fragment in code.lower() for fragment in DECISION_FRAGMENTS)


def shape(error_info, message=None) -> dict:
    """What a failure's structured error says of itself: {code, status, form, has_message}.

    `code` is the variant's tag when it is one of CODES or of the shape of one (TAG_SHAPE), else None;
    `status` a number from 100 to 599, else None; `form` a FailureForm; `has_message` only whether a
    message exists. Nothing of the message is kept, and no other string."""
    has_message = isinstance(message, str) and bool(message.strip())
    tag, status = _tag_and_status(error_info)
    status = status if type(status) is int and 100 <= status <= 599 else None
    if isinstance(tag, str) and tag in _STATUS_KEYS:
        tag = None                           # {"httpStatusCode": 503}: a status, named as one
    if error_info is None:
        form, code = (FailureForm.MESSAGE_ONLY if has_message else FailureForm.ABSENT), None
    elif isinstance(tag, str) and (tag in CODES or TAG_SHAPE.fullmatch(tag)):
        form, code = FailureForm.TAGGED, tag
    elif tag is None and status is not None:
        form, code = FailureForm.STATUS_ONLY, None
    else:
        form, code = FailureForm.UNRECOGNISED, None
    return {"code": code, "status": status, "form": form, "has_message": has_message}


def _plain_code(facts) -> bool:
    """A code of Codex's this product does not know, naming no decision, and no 4xx beside it."""
    code, status = facts.get("code"), facts.get("status")
    return (facts.get("form") == FailureForm.TAGGED and isinstance(code, str) and code not in CODES
            and not decision_tag(code) and (status is None or not 400 <= status <= 499))


# The kind whose switch in Settings each relaxation follows.
_FOLLOWS = {**PACED_AS, Alternative.CAPACITY: "server_5xx"}


def admits(facts, answer) -> bool:
    """Whether core would carry out `answer` for the failure `facts` describe (a category and its
    `shape`), whatever a plug says. Only a tagged failure ever: no code, a message alone, a status
    alone or something unrecognised says nothing of what failed. A sign-in failure only as Codex's
    `unauthorized` or a 401 - never a 403, a permission - and Codex giving up only on a server error
    or none, a 429 being a rate limit already. CAPACITY only for Codex saying it is at capacity
    (`serverOverloaded`), never another server error."""
    category, code, status = facts.get("category"), facts.get("code"), facts.get("status")
    if answer == Alternative.CAPACITY:
        return category == "server_5xx" and code == "serverOverloaded"
    if answer in PACED_AS:
        return category == UNKNOWN and _plain_code(facts)
    if answer != Alternative.ADMIT:
        return False
    if category == UNKNOWN:
        return _plain_code(facts)
    if category == "terminal_auth" and code == "unauthorized":
        return status in (None, 401)
    if category == "terminal_auth":
        return _plain_code(dict(facts, status=None)) and status == 401
    if category == "terminal_failure":
        return code == "responseTooManyFailedAttempts" and (status is None or 500 <= status <= 599)
    return False


def takes(facts, recovers) -> frozenset:
    """The answers core would carry out for this failure now (domain/plug.py, P17's `takes`): each
    that `admits` allows, less one whose kind is switched off in Settings (`recovers`). Empty, and the
    plug is not asked."""
    return frozenset(answer for answer in TAKE_UP if admits(facts, answer)
                     and (answer not in _FOLLOWS or recovers(_FOLLOWS[answer])))


def readmits(category, answer) -> bool:
    """Whether known_failure (P3) takes `answer` for a record of `category` that P17 took up."""
    if answer == Alternative.ADMIT:
        return category in ADMISSIBLE
    if answer == Alternative.CAPACITY:
        return category == "server_5xx"
    return answer in PACED_AS and category == UNKNOWN

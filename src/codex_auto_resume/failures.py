"""Classification of a failed Codex turn into one recovery category.

Everything here is decided from *structured* values that Codex itself writes:
the `codexErrorInfo` variant first, then an HTTP status carried by that variant.
A message is consulted only when there is no structured code at all, and only to
recognise a short list of unambiguous transport failures that have no code.

The rule that matters: an error this module cannot place is `unknown`, and
`unknown` is never retried. Adding a code to the wrong bucket is far worse than
leaving it unclassified, so anything doubtful is left out on purpose.

No error text leaves this module. Callers receive a category name only.
"""
from __future__ import annotations

import re

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


def is_recoverable(category: str) -> bool:
    return category == USAGE_LIMIT or category in TRANSIENT

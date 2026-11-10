"""The capability URIs a notice's buttons carry, and the one reader of each.

Windows hands a toast's button back to this product as a `codex-auto-resume:` URI, in a process that starts for it. A URI
can only name what it may do: cancel one interruption, open one page from a closed list, stop one batch's power action.
Each reader refuses anything else, so a page that merely knows the scheme can at worst open a window.
"""
from __future__ import annotations

from . import machine
from .domain import ids

SCHEME = "codex-auto-resume"


def cancel_uri(interruption_id: str) -> str:
    """Capability URI for one interruption.

    The interruption id is an unguessable local identifier, so a page that merely knows
    the scheme cannot target a real record. The only action it can ever perform is
    *cancelling* a resume, which fails in the safe direction.
    """
    return "%s:cancel?i=%s" % (SCHEME, interruption_id)


def parse_cancel_uri(uri: str) -> str | None:
    """Return the interruption id, or None when the URI is not a valid cancel request."""
    from urllib.parse import parse_qs, urlsplit

    try:
        parts = urlsplit(str(uri))
    except (ValueError, TypeError):
        return None
    if parts.scheme.lower() != SCHEME:
        return None
    # Windows may hand the URI over as "codex-auto-resume:cancel?..." (opaque path).
    action = (parts.path or parts.netloc or "").strip("/").lower()
    if action != "cancel":
        return None
    values = parse_qs(parts.query).get("i") or []
    if len(values) != 1:
        return None
    return ids.read_interruption_id(values[0])


# v0.6.18: a cancel URI may carry the watcher's decision that a notice about one conversation offers Open Codex (an
# edition's, notifier.with_open_codex), so the notice that says the cancel happened - raised by the separate process
# Windows starts for a toast's button, which loads no plug (commands/watcher.cmd_activate) - offers it too. The flag
# only ever adds that button, for the cancelled record's own conversation; parse_cancel_uri passes it over.
OPEN_CODEX_FLAG = "c"


def with_open_codex_flag(uri: str) -> str:
    """A cancel URI with the Open Codex flag on it; any other URI as it is."""
    if parse_cancel_uri(uri) is None or cancel_asks_open_codex(uri):
        return uri
    return "%s&%s=1" % (uri, OPEN_CODEX_FLAG)


def cancel_asks_open_codex(uri) -> bool:
    """Whether a valid cancel URI carries the Open Codex flag, exactly once and exactly 1."""
    from urllib.parse import parse_qs, urlsplit

    if parse_cancel_uri(uri) is None:
        return False
    try:
        values = parse_qs(urlsplit(str(uri)).query).get(OPEN_CODEX_FLAG) or []
    except (ValueError, TypeError):
        return False
    return values == ["1"]


def open_uri(page: str = "pending") -> str:
    """Capability URI that opens one page of the Dashboard.

    Like cancelling, it cannot make anything happen that should not: it names a page
    from a closed list, it changes no state, and a hostile page that knows the scheme can
    at worst open a window.
    """
    return "%s:open?page=%s" % (SCHEME, page)


def parse_open_uri(uri: str) -> str | None:
    """Return the page, or None when the URI is not a valid open request."""
    from urllib.parse import parse_qs, urlsplit

    try:
        parts = urlsplit(str(uri))
    except (ValueError, TypeError):
        return None
    if parts.scheme.lower() != SCHEME:
        return None
    action = (parts.path or parts.netloc or "").strip("/").lower()
    if action != "open":
        return None
    values = parse_qs(parts.query).get("page") or []
    if len(values) != 1:
        return None
    page = values[0].strip().lower()
    # The same closed list the icon uses, from where both can read it without importing the
    # other's window code.
    return page if page in machine.PAGES else None


def power_stop_uri(nonce: str) -> str:
    """Capability URI that stops the power action for one batch (v0.6.12, the A28 amendment).

    The nonce names the batch: 16 hex digits, new at every arming and at every batch's end, so a page
    that merely knows the scheme cannot name one, and a notice of a batch that is over - still in the
    notification center - stops nothing. Like cancelling, it can only take automation away: the PC
    stays on this time.
    """
    return "%s:power-stop?n=%s" % (SCHEME, nonce)


def parse_power_stop_uri(uri: str) -> str | None:
    """Return the batch's nonce, or None when the URI is not a valid power-stop request: exactly one
    `n` of 16 lowercase hex digits."""
    from urllib.parse import parse_qs, urlsplit

    try:
        parts = urlsplit(str(uri))
    except (ValueError, TypeError):
        return None
    if parts.scheme.lower() != SCHEME:
        return None
    action = (parts.path or parts.netloc or "").strip("/").lower()
    if action != "power-stop":
        return None
    values = parse_qs(parts.query, keep_blank_values=True).get("n") or []
    if len(values) != 1 or set(parse_qs(parts.query, keep_blank_values=True)) != {"n"}:
        return None
    return values[0] if ids.is_power_nonce(values[0]) else None

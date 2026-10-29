# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What an address a person types must be before the courier keeps it or sends to it - pure string checks, no network.

A push goes only to an `https` address of a named host: never `http`, never a user name or password in the address
(a user and password before the host), never an IP literal and never a loopback name (`localhost`, `*.localhost`) - a webhook on
this PC is the loopback API's business, not a push - and never one longer than MAX_URL. Every refusal is one closed
word (AddressRefused.word), never the address. The e-mail server's host is held to the same host rules; its addresses
and its user to shapes that cannot carry a line break, so no header can be injected through them.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

MAX_URL = 2048
MAX_TOKEN = 512
# A host name: letters, digits and hyphens in dot-separated labels, at least one dot (a bare name is a LAN host), no
# label longer than 63, the whole at most 253.
_LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)\Z")
# Telegram's bot token (<digits>:<35 or so of base64url>) and a chat id (a number, negative for a group).
TELEGRAM_TOKEN = re.compile(r"[0-9]{1,20}:[A-Za-z0-9_-]{20,100}\Z")
TELEGRAM_CHAT = re.compile(r"-?[0-9]{1,20}\Z")
# A bearer token or an SMTP password/user: printable ASCII with no space, no line break.
_PRINTABLE = re.compile(r"[!-~]{1,%d}\Z" % MAX_TOKEN)
# An e-mail address, conservatively: no space, no line break, one @, a host with a dot.
_MAILBOX = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9.-]{3,253}\Z")
SMTP_PORTS = (465, 587)


class AddressRefused(ValueError):
    """An address that may not be kept or used. `word` says why, and nothing says what it was."""

    def __init__(self, word):
        self.word = word
        super().__init__(word)


def host_problem(host) -> str | None:
    """Why `host` may not be pushed to, or None: not a name, an IP literal, a loopback name, a bare LAN name."""
    if not isinstance(host, str) or not host or len(host) > 253:
        return "host"
    name = host.rstrip(".").lower()
    try:
        ipaddress.ip_address(name.strip("[]"))
        return "ip_literal"
    except ValueError:
        pass
    if name == "localhost" or name.endswith(".localhost"):
        return "loopback"
    labels = name.split(".")
    if len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        return "host"
    return None


def checked_url(url) -> str:
    """`url` where a push may go, as it was given; AddressRefused otherwise."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise AddressRefused("url")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise AddressRefused("url") from None
    if parts.scheme.lower() != "https":
        raise AddressRefused("not_https")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise AddressRefused("userinfo")
    problem = host_problem(parts.hostname)
    if problem is not None:
        raise AddressRefused(problem)
    if port is not None and not 1 <= port <= 65535:
        raise AddressRefused("url")
    return url


def checked_token(token, *, shape=None) -> str:
    """A bearer token, a password or a bot token: printable, no space or line break, at most MAX_TOKEN - or of `shape`."""
    if not isinstance(token, str) or not (shape or _PRINTABLE).match(token):
        raise AddressRefused("token")
    return token


def checked_mailbox(address) -> str:
    if not isinstance(address, str) or not _MAILBOX.match(address) or host_problem(address.rpartition("@")[2]):
        raise AddressRefused("mailbox")
    return address


def checked_smtp(blob) -> dict:
    """The e-mail channel's settings - host, port (465 or 587), user, password, from, to - each checked; the dict a
    courier keeps as one secret. AddressRefused otherwise."""
    if not isinstance(blob, dict) or set(blob) != {"host", "port", "user", "password", "from", "to"}:
        raise AddressRefused("smtp")
    problem = host_problem(blob["host"])
    if problem is not None:
        raise AddressRefused(problem)
    if type(blob["port"]) is not int or blob["port"] not in SMTP_PORTS:
        raise AddressRefused("port")
    return {"host": blob["host"], "port": blob["port"], "user": checked_token(blob["user"]),
            "password": checked_token(blob["password"]), "from": checked_mailbox(blob["from"]),
            "to": checked_mailbox(blob["to"])}

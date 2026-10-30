# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What the courier keeps, and where - with no network: push_notices' secrets in Windows Credential Manager, and
Telegram's one-time pairing in the `remote` table. The Dashboard's service reads and writes these (control/courier.py)
without loading any code that sends.

Secrets (credentials.py: CodexAutoResume/advanced/push_notices/<name>, SECRETS): the ntfy topic's address, the
webhook's address and its optional bearer token, the Telegram bot's token and the paired chat, and the e-mail
channel's settings as one JSON blob of at most 2,560 bytes. None of them is kept anywhere else - not advanced.sqlite,
settings, a log, the journal, diagnostics or a golden - and none is ever answered to the Dashboard: it is told only
which are saved.

The pairing: the Dashboard shows a code of six digits and keeps only its SHA-256 digest and when it expires
(PAIR_SECONDS) - `begin_pairing`; a courier run with `--pair` keeps the chat whose message is that code
(channels.pair).
"""
from __future__ import annotations

import hashlib
import re

CAPABILITY = "push_notices"
SECRETS = ("ntfy_url", "webhook_url", "webhook_token", "telegram_token", "telegram_chat", "smtp")
# What each channel keeps, and what it must have kept to send (the webhook's token is optional).
CHANNEL_SECRETS = {"ntfy": ("ntfy_url",), "webhook": ("webhook_url", "webhook_token"),
                   "telegram": ("telegram_token", "telegram_chat"), "email": ("smtp",)}
NEEDED = {"ntfy": ("ntfy_url",), "webhook": ("webhook_url",), "telegram": ("telegram_token", "telegram_chat"),
          "email": ("smtp",)}
PAIR_SECONDS = 120
BAD_CODES = 5
CODE = re.compile(r"[0-9]{6}\Z")


class NotSaved(Exception):
    """The channel's address or secret is not in Credential Manager."""


def secrets_of(registry):
    """push_notices' secrets, kept in Windows Credential Manager (credentials.py)."""
    from ..credentials import Secrets
    return Secrets(registry)


def read(secrets, name):
    found = secrets.read(CAPABILITY, name)
    return found if isinstance(found, str) and found else None


def saved(secrets, channel) -> bool:
    """Whether everything `channel` needs to send is kept. False where Credential Manager cannot be read."""
    try:
        return all(read(secrets, name) is not None for name in NEEDED[channel])
    except Exception:
        return False


def digest(code) -> str:
    return hashlib.sha256(str(code).encode("ascii")).hexdigest()


def begin_pairing(state, code, now) -> None:
    """Keep the digest of the one-time `code` and when it expires (`remote`, channel telegram)."""
    if not isinstance(code, str) or not CODE.match(code):
        raise ValueError("code")
    with state._transaction() as connection:
        connection.execute("INSERT INTO remote (channel, paired_at, bad_codes, update_offset, code_digest, "
                           "code_expires_at) VALUES ('telegram', NULL, 0, NULL, ?, ?) ON CONFLICT(channel) DO UPDATE "
                           "SET paired_at = NULL, bad_codes = 0, code_digest = excluded.code_digest, "
                           "code_expires_at = excluded.code_expires_at", (digest(code), float(now + PAIR_SECONDS)))


def pairing(state):
    """The `remote` row of telegram as a dict, or None."""
    with state._read() as connection:
        if connection is None:
            return None
        row = connection.execute("SELECT * FROM remote WHERE channel = 'telegram'").fetchone()
    return dict(row) if row is not None else None

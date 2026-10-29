# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Which Codex account is signed in, and Codex's own sign-out and sign-in (account_switch, v0.6.20).

`read` asks the app server account/read through a finite session of this capability's own (codex/protocol.py, its one
row of CAPABILITY_METHODS) and answers {present, plan_word, email, kind}: whether an account is signed in - None where
the answer was not one Codex gives - its plan as a closed word (vocabulary.PlanWord), its e-mail address and its kind
("chatgpt", "apikey"). The address goes to the caller in this process only: the Dashboard's card shows `mask` of it and
the watcher keeps `digest` of it, keyed by a salt of this installation's own; neither stores the address.

`switch` is the one way this product signs anyone out or in, and it is not a route of its own: the product never asks
Codex for a sign-in method (protocol.FORBIDDEN_METHODS stays as it is) - it runs Codex's own `codex logout` and then
`codex login`, the engine the product already drives, each as an argument list with no shell, no console
(CREATE_NO_WINDOW), the environment core's codex children have (C10: the backend's own argv and environment), started in
the Dashboard's job object (KILL_ON_JOB_CLOSE, report/github.run_process's chain), so a sign-in still waiting when the
Dashboard's service ends is ended with it. `codex login` starts Codex's own local callback and opens the default browser
on Codex's sign-in page; the person signs in there, and nothing they type passes through this product. It is waited for
LOGIN_SECONDS at most. Only the Dashboard's command handler calls it (control/account.py).
"""
from __future__ import annotations

import hashlib
import hmac

from ..vocabulary import PlanWord

CAPABILITY = "account_switch"
READ = "account/read"
# How long `codex logout` and `codex login` are each waited for, in seconds: a sign-in in the browser takes as long as
# the person takes, up to ten minutes.
LOGOUT_SECONDS = 60
LOGIN_SECONDS = 600
# What a switch came to (the card's result word, never stored): signed in again, left signed out (the person cancelled
# in the browser), still not done after LOGIN_SECONDS, or Codex could not be run.
SIGNED_IN, CANCELLED, TIMED_OUT, FAILED = "signed_in", "cancelled", "timed_out", "failed"
OUTCOMES = (SIGNED_IN, CANCELLED, TIMED_OUT, FAILED)
# The kinds of account Codex names (its Account type), and the one that has an address.
KINDS = ("chatgpt", "apikey")
# A shown address's hidden part.
HIDDEN = "•••"
SALT_BYTES = 32
DIGEST_HEX = 16
_PLANS = frozenset(str(word) for word in PlanWord)


def plan_word(value):
    """Codex's plan type as a closed word: one of PlanWord, `other` for any other string, None for none."""
    if not isinstance(value, str) or not value:
        return None
    word = value.strip().lower()
    return word if word in _PLANS else str(PlanWord.OTHER)


def parse(reply) -> dict:
    """{present, plan_word, email, kind} of an account/read answer. `present` None - and nothing else - where `reply`
    is not one Codex gives: a failed read is never taken as signed out (E1). Pure."""
    unknown = {"present": None, "plan_word": None, "email": None, "kind": None}
    if not isinstance(reply, dict) or "account" not in reply:
        return unknown
    account = reply.get("account")
    if account is None:
        return {"present": False, "plan_word": None, "email": None, "kind": None}
    if not isinstance(account, dict):
        return unknown
    kind = account.get("type")
    kind = kind.lower() if isinstance(kind, str) and kind.lower() in KINDS else None
    email = account.get("email")
    email = email.strip() if isinstance(email, str) and "@" in email.strip() and len(email.strip()) <= 320 else None
    return {"present": True, "plan_word": plan_word(account.get("planType", account.get("plan_type"))),
            "email": email, "kind": kind}


def identity(found):
    """The text an account is told apart by: its address in lower case, or its kind where it has none ("kind:apikey"),
    or None where neither is known - an account that cannot be told apart is never "another one". Pure."""
    if not isinstance(found, dict) or found.get("present") is not True:
        return None
    if found.get("email"):
        return found["email"].lower()
    return "kind:" + found["kind"] if found.get("kind") else None


def digest(text, salt) -> str:
    """16 hex characters of HMAC-SHA256 over `text`, keyed by `salt` (hex): what the watcher keeps of an account
    (state `account_seen`), never the address. Pure."""
    if not isinstance(text, str) or not text or not isinstance(salt, str) or not salt:
        raise ValueError("an identity and a salt")
    return hmac.new(bytes.fromhex(salt), text.encode("utf-8"), hashlib.sha256).hexdigest()[:DIGEST_HEX]


def new_salt() -> str:
    """32 random bytes, as hex: this installation's salt, kept in Credential Manager (credentials.py)."""
    import secrets
    return secrets.token_hex(SALT_BYTES)


def mask(email):
    """`email` as the card shows it: the first letter of the part before the @ and of the domain, the rest hidden, and
    the domain's last label ("s•••@e•••.com") - or None for anything that is not an
    address. Made for display, in the Dashboard's process; never stored or journalled. Pure."""
    if not isinstance(email, str) or email.count("@") != 1:
        return None
    local, domain = email.strip().split("@")
    if not local or not domain or domain.startswith(".") or domain.endswith("."):
        return None
    labels = domain.split(".")
    shown = local[0] + HIDDEN + "@" + labels[0][:1] + HIDDEN
    return shown + ("." + labels[-1] if len(labels) > 1 else "")


def read(paths, *, session=None) -> dict:
    """account/read through a finite session of this capability's own, parsed - {present: None, ...} where Codex could
    not be found or asked. `session` is a test's: a context manager whose value has `call`."""
    try:
        if session is None:
            from . import inuse
            from .protocol import Session
            session = Session(inuse.backend(paths), capability=CAPABILITY)
        with session as opened:
            return parse(opened.call(READ, {}))
    except Exception:
        return parse(None)

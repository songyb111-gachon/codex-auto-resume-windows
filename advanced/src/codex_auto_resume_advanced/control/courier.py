# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The courier's card on the Advanced features page: its bridge commands, the Dashboard's alone and never an MCP tool's.

* advanced-courier - the card read: each channel's switch, whether its address and secret are saved (never what they
  are), how many of its tries were refused today and whether that turned it off, the events picked, Telegram's pairing,
  and the status feed's last reading;
* advanced-courier-save - one channel's address and secret checked (courier/address.py) and kept in Windows Credential
  Manager (credentials.py) - or, for Telegram with `pair`, a pairing begun: a one-time code of six digits is answered
  for the card to show, only its digest is kept, and a courier run with `--pair` waits for it (courier/keep.py);
* advanced-courier-forget - one channel's address and secret taken out of Credential Manager;
* advanced-courier-test - the fixed test notice on one channel, sent now by a courier run, its outcome one word: sent,
  refused, server_error, timed_out, tls, busy, not_saved or no_answer;
* advanced-feed-refresh - a courier run with `--feed` started for one reading now, and the last reading answered.

Saving, testing and pairing are for push_notices on or watched, the feed read for status_feed on; forgetting is always
taken. No answer ever carries an address, a token, a password or the chat kept. This module loads no networking code:
the courier sends, in its own process (courier/launch.py).
"""
from __future__ import annotations

import json
import secrets as random

from ..vocabulary import ArmingState, CourierChannel, OptionKey, Refusal

PUSH = "push_notices"
FEED = "status_feed"
# A test notice's exit code (courier/__main__.EXIT_TEST and the rest) as the card's word.
TEST_WORDS = {0: "sent", 5: "refused", 6: "server_error", 7: "timed_out", 8: "tls", 3: "busy", 4: "not_saved"}
TEST_SECONDS = 30


def _refused(refusal, **more) -> dict:
    return dict({"done": False, "refusal": refusal}, **more)


def _standing(runtime, capability, *, watched=True):
    """None where `capability` is on (or, with `watched`, watched); the refusal otherwise."""
    if runtime.registry.get(capability) is None:
        return Refusal.UNKNOWN_CAPABILITY
    try:
        state = runtime.states(fresh=True).get(capability, ArmingState.OFF)
    except Exception:
        return Refusal.STATE_UNAVAILABLE
    wanted = (ArmingState.ARMED, ArmingState.SHADOW) if watched else (ArmingState.ARMED,)
    return None if state in wanted else Refusal.NOT_ON


def _channel(value):
    return value if isinstance(value, str) and value in tuple(CourierChannel) else None


def _secrets(runtime, secrets):
    if secrets is not None:
        return secrets
    from ..courier.keep import secrets_of
    return secrets_of(runtime.registry)


def view(runtime, *, secrets=None) -> dict:
    """advanced-courier: what the card shows - never a secret."""
    from ..courier import feed, keep, outbox
    from ..engine.push import EVENTS
    if runtime.registry.get(PUSH) is None:
        return _refused(Refusal.UNKNOWN_CAPABILITY)
    secrets = _secrets(runtime, secrets)
    now = runtime.clock()
    try:
        options = runtime.state.options(PUSH)
        rows = []
        for channel in CourierChannel:
            refused = outbox.refusals_today(runtime.state, channel, now)
            on = options.get(OptionKey(str(channel))) == 1
            rows.append({"channel": str(channel), "on": on, "saved": keep.saved(secrets, str(channel)),
                         "refused_today": refused, "tripped": not on and refused >= outbox.TRIPWIRE})
        token = keep.saved(secrets, "telegram") or _has(secrets, "telegram_token")
        row = keep.pairing(runtime.state)
        pairing = bool(row and row.get("code_digest") and (row.get("code_expires_at") or 0) > now)
        reading = feed.read(runtime.state) if runtime.registry.get(FEED) is not None else None
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None, "channels": rows, "events": options.get(OptionKey.PUSH_EVENTS),
            "event_order": [str(event) for event in EVENTS],
            "telegram": {"token_saved": bool(token), "paired": keep.saved(secrets, "telegram"), "pairing": pairing},
            "feed": reading}


def _has(secrets, name) -> bool:
    from ..courier.keep import read
    try:
        return read(secrets, name) is not None
    except Exception:
        return False


def save(runtime, argument, *, secrets=None, start=None) -> dict:
    """advanced-courier-save: one channel's address and secret checked and kept, or Telegram's pairing begun."""
    from ..credentials import SecretError
    from ..courier.address import (AddressRefused, TELEGRAM_TOKEN, checked_smtp, checked_token, checked_url)
    from ..courier import keep
    refusal = _standing(runtime, PUSH)
    if refusal is not None:
        return _refused(refusal)
    channel = _channel(argument.get("channel"))
    if channel is None:
        return _refused(Refusal.INVALID_REQUEST)
    secrets = _secrets(runtime, secrets)
    try:
        if channel == "ntfy":
            secrets.write(PUSH, "ntfy_url", checked_url(argument.get("url")))
        elif channel == "webhook":
            token = argument.get("token")
            url = checked_url(argument.get("url"))
            token = None if token in (None, "") else checked_token(token)
            secrets.write(PUSH, "webhook_url", url)
            if token is None:
                secrets.delete(PUSH, "webhook_token")
            else:
                secrets.write(PUSH, "webhook_token", token)
        elif channel == "telegram" and argument.get("pair") is True:
            return _pair(runtime, secrets, start)
        elif channel == "telegram":
            secrets.write(PUSH, "telegram_token", checked_token(argument.get("token"), shape=TELEGRAM_TOKEN))
            secrets.delete(PUSH, "telegram_chat")         # a new bot is paired afresh
        else:
            blob = checked_smtp({name: argument.get(name) for name in ("host", "port", "user", "password", "from",
                                                                        "to")})
            secrets.write(PUSH, "smtp", json.dumps(blob, separators=(",", ":")))
    except AddressRefused as exc:
        return _refused(Refusal.ADDRESS_REFUSED, why=exc.word)
    except SecretError:
        return _refused(Refusal.SECRET_UNAVAILABLE)
    return {"done": True, "refusal": None, "saved": keep.saved(secrets, channel)}


def _pair(runtime, secrets, start) -> dict:
    """Telegram's pairing begun: the bot's token must be saved; the code answered for the card, its digest kept."""
    from ..courier import keep
    if not _has(secrets, "telegram_token"):
        return _refused(Refusal.NOT_SAVED)
    code = "%06d" % random.randbelow(10 ** 6)
    now = runtime.clock()
    try:
        keep.begin_pairing(runtime.state, code, now)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE)
    if start is None:
        from ..courier.launch import start
    if not start(runtime.paths, "--pair"):
        return _refused(Refusal.COURIER_UNAVAILABLE)
    return {"done": True, "refusal": None, "code": code, "expires_at": now + keep.PAIR_SECONDS}


def forget(runtime, channel, *, secrets=None) -> dict:
    """advanced-courier-forget: one channel's address and secret taken out of Credential Manager."""
    from ..credentials import SecretError
    from ..courier.keep import CHANNEL_SECRETS
    channel = _channel(channel)
    if channel is None or runtime.registry.get(PUSH) is None:
        return _refused(Refusal.INVALID_REQUEST)
    secrets = _secrets(runtime, secrets)
    try:
        for name in CHANNEL_SECRETS[channel]:
            secrets.delete(PUSH, name)
    except SecretError:
        return _refused(Refusal.SECRET_UNAVAILABLE)
    return {"done": True, "refusal": None}


def test(runtime, channel, *, secrets=None, run=None) -> dict:
    """advanced-courier-test: the test notice sent now by a courier run on `channel`, waited for at most TEST_SECONDS."""
    from ..courier import keep
    refusal = _standing(runtime, PUSH)
    if refusal is not None:
        return _refused(refusal)
    channel = _channel(channel)
    if channel is None:
        return _refused(Refusal.INVALID_REQUEST)
    if not keep.saved(_secrets(runtime, secrets), channel):
        return {"done": True, "refusal": None, "outcome": "not_saved"}
    if run is None:
        from ..courier.launch import run
    code = run(runtime.paths, "--test", channel, timeout=TEST_SECONDS)
    return {"done": True, "refusal": None, "outcome": TEST_WORDS.get(code, "no_answer")}


def feed_refresh(runtime, *, start=None) -> dict:
    """advanced-feed-refresh: one reading started now, and the last one answered."""
    from ..courier import feed
    refusal = _standing(runtime, FEED, watched=False)
    if refusal is not None:
        return _refused(refusal)
    if start is None:
        from ..courier.launch import start
    started = start(runtime.paths, "--feed")
    try:
        reading = feed.read(runtime.state)
    except Exception:
        reading = None
    return {"done": True, "refusal": None, "started": bool(started), "feed": reading}

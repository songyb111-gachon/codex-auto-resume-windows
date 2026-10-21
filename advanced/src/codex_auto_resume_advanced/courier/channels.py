# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The four channels a notice is pushed on, what a push says, and Telegram's one-time pairing.

What a push says (`lines`), in the person's language, at most three short lines: what happened - one of the closed
events (CourierEvent) in words - then the record's place in Pending as `task N`, core's category word and the local
time, then the edition. Never a title, a project, a path, an id, an error's text, an account or a word of a
conversation: nothing that could be one reaches this module, which is handed an outbox row of closed words and numbers.

* ntfy: the lines POSTed as plain text to the topic's address; `Title` the product's name and `Tags` the event's closed
  word, both fixed ASCII.
* webhook: `{"event", "category", "task", "at", "edition"}` POSTed as JSON, with `Authorization: Bearer <token>` where
  the person gave one.
* Telegram: the lines sent by `https://api.telegram.org/bot<token>/sendMessage` to the chat the pairing kept. The token
  is only ever in that path - never in a log, the journal or an error (http.Failed keeps a status class alone).
* e-mail: one plain-text message, over SMTP on 465 (TLS from the start) or 587 (STARTTLS), both verifying the server,
  after signing in. Every header is built from closed words and addresses checked to carry no line break (address.py),
  so none can be injected.

Every address and secret comes from Windows Credential Manager through credentials.py, under push_notices' own
names (keep.py); none is kept anywhere else. `smtp` and `opener` are the seams a test fills: no test
reaches a real service.

Telegram's pairing (`pair`): the Dashboard shows a one-time code of six digits, keeping only its SHA-256 digest and
when it expires in the `remote` table (keep.begin_pairing); a courier run with `--pair` reads the bot's new messages for
up to PAIR_SECONDS and keeps the chat whose message is that code. Five other six-digit messages end the pairing.
"""
from __future__ import annotations

import json
import smtplib
import socket
import ssl
import time
from email.message import EmailMessage

from . import http, outbox
from .address import (AddressRefused, TELEGRAM_CHAT, TELEGRAM_TOKEN, checked_smtp, checked_token,
                      checked_url)
from .keep import (BAD_CODES, CAPABILITY, CODE, PAIR_SECONDS, NotSaved, digest, pairing, read as _read,  # noqa: F401
                   saved, secrets_of)

TELEGRAM_API = "https://api.telegram.org/bot"
PRODUCT = "Codex Auto Resume"
EDITION = "advanced"
PAIR_POLL = 25                    # seconds Telegram is asked to hold one read open
ON = 1                            # a channel's switch (registry SWITCH: 1 on, 2 off)
OFF = 2


# ------------------------------------------------------------------------------ what a push says
def lines(event, category=None, task=None, at=None, locale=None) -> list:
    """What a push of `event` says, at most three lines, in `locale` (the process's own by default): the event in
    words; `task N`, the category word and the local time; the edition."""
    from ..statement import CATALOGS
    event = str(event)
    said = CATALOGS.text("push.event." + event, locale) or event
    detail = [part for part in (task if isinstance(task, str) else None,
                                category if isinstance(category, str) else None) if part]
    if isinstance(at, (int, float)) and not isinstance(at, bool):
        detail.append(time.strftime("%H:%M", time.localtime(at)))
    found = [said]
    if detail:
        found.append(" · ".join(detail))
    found.append(CATALOGS.text("push.edition", locale) or "%s (%s)" % (PRODUCT, EDITION))
    return found[:3]


def webhook_body(event, category=None, task=None, at=None) -> dict:
    """The webhook's JSON: closed keys, closed words and numbers."""
    return {"event": str(event), "category": category if isinstance(category, str) else None,
            "task": task if isinstance(task, str) else None,
            "at": int(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else None, "edition": EDITION}


# ------------------------------------------------------------------------------ sending
def send(channel, row, secrets, *, opener=None, smtp=None, locale=None) -> str:
    """Push the outbox `row` (or a test's) on `channel`: "2xx", or http.Failed, NotSaved or AddressRefused."""
    event, category, task, at = row["event"], row.get("category"), row.get("alias"), row.get("at")
    text = "\n".join(lines(event, category, task, at, locale))
    if channel == "ntfy":
        url = _read(secrets, "ntfy_url")
        if url is None:
            raise NotSaved()
        return http.post(checked_url(url), text.encode("utf-8"),
                         {"Title": PRODUCT, "Tags": str(event), "Content-Type": "text/plain; charset=utf-8"},
                         opener=opener)
    if channel == "webhook":
        url, token = _read(secrets, "webhook_url"), _read(secrets, "webhook_token")
        if url is None:
            raise NotSaved()
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + checked_token(token)
        body = json.dumps(webhook_body(event, category, task, at), separators=(",", ":")).encode("utf-8")
        return http.post(checked_url(url), body, headers, opener=opener)
    if channel == "telegram":
        token, chat = _read(secrets, "telegram_token"), _read(secrets, "telegram_chat")
        if token is None or chat is None:
            raise NotSaved()
        checked_token(token, shape=TELEGRAM_TOKEN)
        checked_token(chat, shape=TELEGRAM_CHAT)
        body = json.dumps({"chat_id": int(chat), "text": text, "disable_web_page_preview": True},
                          ensure_ascii=False).encode("utf-8")
        return http.post(TELEGRAM_API + token + "/sendMessage", body, {"Content-Type": "application/json"},
                         opener=opener)
    if channel == "email":
        blob = _read(secrets, "smtp")
        if blob is None:
            raise NotSaved()
        try:
            settings = checked_smtp(json.loads(blob))
        except ValueError:
            raise AddressRefused("smtp") from None
        return mail(settings, event, text, smtp=smtp)
    raise ValueError("channel")


def mail(settings, event, text, *, smtp=None) -> str:
    """One plain-text message over SMTP as `settings` say (address.checked_smtp's): "2xx", or http.Failed - "4xx" for a
    refusal (a 5xx reply, the sign-in refused), "5xx" for the server's own trouble (a 4xx reply), "tls" for a server
    that would not verify or offer STARTTLS, "timeout" for no answer."""
    message = EmailMessage()
    message["Subject"] = "%s: %s" % (PRODUCT, str(event))
    message["From"] = settings["from"]
    message["To"] = settings["to"]
    message.set_content(text)
    factory = smtp or smtplib
    context = http.context()
    server = None
    try:
        if settings["port"] == 465:
            server = factory.SMTP_SSL(settings["host"], 465, timeout=http.TIMEOUT, context=context)
        else:
            server = factory.SMTP(settings["host"], 587, timeout=http.TIMEOUT)
            server.starttls(context=context)
        server.login(settings["user"], settings["password"])
        server.send_message(message)
    except smtplib.SMTPNotSupportedError:
        raise http.Failed("tls") from None
    except smtplib.SMTPAuthenticationError:
        raise http.Failed("4xx", 535) from None
    except smtplib.SMTPResponseException as exc:
        code = exc.smtp_code if isinstance(exc.smtp_code, int) else 0
        raise http.Failed("4xx" if code >= 500 else "5xx", code) from None
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused):
        raise http.Failed("4xx") from None
    except (ssl.SSLError, ssl.CertificateError):
        raise http.Failed("tls") from None
    except (smtplib.SMTPException, socket.timeout, TimeoutError, OSError):
        raise http.Failed("timeout") from None
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass
    return "2xx"


def test(runtime, channel, secrets, *, opener=None, smtp=None) -> int:
    """The Dashboard's Send a test: the fixed test notice on `channel`, now. Its outcome as the courier's exit code."""
    from .__main__ import EXIT_REFUSED, EXIT_TEST
    if not saved(secrets, channel):
        return EXIT_REFUSED
    try:
        word = send(channel, {"event": "test", "at": runtime.clock()}, secrets, opener=opener, smtp=smtp)
    except http.Failed as exc:
        word = exc.word
    except (NotSaved, AddressRefused, ValueError):
        return EXIT_REFUSED
    return EXIT_TEST.get(word, EXIT_REFUSED)


def drain(runtime, secrets, *, opener=None, smtp=None, now=None) -> int:
    """One pass over the outbox: rows too old dropped; each row due sent on its channel - dropped where its channel is
    switched off or not saved; on a failure, tried again later or dropped at its last try; and a channel whose refusals
    today reach outbox.TRIPWIRE switched off. How many went."""
    from ..vocabulary import Actor, OptionKey
    state = runtime.state
    now = runtime.clock() if now is None else now
    for channel in outbox.expire(state, now):
        state.counted(CAPABILITY, "dropped_%s" % channel)
    sent = 0
    for row in outbox.due(state, now):
        channel = row["channel"]
        options = state.options(CAPABILITY)
        if options.get(OptionKey(channel)) != ON:
            _drop(state, row["item_id"], channel, now)
            continue
        try:
            send(channel, row, secrets, opener=opener, smtp=smtp)
        except (NotSaved, AddressRefused, ValueError):
            _drop(state, row["item_id"], channel, now)
            continue
        except http.Failed as exc:
            word = exc.word if exc.word in outbox.FAILED else "timeout"
            state.counted(CAPABILITY, "refused_%s_%s" % (channel, word))
            if outbox.settle(state, row["item_id"], False, now) == "dropped":
                state.counted(CAPABILITY, "dropped_%s" % channel)
            if word in outbox.REFUSING and outbox.refusals_today(state, channel, now) >= outbox.TRIPWIRE:
                try:
                    state.set_option(CAPABILITY, OptionKey(channel), OFF, generation=state.meta()["generation"],
                                     actor=Actor.TRIPWIRE)
                    state.counted(CAPABILITY, "off_%s" % channel)
                except Exception:
                    pass
            continue
        outbox.settle(state, row["item_id"], True, now)
        state.counted(CAPABILITY, "sent_%s" % channel)
        sent += 1
    return sent


def _drop(state, item_id, channel, now) -> None:
    with state._transaction() as connection:
        connection.execute("UPDATE outbox SET state = 'dropped', finished_at = ? WHERE item_id = ? "
                           "AND state = 'waiting'", (float(now), item_id))
    state.counted(CAPABILITY, "dropped_%s" % channel)


# ------------------------------------------------------------------------------ Telegram's pairing
def _end_pairing(state, *, offset=None, paired_at=None, bad=None) -> None:
    with state._transaction() as connection:
        connection.execute("UPDATE remote SET code_digest = NULL, code_expires_at = NULL, paired_at = ?, "
                           "update_offset = coalesce(?, update_offset), bad_codes = coalesce(?, bad_codes) "
                           "WHERE channel = 'telegram'", (paired_at, offset, bad))


def _updates(reply) -> list:
    try:
        found = json.loads(reply.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        return []
    result = found.get("result") if isinstance(found, dict) and found.get("ok") is True else None
    return [entry for entry in result if isinstance(entry, dict)] if isinstance(result, list) else []


def pair(runtime, secrets, *, opener=None, clock=None, sleep=None) -> int:
    """Read the bot's messages until the one-time code arrives, it expires, PAIR_SECONDS pass or BAD_CODES other codes
    came: the chat that sent it kept as push_notices' telegram_chat. The courier's exit code."""
    from .__main__ import EXIT_DONE, EXIT_NOT_PAIRED, EXIT_REFUSED
    clock = clock or time.time
    sleep = sleep or time.sleep
    state = runtime.state
    try:
        token = _read(secrets, "telegram_token")
        checked_token(token or "", shape=TELEGRAM_TOKEN)
    except (AddressRefused, Exception):
        return EXIT_REFUSED
    row = pairing(state)
    start = clock()
    if row is None or row["code_digest"] is None or not isinstance(row["code_expires_at"], float) \
            or row["code_expires_at"] <= start:
        return EXIT_REFUSED
    deadline = min(row["code_expires_at"], start + PAIR_SECONDS)
    offset, bad = row["update_offset"] or 0, row["bad_codes"] or 0
    while clock() < deadline:
        wait = int(max(1, min(PAIR_POLL, deadline - clock())))
        url = "%s%s/getUpdates?timeout=%d&offset=%d" % (TELEGRAM_API, token, wait, offset)
        try:
            reply = http.get(url, timeout=wait + http.TIMEOUT, opener=opener)
        except http.Failed as exc:
            if exc.word in outbox.REFUSING:
                _end_pairing(state, offset=offset, bad=bad)
                return EXIT_REFUSED
            sleep(2)
            continue
        for update in _updates(reply):
            number = update.get("update_id")
            if type(number) is int and number >= offset:
                offset = number + 1
            message = update.get("message") if isinstance(update.get("message"), dict) else {}
            text = message.get("text").strip() if isinstance(message.get("text"), str) else ""
            chat = (message.get("chat") or {}).get("id") if isinstance(message.get("chat"), dict) else None
            if not CODE.match(text) or type(chat) is not int:
                continue
            if digest(text) == row["code_digest"]:
                secrets.write(CAPABILITY, "telegram_chat", str(chat))
                _end_pairing(state, offset=offset, paired_at=float(clock()), bad=0)
                return EXIT_DONE
            bad += 1
            if bad >= BAD_CODES:
                _end_pairing(state, offset=offset, bad=BAD_CODES)
                return EXIT_NOT_PAIRED
        with state._transaction() as connection:
            connection.execute("UPDATE remote SET update_offset = ?, bad_codes = ? WHERE channel = 'telegram'",
                               (offset, bad))
    _end_pairing(state, offset=offset, bad=bad)
    return EXIT_NOT_PAIRED

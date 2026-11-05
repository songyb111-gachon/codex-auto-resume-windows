# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Remote control over Telegram (telegram_remote, telegram_continue - v0.6.22, plans/v0619-design/D-remote.md): the
resident courier's long poll of the bot push_notices keeps (channels.py), obeying the one chat its pairing kept.

`run` asks Telegram for the bot's new messages (getUpdates, held open up to POLL seconds, the offset kept in the
`remote` table) for as long as telegram_remote stands on, and waits while a pairing is under way - the pairing reads the
same bot (channels.pair) and Telegram answers only one reader at a time. A message from any chat but the paired one is
ignored without an answer, and so is one older than FRESH seconds: a /pause sent while this PC was off is not obeyed
hours later. The paired chat's text is read as one of COMMANDS and nothing else:

    /status            what the watcher is doing: running or not, recovery on or paused, how many wait
    /list              the waiting recoveries as `task N`, their public state and next check (control/remote.py)
    /cancel task N     one of them cancelled - against the list last answered, or "list again"
    /pause             recovery paused
    /continue task N   one held for the person let go on - telegram_continue only (core's release_hold)
    /recovery-on       the pause lifted - telegram_continue only

A command addressed to a bot by name (`/pause@name`, as Telegram writes them in a group) is obeyed only when the name is
this bot's own, asked of Telegram once (getMe); for another bot - or while this one's name cannot be read - it is passed
over without an answer. Anything else is answered with the list of commands it may send. No command sends to Codex, chats, changes a setting,
turns a feature on or off, sends now or gives attempts back (a test holds COMMANDS to the design's table); no text of a
message reaches a conversation. Answers are in the person's language, closed words, numbers and `task N` alone, sent to
the paired chat by sendMessage - the bot's token only ever in the request's path, never in a log or the journal.

The offset is kept before a message is acted on: a command is carried out at most once, and one lost to a crash is one the
person sends again. A read asks for at most UPDATES messages, so what strangers send the bot can never make a reply
longer than http.MAX_REPLY, which could not be parsed and would stop the offset moving. Recovery paused changes nothing
here: asking how things stand is what a paused PC is asked; it is the one way this feature sends while paused, and only
in answer to the paired chat.

`opener` is the seam a test fills; no test reaches Telegram.
"""
from __future__ import annotations

import json
import time

from . import http
from .address import TELEGRAM_CHAT, TELEGRAM_TOKEN
from .channels import TELEGRAM_API
from ..vocabulary import ArmingState

TELEGRAM = "telegram_remote"
TELEGRAM_CONTINUE = "telegram_continue"
POLL = 50                          # seconds Telegram is asked to hold one read open
IDLE = 30                          # seconds before asking again with no bot or chat kept, or a pairing under way
AFTER_REFUSAL = 60                 # ... after Telegram refused (a token it does not know)
AFTER_FAILURE = 10                 # ... after no answer, or another reader of the same bot (409: a pairing starting)
CONFLICT = 409
FRESH = 300                        # seconds a message may be old and still be obeyed
UPDATES = 2                        # messages one read may bring: each at most 4,096 characters
IGNORED_EVERY = 3600               # seconds between two journal lines for what other chats sent: one an hour at most
MAX_TEXT = 64                      # characters of a message read; a longer one is no command
LISTED = 20                        # rows of one /list answer: a Telegram message has a limit, and task N stays right
# Every command, with the capability that allows it. A test holds this table to the design's.
COMMANDS = {"/status": TELEGRAM, "/list": TELEGRAM, "/cancel": TELEGRAM, "/pause": TELEGRAM,
            "/continue": TELEGRAM_CONTINUE, "/recovery-on": TELEGRAM_CONTINUE}
TAKES_TASK = ("/cancel", "/continue")
CODES = ("status", "listed", "cancelled", "paused", "list_again", "ignored")
CONTINUE_CODES = ("continued", "pause_lifted")


def parse(text):
    """(command, `task N` or None) of a message's text, or (None, None) for anything that is not one of COMMANDS: the
    command word (a `@bot` after it dropped), then for /cancel and /continue `task N` or `N`, then nothing more."""
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        return None, None
    words = text.strip().split()
    if not words:
        return None, None
    command = words[0].split("@", 1)[0].lower()
    if command not in COMMANDS:
        return None, None
    rest = words[1:]
    if command not in TAKES_TASK:
        return (command, None) if not rest else (None, None)
    if len(rest) == 2 and rest[0].lower() == "task":
        rest = rest[1:]
    if len(rest) == 1 and rest[0].isascii() and rest[0].isdigit() and rest[0][0] != "0" and len(rest[0]) <= 4:
        return command, "task %s" % rest[0]
    return None, None


class Poller:
    """One bot read at a time, and what the paired chat last listed. `secrets`, `opener`, `layer` and `clock` are the
    seams a test fills."""

    def __init__(self, runtime, *, secrets=None, opener=None, layer=None, clock=None, locale=None):
        from ..control import remote
        self.runtime = runtime
        self._remote = remote
        self._secrets = secrets
        self._opener = opener
        self._layer = layer
        self.clock = clock or time.time
        self.locale = locale
        self.listed = None               # the snapshot of the list last answered to the paired chat - once it was sent
        self.offered = None              # the snapshot of a list being answered, until its answer is sent
        self.ignored_at = None           # when what other chats sent was last journalled
        self.name = None                 # this bot's own name, lower case, once getMe answered it

    @property
    def secrets(self):
        if self._secrets is None:
            from .keep import secrets_of
            self._secrets = secrets_of(self.runtime.registry)
        return self._secrets

    @property
    def layer(self):
        if self._layer is None:
            self._layer = self._remote.control(self.runtime.paths)
        return self._layer

    def _kept(self):
        """(token, chat) push_notices' pairing kept, each checked - or None."""
        from .keep import read
        try:
            token, chat = read(self.secrets, "telegram_token"), read(self.secrets, "telegram_chat")
        except Exception:
            return None
        if not token or not chat or not TELEGRAM_TOKEN.match(token) or not TELEGRAM_CHAT.match(chat):
            return None
        return token, int(chat)

    def _pairing(self) -> bool:
        from .keep import pairing
        try:
            row = pairing(self.runtime.state) or {}
        except Exception:
            return False
        return bool(row.get("code_digest") and (row.get("code_expires_at") or 0) > self.clock())

    def _offset(self) -> int:
        from .keep import pairing
        try:
            found = (pairing(self.runtime.state) or {}).get("update_offset")
        except Exception:
            found = None
        return found if type(found) is int and found >= 0 else 0

    def _keep_offset(self, offset) -> None:
        with self.runtime.state._transaction() as connection:
            connection.execute("INSERT INTO remote (channel, paired_at, bad_codes, update_offset) VALUES "
                               "('telegram', NULL, 0, ?) ON CONFLICT(channel) DO UPDATE SET "
                               "update_offset = excluded.update_offset", (offset,))

    def once(self, stop=None) -> int:
        """One read of the bot and every message it brought, answered; the seconds to wait before the next."""
        kept = self._kept()
        if kept is None or self._pairing():
            return IDLE
        token, chat = kept
        offset = self._offset()
        url = "%s%s/getUpdates?timeout=%d&offset=%d&limit=%d" % (TELEGRAM_API, token, POLL, offset, UPDATES)
        try:
            reply = http.get(url, timeout=POLL + http.TIMEOUT, opener=self._opener)
        except http.Failed as exc:
            if exc.status == CONFLICT:
                return AFTER_FAILURE
            return AFTER_REFUSAL if exc.word in ("4xx", "tls") else AFTER_FAILURE
        if stop is not None and stop.is_set():
            return 0                     # turned off while the read was held open: nothing it brought is obeyed
        found = updates(reply)
        for update in found:
            number = update.get("update_id")
            if type(number) is int and number >= offset:
                offset = number + 1
        self._keep_offset(offset)
        ignored = False
        now = self.clock()
        for update in found:
            message = update.get("message") if isinstance(update.get("message"), dict) else {}
            sender = message.get("chat").get("id") if isinstance(message.get("chat"), dict) else None
            sent_at = message.get("date")
            if (type(sender) is not int or sender != chat or type(sent_at) is not int
                    or not 0 <= now - sent_at <= FRESH):
                ignored = True
                continue
            if self.elsewhere(token, message.get("text")):
                continue                 # a command for another bot, in a group: not this one's to answer
            self.offered = None
            said = self.answer(message.get("text"))
            try:
                self.send(token, chat, said)
            except (http.Failed, ValueError):
                continue                 # a list the person never saw is never what a later `task N` means
            if self.offered is not None:
                self.listed = self.offered
        if ignored and (self.ignored_at is None or not 0 <= now - self.ignored_at < IGNORED_EVERY):
            # One line an hour, however much strangers send: a flood must not wear the journal every capability shares.
            self.ignored_at = now
            self.runtime.state.counted(TELEGRAM, "ignored")
        return 0

    def own_name(self, token):
        """This bot's name (getMe), lower case - asked once and kept - or None where it cannot be read."""
        if self.name is None:
            try:
                found = json.loads(http.get("%s%s/getMe" % (TELEGRAM_API, token), opener=self._opener).decode("utf-8"))
                name = found.get("result", {}).get("username") if found.get("ok") is True else None
            except (http.Failed, ValueError, UnicodeDecodeError, AttributeError):
                return None
            self.name = name.lower() if isinstance(name, str) and name else None
        return self.name

    def elsewhere(self, token, text) -> bool:
        """Whether `text` is a command addressed by name to another bot (or to a name this one cannot confirm)."""
        if not isinstance(text, str) or not text.strip().startswith("/"):
            return False
        first = text.strip().split()[0]
        if "@" not in first:
            return False
        return first.split("@", 1)[1].lower() != self.own_name(token)

    def send(self, token, chat, text) -> str:
        body = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True},
                          ensure_ascii=False).encode("utf-8")
        return http.post("%s%s/sendMessage" % (TELEGRAM_API, token), body, {"Content-Type": "application/json"},
                         opener=self._opener)

    # ---------------------------------------------------------------------------- the commands
    def word(self, key, fallback, **fields) -> str:
        from ..statement import CATALOGS
        return CATALOGS.text(key, self.locale, **fields) or fallback.format(**fields)

    def allowed(self, capability) -> bool:
        try:
            return self.runtime.states(fresh=True).get(capability) == ArmingState.ARMED
        except Exception:
            return False

    def help(self) -> str:
        names = [name for name, capability in COMMANDS.items() if self.allowed(capability)]
        return self.word("page.remote.answer.help", "Commands: {commands}", commands=", ".join(names))

    def answer(self, text) -> str:
        """What the paired chat is answered for `text` - and, for an allowed command, it carried out."""
        command, alias = parse(text)
        if command is None:
            return self.help()
        capability = COMMANDS[command]
        if not self.allowed(TELEGRAM) or not self.allowed(capability):
            return self.word("page.remote.answer.not_allowed", "That command is not turned on.")
        try:
            if command == "/status":
                self.runtime.state.counted(TELEGRAM, "status")
                return self.status()
            if command == "/list":
                self.runtime.state.counted(TELEGRAM, "listed")
                return self.list()
            if command == "/pause":
                self._remote.pause(self.layer)
                self.runtime.state.counted(TELEGRAM, "paused")
                return self.word("page.remote.answer.paused", "Recovery is paused.")
            if command == "/recovery-on":
                self._remote.lift_pause(self.layer)
                self.runtime.state.counted(TELEGRAM_CONTINUE, "pause_lifted")
                return self.word("page.remote.answer.pause_lifted", "Recovery is on again.")
            return self.by_task(command, alias)
        except self._remote.Stale:
            self.runtime.state.counted(TELEGRAM, "list_again")
            return self.word("page.remote.answer.list_again", "The list has changed. Send /list again.")
        except Exception:
            return self.word("page.remote.answer.refused", "That could not be done.")

    def by_task(self, command, alias) -> str:
        number = alias.split(" ", 1)[1]
        if command == "/cancel":
            self._remote.cancel(self.layer, alias, self.listed)
            self.runtime.state.counted(TELEGRAM, "cancelled")
            return self.word("page.remote.answer.cancelled", "task {n} is cancelled.", n=number)
        self._remote.release(self.layer, alias, self.listed)
        self.runtime.state.counted(TELEGRAM_CONTINUE, "continued")
        return self.word("page.remote.answer.continued", "task {n} goes on. Nothing is sent until every check passes.",
                         n=number)

    def status(self) -> str:
        document = self._remote.status_document(self.layer, self.clock())
        return self.word("page.remote.answer.status", "Watcher {watcher}, recovery {recovery}, {n} waiting.",
                         watcher=self.word("page.remote.word." + document["watcher"], document["watcher"]),
                         recovery=self.word("page.remote.word." + document["recovery"], document["recovery"]),
                         n=document["pending"])

    def list(self) -> str:
        found = self._remote.pending(self.layer)
        self.offered = found["snapshot"]
        if not found["pending"]:
            return self.word("page.remote.answer.list_none", "Nothing waits.")
        lines = []
        for row in found["pending"][:LISTED]:
            at = row["next_check_at"]
            lines.append(self.word("page.remote.answer.list_item", "{task}: {state}, next check {at}",
                                   task=row["task"], state=self._state_word(row["state"]),
                                   at=time.strftime("%H:%M", time.localtime(at)) if at else "-"))
        return "\n".join(lines)

    def _state_word(self, code) -> str:
        """A public state code in the person's language, core's word for it, else the code: closed either way."""
        from codex_auto_resume import l10n
        try:
            said = l10n.text("code." + code, self.locale or l10n.current())
        except Exception:
            return code
        return said if isinstance(said, str) and said and said != "code." + code else code


def updates(reply) -> list:
    """The updates of a getUpdates reply: a list of dicts, or empty for anything else."""
    try:
        found = json.loads(reply.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        return []
    result = found.get("result") if isinstance(found, dict) and found.get("ok") is True else None
    return [entry for entry in result if isinstance(entry, dict)] if isinstance(result, list) else []


def run(runtime, stop, **seams) -> None:
    """Read the bot until `stop` is set."""
    poller = Poller(runtime, **seams)
    while not stop.is_set():
        try:
            wait = poller.once(stop)
        except Exception:
            wait = AFTER_FAILURE
        if wait:
            stop.wait(wait)

# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Stop hook's handler: what runs when Codex ends a turn, while "Continue inside the turn" is on.

Codex starts gui/HookLauncher.cs, which starts this with the installation's own interpreter and hands it Codex's one
JSON object (plans/v0619-design/D-stop-hook.md). It answers within BUDGET_SECONDS or passes - exits 0 having written
nothing, which lets the turn end as it would have - and passes on every doubt.

What it reads of the input: the keys format.allowed_keys names, and no other key's value, ever - the last assistant
message, the transcript's path and the prompt are dropped as the JSON is parsed (B9). Input over MAX_INPUT bytes, or
not one JSON object, passes.

What it decides, for a Stop of the conversation the input names:
* the capability is on (the advanced state, read) and automatic recovery is on for that conversation (core's store);
* the conversation's latest turn in Codex's history - read-only, core's own reader (codex.LocalSource, B1) - failed,
  is the turn the input names, and core's own detection takes it (codex.detect: a kind core recovers, its error
  classified by core and its words dropped), under the interruption id core derives (domain/ids.py);
* its kind is one a hook can wait for: a transient one whose first wait, by the person's own retry timing, is
  FIRST_WAIT_MOST seconds or less (ALLOWED) - never a usage limit, which waits hours and stays the watcher's;
* the shared claim (engine/hookclaims.claim) grants it: once a turn, never where the watcher took the record first,
  within the ceilings and core's own caps on one conversation.
Then, and only then, it prints the block, whose reason is the standard continuation in the person's language with the
record's marker after it - the words core would have sent, and the marker core finds it by.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time

from codex_auto_resume.domain import ids

from .format import FORMAT, allowed_keys, answer

CAPABILITY = "stop_hook_continuation"
MAX_INPUT = 1024 * 1024              # bytes of input read at most; more passes
BUDGET_SECONDS = 2.0                 # an answer within this, or the turn ends as it would have
CLAIM_MARGIN_SECONDS = 0.6           # no claim begun with less of the budget left than this
COMMIT_GRACE_SECONDS = 3.0           # a claim begun is let finish, and its answer written, within this
# The kinds a hook may continue: core's transient ones whose first step waits a minute at most - a dropped
# connection, a timeout, a server error, an interrupted stream. A rate limit waits a minute at least, and Codex has
# retried it already; a usage limit waits hours. Each is held, too, to the person's retry timing (FIRST_WAIT_MOST).
ALLOWED = frozenset({"network_transient", "timeout", "server_5xx", "stream_interrupted"})
FIRST_WAIT_MOST = 60


def _keep_allowed(pairs):
    """json's object hook: each object as only the allowed keys of it - the rest dropped as it is parsed."""
    keep = allowed_keys()
    return {key: value for key, value in pairs if key in keep}


def pick(document) -> dict | None:
    """The allowed keys of `document`, read by name and no other: None for anything that is not one object. Never
    iterates, never asks for a value it does not keep (advanced/tests/test_advanced_hook_input.py)."""
    if not isinstance(document, dict):
        return None
    return {key: document[key] for key in allowed_keys() if key in document}


def read_input(stream) -> dict | None:
    """The one JSON object on `stream`, as `pick` keeps it, or None: over MAX_INPUT bytes, not UTF-8, not JSON, not
    an object."""
    try:
        data = stream.read(MAX_INPUT + 1)
    except (OSError, ValueError):
        return None
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_INPUT:
        return None
    try:
        document = json.loads(bytes(data).decode("utf-8"), object_pairs_hook=_keep_allowed)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    return pick(document)


def stop_of(picked) -> tuple | None:
    """(thread id, turn id or None) for a Stop the handler may look at, or None: another event, a stop that follows a
    hook's own block, or a conversation not named by its id."""
    if not isinstance(picked, dict):
        return None
    if picked.get(FORMAT.event_key) != FORMAT.event or picked.get(FORMAT.active_key) is True:
        return None
    thread, turn = picked.get(FORMAT.thread_key), picked.get(FORMAT.turn_key)
    if not ids.is_uuid(thread) or not (turn is None or ids.is_uuid(turn)):
        return None
    return thread, turn


class Hands:
    """What the decision reads and the one write it makes, each replaceable by a test: whether the capability is on,
    the person's settings, Codex's latest turn of a conversation, and the shared claim. Production wires `live`."""
    def __init__(self, *, armed, settings, latest, claim, clock=time.time):
        self.armed = armed
        self.settings = settings
        self.latest = latest
        self.claim = claim
        self.clock = clock

    @classmethod
    def live(cls, paths):
        from codex_auto_resume import config

        def armed():
            from ..state import AdvancedState
            from ..arming import Arming
            from ..vocabulary import ArmingState
            state = AdvancedState(paths)
            try:
                return Arming(state).current().get(CAPABILITY) == ArmingState.ARMED
            finally:
                state.close()

        def latest(thread):
            from codex_auto_resume.codex import LocalSource
            from codex_auto_resume.codex.chains import memory as chain_memory
            return LocalSource(config.codex_home(), chains=chain_memory(paths.split_chains_file)).latest(thread)

        def claim(failure, turn_key, now):
            from ..engine.hookclaims import claim as shared
            return shared(paths, failure, turn_key, now)

        return cls(armed=armed, settings=lambda: config.load_settings(paths), latest=latest, claim=claim)


def turn_key(turn_id) -> str:
    """The digest the claim keeps a turn under: never the turn's id itself."""
    import hashlib
    return hashlib.sha256(("turn:%s" % turn_id).encode("ascii")).hexdigest()


def continues(failure, values) -> bool:
    """Whether `failure` (core's detection of a latest turn) is one a hook may continue under the settings `values`."""
    from codex_auto_resume import ladder, settings
    category = failure.get("category")
    if category not in ALLOWED or not settings.category_enabled(values, category):
        return False
    try:
        return ladder.wait_before(values, 1, category) <= FIRST_WAIT_MOST
    except Exception:
        return False


def reason_for(failure, values) -> str:
    """The block's reason: the standard continuation for the failure, in the person's language and style, and the
    record's marker after it, as core ends every continuation it sends with one (engine/dispatch.py)."""
    from codex_auto_resume import continuation
    row = {"thread_id": failure["thread_id"], "category": failure["category"], "recovery_attempts": 0}
    text = continuation.for_settings(failure["category"], values, row=row)
    return text + "\n\n" + ids.short_marker(failure["interruption_id"])


def decide(picked, hands, *, started=None, claiming=None) -> str | None:
    """The block's reason, or None to pass. `started` is when the handler began (the budget runs from it), and
    `claiming` an event set the moment a claim begins - past it, the answer is let finish (`main`)."""
    from codex_auto_resume.codex import detect
    from ..vocabulary import HookOutcome
    started = hands.clock() if started is None else started
    stop = stop_of(picked)
    if stop is None or not hands.armed():
        return None
    thread, turn = stop
    values = hands.settings()
    failure = detect(hands.latest(thread))
    if failure is None or failure.get("thread_id") != thread or (turn is not None and failure.get("turn_id") != turn):
        return None
    if not continues(failure, values):
        return None
    reason = reason_for(failure, values)
    now = hands.clock()
    if now - started > BUDGET_SECONDS - CLAIM_MARGIN_SECONDS:
        return None
    if claiming is not None:
        claiming.set()
    outcome = hands.claim(failure, turn_key(failure["turn_id"]), now)
    return reason if outcome == HookOutcome.BLOCKED else None


def main(argv=None, *, stdin=None, stdout=None, hands=None) -> int:
    """The handler, as the launcher runs it: `--home <installation home>`. Always 0; the block on standard output only
    where `decide` granted one. Past the budget with no claim begun it passes at once, whatever is still being read."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--home")
    try:
        arguments, _ = parser.parse_known_args(argv)
    except SystemExit:
        return 0
    started = time.time()
    stdin = stdin if stdin is not None else getattr(sys.stdin, "buffer", sys.stdin)
    stdout = stdout if stdout is not None else getattr(sys.stdout, "buffer", sys.stdout)
    done, claiming, found = threading.Event(), threading.Event(), {}

    def work():
        try:
            picked = read_input(stdin)
            if picked is None:
                return
            used = hands
            if used is None:
                from codex_auto_resume import config
                if not arguments.home:
                    return
                used = Hands.live(config.Paths(arguments.home))
            found["reason"] = decide(picked, used, started=started, claiming=claiming)
        except Exception:
            found.pop("reason", None)
        finally:
            done.set()

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    if not done.wait(BUDGET_SECONDS) and (not claiming.is_set() or not done.wait(COMMIT_GRACE_SECONDS)):
        return 0
    reason = found.get("reason")
    if isinstance(reason, str) and reason:
        try:
            stdout.write(json.dumps(answer(reason), ensure_ascii=False).encode("utf-8"))
            stdout.flush()
        except (OSError, ValueError):
            return 0
    return 0

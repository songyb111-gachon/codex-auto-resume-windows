# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Codex restart a person agreed to after Codex's own sign-in (account_switch, v0.6.20 final).

Measured on codex-cli 0.166 (2026-11-01, plans/measure-20261101b-result.md): a `codex logout` made outside the app
reaches the running app, but the `codex login` after it does not - the app's long-lived app server never reads the
sign-in again; Ctrl+R and closing the window (the app keeps running in the background) do not help; only a full restart
of the app - its main process ended, then started again - brings it up signed in as the new account. So the card's
button ends with a question, and this is what Restart does.

`busy` is when it may: never while a turn runs in any conversation or anything is queued in Codex - core's own
judgement, the power action's (LocalSource.activity read with the boot time the watcher's heartbeat records, then
poweraction.judge_activity: one way to that answer, so a turn or an item left from before Windows started holds neither)
- nor while a recovery of core's waits or runs (core's store: a record not ended, unless a person's or a change of
account's hold keeps it waiting for them). A reading that fails, or Codex's history behind its files, is busy too.
`restart` then:

1. finds the Codex app's main process as core finds it (codex/pairing: the package's ChatGPT.exe whose parent is none
   of its own) - none running is NOT_RUNNING, nothing to restart; several, FAILED;
2. asks Windows to close it (win/appclose.ask_close: the Restart Manager's request, not forced) and waits END_SECONDS
   for it to be gone; only if it is still there, ends that process (win/appclose.end_process: the same id and creation
   time) and waits KILL_SECONDS - neither ending it is NOT_ENDED;
3. starts it again the way the product opens Codex (core's codex_link.open_in_codex: the app's own link to the person's
   newest own conversation, handed to Windows - measured to start a closed app there) and waits START_SECONDS for its
   main process - no conversation to open, or no app after that, is NOT_STARTED;
4. reads the account afresh (codex/account.read: a session of its own) - RESTARTED where one is signed in, SIGNED_OUT
   where none is.

Each step's hands are a seam (`Hands`); a test fills every one and nothing real is asked, ended or started.
"""
from __future__ import annotations

import time

from ..vocabulary import ObservedWord as _Word

# How long each wait lasts, in seconds, and how often it looks.
END_SECONDS = 30
KILL_SECONDS = 15
START_SECONDS = 60
LOOK_SECONDS = 1.0
# What a restart came to (the card's word, and MALR's closed word - vocabulary.ObservedWord; never stored).
RESTARTED, SIGNED_OUT, NOT_RUNNING, NOT_ENDED, NOT_STARTED, FAILED = (
    str(_Word.RESTARTED), str(_Word.RESTARTED_SIGNED_OUT), str(_Word.NOT_RUNNING), str(_Word.NOT_ENDED),
    str(_Word.NOT_STARTED), str(_Word.RESTART_FAILED))
OUTCOMES = (RESTARTED, SIGNED_OUT, NOT_RUNNING, NOT_ENDED, NOT_STARTED, FAILED)
# How the app ended: closed on Windows' request, or its process ended.
CLOSED, ENDED = str(_Word.CLOSED), str(_Word.ENDED)
# Why it is not the time (`busy`): a turn running, a recovery waiting or running, something queued in Codex, or a
# reading that failed.
TURN_RUNNING, RECOVERY, QUEUED, UNKNOWN = "turn_running", "recovery", "queued", "unknown"


class Hands:
    """What `restart` does to the world, each a method a test replaces: the process inventory (core's), a process's
    creation time or None where it has ended, Windows' request to close it, its end, the newest own conversation, the
    link handed to Windows, the account read afresh, and the clock. MALR's probe gives the Codex home and the account read
    it measures with (`home`, `read`); everything else is the product's own."""

    def __init__(self, paths, *, home=None, read=None):
        self.paths = paths
        self._home = home
        self._read = read

    def inventory(self):
        from codex_auto_resume.codex.pairing import inventory
        return inventory()

    def created(self, pid):
        from codex_auto_resume.domain.errors import AdapterError
        from codex_auto_resume.win.kernel import process_identity
        try:
            return process_identity(pid)["created"]
        except AdapterError:
            return None

    def ask_close(self, pid, created):
        from ..win.appclose import ask_close
        return ask_close(pid, created)

    def end_process(self, pid, created):
        from ..win.appclose import end_process
        return end_process(pid, created)

    def newest_conversation(self):
        from . import inuse
        from .threads import Threads
        own = Threads(self._home if self._home is not None else inuse.home(self.paths)).own(1)
        return own[0][0] if own else None

    def open(self, link):
        from codex_auto_resume.codex_link import open_in_codex
        return open_in_codex(link)

    def read(self):
        if self._read is not None:
            return self._read()
        from .account import read
        return read(self.paths)

    def now(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)


def busy(paths, *, source=None, store=None, now=None) -> tuple:
    """Why Codex may not be restarted now - (TURN_RUNNING or QUEUED, RECOVERY) as they stand, (UNKNOWN,) where any of
    them cannot be read - or () when it may. `source` (core's LocalSource's shape: `activity`), `store` (core's Store,
    opened: `pending` and `watcher_status`) and `now` are a test's."""
    from codex_auto_resume import poweraction
    from codex_auto_resume.domain.power_vocabulary import PowerWait
    try:
        if store is None:
            from codex_auto_resume.store import Store
            with Store(paths.state_dir) as opened:
                rows, status = opened.pending(), opened.watcher_status()
        else:
            rows, status = store.pending(), store.watcher_status()
        if source is None:
            from pathlib import Path
            from codex_auto_resume.codex import LocalSource
            from . import inuse
            source = LocalSource(Path(inuse.home(paths)))
        word = poweraction.judge_activity(source.activity((), time.time() if now is None else now,
                                                          booted=(status or {}).get("booted_at")))
    except Exception:
        return (UNKNOWN,)
    found = {PowerWait.TURN_RUNNING: [TURN_RUNNING], PowerWait.QUEUED_INPUT: [QUEUED], None: []}.get(word)
    if found is None:
        return (UNKNOWN,)
    if any(not row.get("hold") and not row.get("cancel_requested") for row in rows):
        found.append(RECOVERY)
    return tuple(found)


def _main(hands):
    """The app's main as (pid, creation time); None where the app does not run. Raises LookupError where it cannot be
    told (several mains, or the inventory unread)."""
    from codex_auto_resume.codex import pairing
    from codex_auto_resume.domain.errors import AdapterError
    try:
        rows = hands.inventory()
        if not pairing.app_running(rows):
            return None
        pid = pairing._app_main(rows)["pid"]
    except (AdapterError, KeyError, TypeError, ValueError):
        raise LookupError("the app's main cannot be told") from None
    created = hands.created(pid)
    if created is None:
        raise LookupError("the app's main ended as it was found")
    return pid, created


def _until(hands, seconds, done) -> bool:
    """Whether `done()` came true within `seconds`, looking every LOOK_SECONDS."""
    deadline = hands.now() + seconds
    while True:
        try:
            if done():
                return True
        except Exception:
            pass
        if hands.now() >= deadline:
            return False
        hands.sleep(LOOK_SECONDS)


def restart(paths, *, hands=None) -> tuple:
    """(what the restart came to - one of OUTCOMES -, how the app ended - CLOSED, ENDED or None); see the module."""
    from codex_auto_resume.codex_link import codex_thread_uri
    hands = hands or Hands(paths)
    try:
        main = _main(hands)
    except LookupError:
        return FAILED, None
    if main is None:
        return NOT_RUNNING, None
    pid, created = main

    def gone():
        return hands.created(pid) != created

    how = None
    try:
        asked = hands.ask_close(pid, created) is True
    except Exception:
        asked = False
    if asked and _until(hands, END_SECONDS, gone):
        how = CLOSED
    elif _until(hands, 0, gone):
        how = CLOSED                                   # it closed although Windows did not say so
    else:
        try:
            ended = hands.end_process(pid, created) is True
        except Exception:
            ended = False
        if not (ended and _until(hands, KILL_SECONDS, gone)):
            return NOT_ENDED, None
        how = ENDED
    try:
        link = codex_thread_uri(hands.newest_conversation())
        opened = link is not None and hands.open(link) is True
    except Exception:
        opened = False
    if not opened:
        return NOT_STARTED, how

    def back():
        found = _main(hands)
        return found is not None and found != main
    if not _until(hands, START_SECONDS, back):
        return NOT_STARTED, how
    found = hands.read()
    return (RESTARTED if isinstance(found, dict) and found.get("present") is True else SIGNED_OUT), how

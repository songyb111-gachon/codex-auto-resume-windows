"""The power action's file, and every way it is written (v0.6.12; poweraction.py says what it decides).

config/power-action.json holds one arming: what to do, after what, how often, how long to warn, the
batch's nonce, when it was armed and the batch began, the open usage-limit recoveries it carries, and
a stop if a person pressed one - then what the watcher last showed, and how the last batch ended. Ids,
times and closed words, and nothing of any conversation (D2). Out of the store, so no schema moves and
no version picker's downgrade has to carry it; out of settings.json, which is policy - and which the
Dashboard's Save writes whole, so a field there could silently arm a spent Once again (H2). The
precedent is config/failure-seen.json (seen.py). A missing file is off; so is one that cannot be
believed, which is never rewritten until the next arming.

Who writes what:

    arm_power_action      the Dashboard, through the bridge, and nothing else (H14): a person's choice,
                          refused while an administrator's DisablePowerAction is set, while an older
                          watcher holds the state, or when Windows will not do it for this account
    disarm_power_action   anyone: the Dashboard, MCP, the icon, a notice, the watcher - it only reduces
    stop_power_countdown  a notice's stop button, from the card or a toast: stops one batch, named by
                          its nonce, so a notice of a batch that is over stops nothing
    power_batch_end       the watcher: Once is spent; Always begins the next batch under a new nonce
    power_batch_finish    the watcher, as a countdown runs out: the same end, done - or skipped when a
                          stop came meanwhile - written before the action, under the one lock
    power_refused         the watcher: Windows refused the action a batch was ended done for
    power_show            the watcher: what it waits for, or until when it counts down - display only

Each write takes one named lock, rereads, decides and replaces the file whole (a temporary file of a
name nobody can plant a link at, flushed to disk, then moved over it). Without the lock nothing is
written. Nothing here sends anything, and nothing here asks Windows anything but whether an action is
available (win/powerdown.py, the port, which a test stands in for).
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import time

from .. import config, poweraction
from ..domain import ids
from ..domain.power_vocabulary import PowerEnd, PowerRepeat
from ..openstate import UPGRADE_PENDING
from ..store import LegacyStore
from ..win import powerdown
from ..windows import Mutex
from .errors import ControlError

POWER_LOCK_SECONDS = 5.0
# Who may turn it off or stop a batch: everyone but a model may not arm, and none of these arms.
DISARM_ACTORS = ("dashboard", "mcp", "tray", "toast", "card", "watcher")
STOP_ACTORS = ("toast", "card", "dashboard")
STOPPED, IGNORED = "stopped", "ignored"
BUSY = "the state is busy"
FAILED = "the request could not be completed: %s"
UNAVAILABLE = "that power action is not available on this PC"
MANAGED = "your administrator has set this"


def _write(path, document) -> bool:
    """`document` to `path` whole: False where Windows refused, with nothing left behind."""
    try:
        descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix="power-action.", suffix=".tmp")
    except OSError:
        return False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, allow_nan=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return True
    except (OSError, ValueError, TypeError):
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return False


def read_file(path, now=None):
    """(why, document): poweraction.READ_OK and the file's contents as they may be believed; or None and
    READ_MISSING (no file), READ_INVALID (a link, a junction, too large, or not what poweraction allows)
    or READ_UNREADABLE (one that could not be read just now)."""
    now = time.time() if now is None else float(now)
    try:
        if config.is_link(path):
            return poweraction.READ_INVALID, None
        size = path.stat().st_size
    except FileNotFoundError:
        return poweraction.READ_MISSING, None
    except OSError:
        return poweraction.READ_UNREADABLE, None
    if size > poweraction.FILE_LIMIT:
        return poweraction.READ_INVALID, None
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return poweraction.READ_MISSING, None
    except UnicodeError:
        return poweraction.READ_INVALID, None
    except OSError:
        return poweraction.READ_UNREADABLE, None
    try:
        document = poweraction.read_document(json.loads(text), now)
    except (ValueError, RecursionError):
        document = None
    return (poweraction.READ_OK, document) if document is not None else (poweraction.READ_INVALID, None)


class PowerActionMixin:
    """Arming, disarming, stopping and ending the power action, and reading what is armed."""

    # The Windows port: win/powerdown.py, which a test replaces on its instance.
    power_port = powerdown

    # ------------------------------------------------------------ reading
    def read_power_action(self, now=None):
        """(why, document), as `read_file` says: what the watcher decides from and what every surface shows."""
        return read_file(self.paths.power_action_file, now)

    def power_view(self):
        """What a surface is told of the file (poweraction.view), or None while there is no file."""
        why, document = self.read_power_action()
        return None if why == poweraction.READ_MISSING else poweraction.view(document)

    def power_options(self) -> dict:
        """What the Dashboard's card draws: the view, each action and whether Windows will do it for this
        account here (and why not), an administrator's key, and an older watcher holding the state."""
        with self._open(legacy_ok=True) as store:
            legacy = isinstance(store, LegacyStore)
        actions = []
        for action in poweraction.ACTIONS:
            available, reason = self._power_available(action)
            actions.append({"value": action, "available": available, "reason": reason})
        return {"view": poweraction.view(self.read_power_action()[1]), "actions": actions,
                "managed": self.managed().disable_power_action, "upgrade_pending": legacy}

    def _power_available(self, action):
        try:
            available, reason = self.power_port.available(action)
        except Exception:
            return False, None
        return bool(available), reason if reason in poweraction.UNAVAILABLE else None

    # ------------------------------------------------------------ writing
    def _power_change(self, change, now):
        """Under the lock, reread the file and write what `change(why, document)` returns - None writes
        nothing. Returns what `change` returned. Busy is a refusal, and so is a write Windows refused."""
        path = self.paths.power_action_file
        try:
            lock = Mutex(str(path), timeout=POWER_LOCK_SECONDS)
            lock.__enter__()
        except Exception:
            raise ControlError(BUSY, code="state_busy") from None
        try:
            why, document = read_file(path, now)
            written = change(why, document)
            if written is None:
                return None
            try:                                # what is about to be written, read back as the file would be
                believed = poweraction.read_document(json.loads(json.dumps(written, allow_nan=False)), now)
            except (ValueError, TypeError):     # a NaN or an infinity, which no JSON file may hold
                believed = None
            if believed is None:
                raise ControlError(FAILED % "it would not be believed", code="request_failed")
            if not path.parent.is_dir() or not _write(path, written):
                raise ControlError(FAILED % "the file could not be written", code="request_failed")
            return written
        finally:
            lock.__exit__(None, None, None)

    def arm_power_action(self, choice, actor="dashboard") -> dict:
        """Arm it as a person chose in the Dashboard - the only place it is armed - and return the view.

        A second arming replaces the first. It carries the usage-limit recoveries open now, and begins its
        batch now; a fresh nonce names it."""
        if actor != "dashboard":
            raise ControlError(FAILED % "it is turned on only in the Dashboard", code="request_failed")
        problem = poweraction.choice_problem(choice)
        if problem is not None:
            raise ControlError(FAILED % problem, code="request_failed")
        if self.managed().disable_power_action:
            raise ControlError(MANAGED, code="managed_by_policy")
        with self._open() as store:
            if isinstance(store, LegacyStore):
                raise ControlError(UPGRADE_PENDING, code="upgrade_pending")
            carried = [row["interruption_id"] for row in store.pending()
                       if row.get("category") == "usage_limit" and ids.is_digest(row["interruption_id"])]
        if not self._power_available(choice["action"])[0]:
            raise ControlError(UNAVAILABLE, code="power_unavailable")
        now = time.time()
        armed = {"nonce": secrets.token_hex(ids.POWER_NONCE_LENGTH // 2), "action": choice["action"],
                 "after": choice["after"], "repeat": choice["repeat"],
                 "grace_seconds": choice["grace_minutes"] * 60, "armed_at": now, "since": now,
                 "carried": list(dict.fromkeys(carried))[:poweraction.MAX_CARRIED], "stop_at": None}

        def change(why, document):
            kept = document if why == poweraction.READ_OK else poweraction.blank()
            return dict(kept, armed=armed, shown=None)
        return poweraction.view(self._power_change(change, now))

    def disarm_power_action(self, actor) -> dict:
        """Turn it off, from anywhere: the arming goes, what was shown with it, and how the last batch
        ended is kept. {"changed": whether there was an arming}. A file that cannot be believed is off
        already, and is left as it is."""
        if actor not in DISARM_ACTORS:
            raise ControlError(FAILED % "an unknown actor", code="request_failed")

        def change(why, document):
            if why != poweraction.READ_OK or document["armed"] is None:
                return None
            return dict(document, armed=None, shown=None)
        return {"changed": self._power_change(change, time.time()) is not None}

    def stop_power_countdown(self, nonce, actor="toast") -> str:
        """A notice's stop button: STOPPED, with the stop written for the watcher to end the batch
        skipped at its next look - in any phase - when `nonce` is the armed batch's; IGNORED for any
        other, which is a notice of a batch that is over, or no nonce at all."""
        if actor not in STOP_ACTORS:
            raise ControlError(FAILED % "an unknown actor", code="request_failed")
        if not ids.is_power_nonce(nonce):
            return IGNORED
        now = time.time()

        def change(why, document):
            armed = document["armed"] if why == poweraction.READ_OK else None
            if armed is None or armed["nonce"] != nonce:
                return None
            if armed["stop_at"] is not None:
                return document
            return dict(document, armed=dict(armed, stop_at=now))
        return STOPPED if self._power_change(change, now) is not None else IGNORED

    def power_batch_end(self, nonce, result, now=None) -> bool:
        """The watcher ends the batch `nonce` names as `result` (a PowerEnd): a Once is spent, and an
        Always begins its next batch now, under a new nonce, carrying nothing. Whether it was written -
        never, when the nonce is not the armed batch's any more. The new nonce is what makes a notice of
        the batch that ended, still in the notification center, stop nothing."""
        if result not in poweraction.ENDS or not ids.is_power_nonce(nonce):
            return False
        now = time.time() if now is None else float(now)

        def change(why, document):
            armed = document["armed"] if why == poweraction.READ_OK else None
            if armed is None or armed["nonce"] != nonce:
                return None
            last = {"action": armed["action"], "result": result, "at": now}
            if armed["repeat"] == PowerRepeat.ONCE:
                return dict(document, armed=None, shown=None, last=last)
            following = dict(armed, nonce=self._fresh_nonce(nonce), since=max(now, armed["armed_at"]),
                             carried=[], stop_at=None)
            return dict(document, armed=following, shown=None, last=last)
        try:
            return self._power_change(change, now) is not None
        except ControlError:
            return False

    def power_batch_finish(self, nonce, now=None):
        """The watcher's countdown ran out (step 16): under the lock, reread, and end the batch `nonce`
        names DONE - written before anything is done, so a write that fails does nothing - or SKIPPED
        when a stop was written for it meanwhile, because a stop wins whatever else happened. The
        PowerEnd written, or None when nothing was: the nonce is not the armed batch's any more, or
        the file could not be written."""
        if not ids.is_power_nonce(nonce):
            return None
        now = time.time() if now is None else float(now)
        ended = []

        def change(why, document):
            armed = document["armed"] if why == poweraction.READ_OK else None
            if armed is None or armed["nonce"] != nonce:
                return None
            result = PowerEnd.SKIPPED if armed["stop_at"] is not None else PowerEnd.DONE
            ended.append(result.value)
            last = {"action": armed["action"], "result": result.value, "at": now}
            if armed["repeat"] == PowerRepeat.ONCE:
                return dict(document, armed=None, shown=None, last=last)
            following = dict(armed, nonce=self._fresh_nonce(nonce), since=max(now, armed["armed_at"]),
                             carried=[], stop_at=None)
            return dict(document, armed=following, shown=None, last=last)
        try:
            written = self._power_change(change, now)
        except ControlError:
            return None
        return ended[-1] if written is not None and ended else None

    def power_refused(self, now=None) -> bool:
        """Windows refused what the watcher had just ended a batch DONE for: `last` says FAILED from now
        on, so the Dashboard tells it. Only a `last` that says DONE is changed; nothing is retried."""
        now = time.time() if now is None else float(now)

        def change(why, document):
            last = document["last"] if why == poweraction.READ_OK else None
            if last is None or last["result"] != PowerEnd.DONE:
                return None
            return dict(document, last=dict(last, result=PowerEnd.FAILED.value, at=now))
        try:
            return self._power_change(change, now) is not None
        except ControlError:
            return False

    @staticmethod
    def _fresh_nonce(old):
        while True:
            nonce = secrets.token_hex(ids.POWER_NONCE_LENGTH // 2)
            if nonce != old:
                return nonce

    def power_show(self, nonce, shown, now=None) -> bool:
        """The watcher writes what it shows - {"phase", "waiting_for", "grace_until"} - only when it
        changed and `nonce` is the armed batch's. Display only: nothing decides from it."""
        if not isinstance(shown, dict) or set(shown) != {"phase", "waiting_for", "grace_until"}:
            return False
        now = time.time() if now is None else float(now)

        def change(why, document):
            armed = document["armed"] if why == poweraction.READ_OK else None
            if armed is None or armed["nonce"] != nonce:
                return None
            wanted = dict(shown, nonce=nonce)
            return None if document["shown"] == wanted else dict(document, shown=wanted)
        try:
            return self._power_change(change, now) is not None
        except ControlError:
            return False

"""What core holds of something a plug names: a channel, a route and (v0.6.14) an errand.

A hook answers; it never sends, claims or starts anything (domain/plug.py). Where a point's answer is
something core carries out - a channel the one send is handed to (P5), a route that continues a
conversation the app does not hold (P16), an errand run once a tick (P8) - core holds it as one of
these and calls only its one method, at the moment core chooses and with what core decides. Each is
held to a guard of core's: the launch guard, read under the store's write lock, for a channel and a
route; for an errand, guards it asks core for and enters itself, once each, in which a Pause, Observe
only or quiet hours that committed first refuse the one irrevocable thing it was going to do.

Pure, as the rest of domain/: the standard library only, and nothing read or written here.
"""
from __future__ import annotations

from contextlib import nullcontext

# How many guards one errand may ask for in one tick: one for each capability whose errand the plug
# joins into it, and no more. A guard asked for past this is refused without a transaction.
ERRAND_GUARDS = 8


class Channel:
    """A channel a plug named at P5, held to the launch guard rather than asked to enter it.

    Core's backend enters the guard it is handed around the one moment it launches the queue
    process, so a Pause, a cancel or a conversation switched off that committed after the claim
    stops the send there. A channel is the plug's code, and nothing made it enter the guard it
    was handed, so this enters the guard for it: consent is read under the store's write lock,
    and the channel is called only if it held, with a guard already decided.

    The lock is let go before the channel is called, as core's backend lets it go once the
    queue process is launched: calling the channel is this send's launch. Held across a
    transport core cannot see into - the lock being the advanced state's too once the claim
    attached it - a Pause, a disarm on another thread and the channel's own write all waited for
    it, and failed past SQLite's ten seconds. A Pause that commits once consent was read finds a
    send started, as it finds one of the backend's after its launch.

    `client_id` is handed on only when core gives one - a continuation it sends with no marker
    (P15) - so a channel that was never asked for that is called exactly as before."""
    __slots__ = ("_send",)

    def __init__(self, send):
        self._send = send

    def send(self, thread_id, prompt, *, launch_guard=None, client_id=None):
        with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
            pass
        if permitted is not True:
            return {"outcome": "not_started", "error_code": "queue_consent_refused"}
        if client_id is None:
            return self._send(thread_id, prompt, launch_guard=nullcontext(True))
        return self._send(thread_id, prompt, launch_guard=nullcontext(True), client_id=client_id)


class Route:
    """A route a plug named at P16, held to the launch guard as a channel is (`Channel`).

    Consent is read under the store's write lock, and the route is called only if it held, with
    a guard already decided and the lock let go - the route is the plug's code, and a transport
    core cannot see into, and a Pause or a disarm must never wait behind it. `resume` is the
    route's one method, and the only thing of it core ever calls.

    `still_unloaded` is core's own look at whether the app still does not hold the conversation
    (engine/delivery.py), handed on, when core gives one, for the route to ask at the last moment
    before it changes anything in Codex: the app may open the conversation while a session starts."""
    __slots__ = ("_resume",)

    def __init__(self, resume):
        self._resume = resume

    def resume(self, thread_id, *, launch_guard=None, still_unloaded=None):
        with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
            pass
        if permitted is not True:
            return {"outcome": "not_started", "error_code": "queue_consent_refused"}
        if still_unloaded is None:
            return self._resume(thread_id, launch_guard=nullcontext(True))
        return self._resume(thread_id, launch_guard=nullcontext(True), still_unloaded=still_unloaded)


class _Once:
    """One guard an errand asked for: entered once, and refused - False, no transaction - if it is
    entered again, so a guard is one irrevocable thing at most."""
    __slots__ = ("_make", "_used", "_held")

    def __init__(self, make):
        self._make, self._used, self._held = make, False, None

    def __enter__(self):
        if self._used:
            return False
        self._used = True
        self._held = self._make()
        return self._held.__enter__() is True

    def __exit__(self, *raised):
        held, self._held = self._held, None
        return bool(held.__exit__(*raised)) if held is not None else False


class Errand:
    """What a plug answered at P8 (v0.6.14): something with a callable `run`, held so that core
    calls it once, last in the tick, with a way to ask for guards and nothing else.

    `guard` is core's: each call makes one of the store's errand guards (store/claims.py), which an
    errand enters around the one write that cannot be taken back - a request made to Codex - and
    whose `permitted` says whether recovery is on, not only observed, not stopped by an administrator
    and outside quiet hours, read under the store's write lock: a Pause that committed first refuses
    it. Each guard enters once (`_Once`), and one errand asks for at most ERRAND_GUARDS of them a
    tick. What it reads, and what it waits for, it does outside them, as the queue launch lets the
    lock go before its receipt."""
    __slots__ = ("_run",)

    def __init__(self, run):
        self._run = run

    def run(self, guard):
        asked = []

        def one():
            asked.append(None)
            return _Once(guard if len(asked) <= ERRAND_GUARDS else (lambda: nullcontext(False)))
        return self._run(one)

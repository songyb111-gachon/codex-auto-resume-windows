"""Starting the watcher, stopping it, and starting one from Codex."""
from __future__ import annotations

import time

from .. import config, edition, notice_kinds, notifier, notify
from ..app import EXIT_ERROR, EXIT_OK
from ..store import LegacyStore, StoreError
from ..windows import WakeEvent
from .base import CliError, _app, _now, _open_state, _print


def cmd_run(args) -> int:
    app = _app(args)
    return app.run(once=args.once, poll=args.poll)


def cmd_stop(args) -> int:
    app = _app(args)
    if app.stop_event().signal():
        for _ in range(40):
            if app.watcher_running() is False:
                break
            time.sleep(0.25)
        _print("stop requested" + ("; watcher exited" if app.watcher_running() is False else "; watcher still finishing"))
        return EXIT_OK
    _print("no running watcher found")
    return EXIT_OK


def _open_codex_on(app) -> bool:
    """Whether a notice raised here may offer Open Codex now (v0.6.18): never in the standard edition, whose buttons
    cancel, stop the power action or open a Dashboard page and nothing else (A28); in the advanced edition only while
    its plug's icon surface says so - the capability on and Windows able to open the link - as the watcher's own
    notices ask it (runtime/app.py). Asked only of a cancel URI that carries the flag."""
    if edition.name() != edition.Edition.ADVANCED:
        return False
    try:
        added = edition.plug(app.paths).surface("tray", {})
    except Exception:
        return False
    notice = added.get("notice") if isinstance(added, dict) else None
    return isinstance(notice, dict) and notice.get("open_codex") is True


def cmd_activate(args) -> int:
    """Handle a notification button. Reached from Windows, never from a terminal.

    A URI can request exactly three things: *cancelling* one resume, *opening* one page of
    the Dashboard, or (v0.6.12, the A28 amendment) *stopping the power action* for the one batch
    its nonce names. None can make anything happen that should not - a hostile URI can at
    worst stop something from happening or open a window. The interruption id is validated
    as opaque hex and must match a real record; nothing is looked up by thread, name or
    recency. The page must be one of the window's own pages. The nonce is 16 hex digits and
    stops nothing unless it is the armed batch's; that press goes through the same branch a
    card's does (notifier.activate), and what it says afterwards is raised as a toast.
    """
    app = _app(args)
    chat_thread = notify.parse_chat_uri(args.uri)
    if chat_thread is not None:
        # v0.6.19: a click on a notice's body that goes to the advanced edition's chat at that conversation.
        from ..ui import tray
        opened = tray.open_chat(app.paths.home, chat_thread)
        app.logger.info("the chat opened from a notification" if opened
                        else "activation: the Dashboard is not installed here")
        return EXIT_OK if opened else EXIT_ERROR
    page = notify.parse_open_uri(args.uri)
    if page is not None:
        from ..ui import tray
        opened = tray.open_dashboard(app.paths.home, page)
        app.logger.info("dashboard opened from a notification" if opened
                        else "activation: the Dashboard is not installed here")
        return EXIT_OK if opened else EXIT_ERROR
    if notify.parse_power_stop_uri(args.uri) is not None:
        from ..control import Control
        done = notifier.activate(args.uri, control=Control(app.paths),
                                 announce=lambda notice: notifier.deliver(notice, inbox=None, setting=False),
                                 log=app.logger.info, stay=notice_kinds.chosen(app.settings))
        return EXIT_OK if done == "stopped" else EXIT_ERROR
    interruption_id = notify.parse_cancel_uri(args.uri)
    if interruption_id is None:
        app.logger.info("activation ignored: malformed or unsupported URI")
        return EXIT_ERROR
    # The button names one interruption, so it stops that task and whatever continues
    # it - not every later interruption in the conversation. Only while an older watcher
    # still owns the state does it fall back to that watcher's thread-wide cancel.
    # v0.6.18: tried again while the watcher holds the state, for as long as a card's Cancel is (control/actions.py
    # CANCEL_RETRY_SECONDS) - a busy store used to end this windowless process in an error nobody saw.
    from ..control.actions import CANCEL_RETRY_SECONDS
    deadline = time.monotonic() + CANCEL_RETRY_SECONDS
    while True:
        try:
            with _open_state(app) as store:
                if isinstance(store, LegacyStore):
                    thread_id = store.thread_of(interruption_id)
                    if thread_id is None:
                        app.logger.info("activation ignored: no record for that interruption")
                        return EXIT_ERROR
                    store.cancel_thread(thread_id, _now())
                else:
                    record = store.get(interruption_id)
                    if record is None:
                        app.logger.info("activation ignored: no record for that interruption")
                        return EXIT_ERROR
                    thread_id = record["thread_id"]
                    result = store.cancel_interruption(interruption_id, _now(), actor="toast")
                    if isinstance(result, dict) and result.get("changed") is False:
                        # v0.6.18: a stale notice's Cancel on a recovery that has finished since says nothing:
                        # the notice below says it was cancelled, which is not true (notifier.activate does the
                        # same for a card).
                        app.logger.info("thread %s: the notification's cancel changed nothing; it had already "
                                        "finished", thread_id)
                        _print("thread %s had already finished; nothing changed" % thread_id)
                        return EXIT_OK
            break
        except StoreError:
            if time.monotonic() >= deadline:
                app.logger.info("activation: the state stayed busy; the cancel was not recorded")
                return EXIT_ERROR
            time.sleep(0.5)
    app.logger.info("thread %s: cancelled from the notification", thread_id)
    # What it says afterwards is the notice a card's cancel announces (notifier.build_cancelled): the same words,
    # a body that opens its page, and staying on screen when a person chose that kind (v0.6.16) - Windows' toast,
    # as the power-stop branch above raises its own.
    # v0.6.18: with Open Codex where the notice pressed offered it - the decision the watcher made, carried on the
    # button's URI (notify.cancel_asks_open_codex), since this process loads no plug.
    # v0.6.18: the flag is honoured only where the edition offers the button now (_open_codex_on), so a crafted URI
    # cannot put Open Codex on a standard edition's notice (A28).
    open_codex = notify.cancel_asks_open_codex(args.uri) and _open_codex_on(app)
    notifier.deliver(notifier.with_open_codex(notifier.build_cancelled(thread_id, notice_kinds.chosen(app.settings)),
                                              open_codex), inbox=None, setting=False)
    _print("thread %s cancelled" % thread_id)
    return EXIT_OK

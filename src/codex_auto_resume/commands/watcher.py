"""Starting the watcher, stopping it, and starting one from Codex."""
from __future__ import annotations

import time

from .. import config, notifier, notify
from ..app import EXIT_ERROR, EXIT_OK
from ..store import LegacyStore
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
                                 log=app.logger.info)
        return EXIT_OK if done == "stopped" else EXIT_ERROR
    interruption_id = notify.parse_cancel_uri(args.uri)
    if interruption_id is None:
        app.logger.info("activation ignored: malformed or unsupported URI")
        return EXIT_ERROR
    # The button names one interruption, so it stops that task and whatever continues
    # it - not every later interruption in the conversation. Only while an older watcher
    # still owns the state does it fall back to that watcher's thread-wide cancel.
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
            store.cancel_interruption(interruption_id, _now(), actor="toast")
    app.logger.info("thread %s: cancelled from the notification", thread_id)
    notify.cancelled(thread_id)
    _print("thread %s cancelled" % thread_id)
    return EXIT_OK

"""The commands that act on one record or list them: enable, disable, pending, cancel, logs."""
from __future__ import annotations

import json

from .. import config, machine
from ..app import EXIT_ERROR, EXIT_OK
from ..logbook import format_local, tail
from ..store import TERMINAL, LegacyStore
from .base import CliError, _app, _now, _open_state, _print, canonical_thread_id


def cmd_enable(args) -> int:
    app = _app(args)
    if args.lookback_hours is not None:
        # An update, not a save: naming one field must never rewrite the other fifteen.
        app.settings = config.update_settings(app.paths, {"detection_lookback_hours": args.lookback_hours})
    with _open_state(app) as store:
        if args.thread_id:
            thread_id = canonical_thread_id(args.thread_id)
            store.set_thread_enabled(thread_id, True, actor="cli")
            app.logger.info("thread %s: enabled by user", thread_id)
            _print("thread %s enabled" % thread_id)
        else:
            store.set_enabled(True, _now())
            app.logger.info("auto-resume enabled by user (lookback %.1fh)", app.settings["detection_lookback_hours"])
            _print("auto-resume enabled (lookback %.1f h). Start the watcher with: run" % app.settings["detection_lookback_hours"])
            if app.watcher_running() is False:
                _print("note: no watcher is running; nothing will be resumed until `run` is started")
    return EXIT_OK


def cmd_disable(args) -> int:
    app = _app(args)
    with _open_state(app) as store:
        if args.thread_id:
            thread_id = canonical_thread_id(args.thread_id)
            store.set_thread_enabled(thread_id, False, actor="cli")
            app.logger.info("thread %s: disabled by user", thread_id)
            _print("thread %s disabled (pending records kept, never submitted while disabled)" % thread_id)
        else:
            store.set_enabled(False, _now())
            app.logger.info("auto-resume DISABLED by user (kill switch)")
            _print("auto-resume disabled: no continuation will be queued until `enable`")
    return EXIT_OK


def _record_view(row: dict) -> dict:
    return {
        "thread_id": row["thread_id"],
        "interruption_id": row["interruption_id"],
        "state": row["state"],
        "code": machine.public_code(row),
        "reason": machine.public_reason(row),
        "detected_at": format_local(row["detected_at"]),
        "reset_at": format_local(row["reset_at"]) if row["reset_at"] else None,
        "limit_type": row["limit_type"],
        "uncertain": row["uncertain"],
        "next_retry_at": format_local(row["next_retry_at"]) if row["next_retry_at"] else None,
        "retry_count": row["retry_count"],
        "attempt_count": row["attempt_count"],
        "resumed_at": format_local(row["resumed_at"]) if row["resumed_at"] else None,
        "last_error": row["last_error"],
        "queue_id": row["queue_id"],
        "cancel_requested": row["cancel_requested"],
    }


def cmd_pending(args) -> int:
    app = _app(args)
    with app.open_store() as store:
        rows = store.all_records() if args.all else store.pending()
        enabled = {row["thread_id"]: store.thread_enabled(row["thread_id"]) for row in rows}
    views = [dict(_record_view(row), thread_enabled=enabled[row["thread_id"]]) for row in rows]
    if args.json:
        _print(json.dumps(views, indent=2, ensure_ascii=False, allow_nan=False))
        return EXIT_OK
    if not views:
        _print("no pending interruptions")
        return EXIT_OK
    for view in views:
        _print("thread %s" % view["thread_id"])
        _print("  status       : %s%s" % (view["code"], "" if view["thread_enabled"] else "  (thread disabled)"))
        _print("  state        : %s" % view["state"])
        _print("  detected     : %s" % view["detected_at"])
        _print("  reset        : %s  [%s%s]" % (view["reset_at"] or "unknown", view["limit_type"] or "unknown", ", uncertain" if view["uncertain"] else ""))
        _print("  next check   : %s" % (view["next_retry_at"] or "-"))
        _print("  retries      : %d launch retries, %d reservations" % (view["retry_count"], view["attempt_count"]))
        if view["resumed_at"]:
            _print("  resumed      : %s" % view["resumed_at"])
        if view["last_error"]:
            _print("  last reason  : %s" % view["last_error"])
        _print("  interruption : %s" % view["interruption_id"][:16])
    return EXIT_OK


def cmd_cancel(args) -> int:
    app = _app(args)
    thread_id = canonical_thread_id(args.thread_id)
    with _open_state(app) as store:
        store.cancel_thread(thread_id, _now(), actor="cli")
        rows = ([row for row in store.all_records() if row["thread_id"] == thread_id]
                if not isinstance(store, LegacyStore) else [])
    app.logger.info("thread %s: cancel requested by user", thread_id)
    in_flight = [row for row in rows if row["state"] not in TERMINAL]
    _print("thread %s cancelled and disabled" % thread_id)
    if in_flight:
        _print("note: %d submission(s) already in flight will be reconciled and not resent" % len(in_flight))
    return EXIT_OK


def cmd_logs(args) -> int:
    paths = config.Paths(args.home)
    for line in tail(paths.log_file, args.lines):
        _print(line)
    return EXIT_OK

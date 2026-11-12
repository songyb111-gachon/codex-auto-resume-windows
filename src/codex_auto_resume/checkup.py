"""The Diagnostics check (v0.6.16-beta.3): why a failed turn is not taken up, answered by the watcher itself.

It replaces the two one-click scripts issue #27 was diagnosed with. The second of those copied the watcher's
rule for whose conversations count - an old one, 'user' only - and so told a person a conversation the
watcher took up was not one it would. This copies no rule: every verdict is the watcher's own function,
asked on the spot -

* how Codex recorded each recent conversation's latest turn, and whether the failure scan brings it, and
  why not (codex/history.py `passed_over`, the read and the order `latest_failures` decides in);
* for one it brings, every other reason it is still not taken up - the engine's own (engine/detect.py
  `not_taken_up`, `detection_since`) over the product's own records, with the Settings in force;
* the conversations whose turns Codex records under another id (issue #30), each Codex home the watcher
  knows with when its databases were last written, how many cloud tasks the app knows (they cannot be
  recovered yet), the last usage reading, how notices reach the person now, the Codex version and its
  compatibility, and the last skip lines the watcher wrote (logbook.skipped).

Read only, everywhere: nothing is written, sent or started, and no process is asked anything (B12) - which
home the app writes to now is told by its databases' last write times alone. Content-free: no title,
message or prompt is read; conversation ids are aliases valid only in one result (diagnostics.Redactor);
another home is a number, never its folder or the alias a person gave it.
"""
from __future__ import annotations

import time

from pathlib import Path

from . import config, homes as homes_module, l10n, notice_presence, notify, settings as settings_module
from .codex import LocalSource
from .codex.chains import memory as chain_memory
from .diagnostics import Redactor, _compatibility
from .domain import skips
from .engine import Engine

# How far back conversations are looked at, how many of them at most (the newest), the longest the check may take
# explaining them - well under the Dashboard's wait for a bridge answer (gui/Dashboard.cs, 30 s) - and the most
# skip lines shown.
HOURS = 72
NEWEST = 200
SECONDS = 10.0
SKIP_LINES = 20
# The windows of a usage reading the check names, by their length in minutes.
FIVE_HOURS, WEEK = 300, 10080
# The summary's reasons, most likely first, where a check sees more than one.
FIRST = (skips.RECOVERY_OFF, "watcher_stopped", skips.CONVERSATION_OFF, skips.CATEGORY_OFF,
         skips.BEFORE_WINDOW, skips.OTHER_KIND, skips.CONTINUED_ELSEWHERE, skips.UNKNOWN_CONVERSATION,
         skips.NOT_RECOVERED, skips.NEWER_TURN)


def _presence():
    """How a notice reaches the person now: card or toast, Do not disturb, this app's notifications - each
    None when Windows cannot say (notice_presence.snapshot, read only)."""
    found = notice_presence.snapshot(notify.aumid())
    mode, allowed = found.get("notification_mode"), found.get("app_notifications")
    card = notice_presence.card_allowed(setting=True, tray_present=True, **found)
    return {"route": "card" if card else "toast",
            "do_not_disturb": None if type(mode) is not int else mode != notice_presence.MODE_UNRESTRICTED,
            "app_allowed": None if type(allowed) is not int else allowed == notice_presence.APP_ENABLED}


def _ago(seconds, locale):
    if seconds is None:
        return l10n.text("check.never", locale)
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return l10n.text("check.ago_minutes", locale, n=str(seconds // 60))
    if seconds < 2 * 86400:
        return l10n.text("check.ago_hours", locale, n=str(seconds // 3600))
    return l10n.text("check.ago_days", locale, n=str(seconds // 86400))


def _within(seconds, locale):
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return l10n.text("check.in_minutes", locale, n=str(seconds // 60))
    return l10n.text("check.in_hours", locale, n=str(seconds // 3600))


def _reason(code, kind, locale):
    """A reason's words; its kind word, where it has one, after them."""
    key = "check.reason." + code
    if key not in l10n.catalog(locale):
        return code
    words = l10n.text(key, locale)
    return words + " (" + kind + ")" if kind else words


def _usage(status, now):
    usage = ((status or {}).get("watcher") or {}).get("usage")
    if not isinstance(usage, dict) or not isinstance(usage.get("windows"), list):
        return {"read": False, "read_at": None, "five_hour": None, "weekly": None, "reset_at": None}
    found = {"read": True, "read_at": usage.get("read_at"), "five_hour": None, "weekly": None, "reset_at": None}
    resets = []
    for window in usage["windows"]:
        if not isinstance(window, dict):
            continue
        minutes, used = window.get("window_minutes"), window.get("used_percent")
        name = "five_hour" if minutes == FIVE_HOURS else "weekly" if minutes == WEEK else None
        if name and found[name] is None and type(used) in (int, float):
            found[name] = used
        if type(window.get("reset_at")) in (int, float) and window["reset_at"] > now:
            resets.append(window["reset_at"])
    found["reset_at"] = min(resets) if resets else None
    return found


def _skip_lines(control, redact):
    """The watcher's last skip lines (logbook.skipped, and the two lines beside them), redacted."""
    try:
        found = control.search_logs("not taken up", limit=SKIP_LINES)["lines"]
        found += control.search_logs("automatic recovery is off", limit=3)["lines"]
    except Exception:
        return []
    lines = sorted(found, key=lambda line: line["at"])[-SKIP_LINES:]
    return [redact.text("%s %s" % (line["at"], line["text"])) for line in lines]


def _conversations(control, sources, engine_for, now, redact):
    """Part 1 and part 2 for every home: each recent conversation's latest turn, and for one the failure
    scan brings, the engine's own remaining reasons and the records it already has of that turn."""
    found, homes, left = [], [], {"conversations": 0, "unchecked": 0}
    deadline = time.monotonic() + SECONDS
    with control._open() as store:
        stored = store.settings()
        records = store.all_records()
        for label, source in sources:
            home = {"home": label, "state_written": None, "history_written": None, "current": False,
                    "readable": True, "cloud_tasks": None}
            try:
                home.update(source.written())
                home["cloud_tasks"] = source.cloud_tasks()
            except Exception:
                home["readable"] = False
            homes.append(home)
            engine = engine_for(store, source)
            since = engine.detection_since(stored)
            try:
                read = source.passed_over(since, now - HOURS * 3600, every_status=True, newest=NEWEST,
                                          deadline=deadline)
            except Exception:
                home["readable"] = False
                continue
            left["conversations"] += read["more"]
            left["unchecked"] += read["unchecked"]
            for entry in read["passed"]:
                row = {"thread": redact.alias(entry["thread_id"], "thread"), "home": label,
                       "status": entry["status"], "category": entry["category"],
                       "completed_at": entry["completed_at"], "reason": entry["reason"], "kind": entry["kind"],
                       "turns_under": redact.alias(entry["turns_id"], "thread") if entry["turns_id"] else None,
                       "brought": entry["status"] == "failed" and entry["reason"] is None,
                       "remaining": [], "records": []}
                if row["brought"]:
                    if not stored["enabled"] or engine.managed.disable_auto_resume:
                        row["remaining"].append(skips.RECOVERY_OFF)
                    why = engine.not_taken_up(entry)
                    if why is not None:
                        row["remaining"].append(why[0])
                    row["records"] = [record["state"] for record in records
                                      if record["thread_id"] == entry["thread_id"]
                                      and record["turn_id"] == entry["turn_id"]]
                found.append(row)
    written = [home["history_written"] for home in homes if home["history_written"] is not None]
    for home in homes:
        home["current"] = bool(written) and home["history_written"] == max(written)
    found.sort(key=lambda row: row["completed_at"] or 0)
    return found, homes, stored, left


def _summary(rows, watcher_running, cloud):
    """The most likely reason, as a code: of the latest failed turn the check saw, else of none."""
    failed = [row for row in rows if row["status"] == "failed"]
    if not failed:
        return "cloud" if cloud else "nothing"
    latest = failed[-1]
    if latest["records"]:
        return "taken"
    reasons = ([latest["reason"]] if latest["reason"] else []) + latest["remaining"]
    if latest["brought"] and not watcher_running:
        reasons.append("watcher_stopped")
    if not reasons:
        return "ready"
    return min(reasons, key=lambda code: FIRST.index(code) if code in FIRST else len(FIRST))


def sources_for(control) -> list:
    """(label, reader) for each Codex home the watcher knows: the default (label None) first, then each one
    Settings add, by its number (2, 3, ...) - never its folder or the alias a person gave it."""
    chains = chain_memory(control.paths.split_chains_file, writable=False)        # the watcher's, read only
    found = [(None, LocalSource(config.codex_home(), chains=chains))]
    try:
        named = control.get_settings().get(homes_module.FIELD) or []
    except Exception:
        named = []
    for number, entry in enumerate(named if isinstance(named, list) else [], 2):
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            found.append((number, LocalSource(Path(entry["path"]), chains=chains)))
    return found


def for_bundle(control):
    """The check as the diagnostics bundle runs it (diagnostics.collect): in English, with the bundle's own
    aliases, so a conversation is the same alias in the check and in the records beside it."""
    return lambda redact: run(control, redact=redact, locale=l10n.DEFAULT)


def run(control, sources=None, *, now=None, redact=None, locale=None, presence=None) -> dict:
    """The check, run now: the structured result and `lines`, the same in words in `locale` (the
    Interface language by default), the summary first. `sources` are (label, LocalSource) for each Codex
    home the watcher knows (`sources_for`, the default)."""
    now = time.time() if now is None else now
    sources = sources_for(control) if sources is None else sources
    redact = redact or Redactor()
    if locale is None:
        try:
            locale = l10n.resolve(control.get_settings().get("interface_language"))
        except Exception:
            locale = l10n.DEFAULT
    values = settings_module.load(control.settings_path())
    try:
        settings_module.read(control.settings_path())
        unread = None
    except settings_module.Unreadable as exc:
        unread = exc.reason                     # v0.6.23: said second, after the summary (K1)
    held = control.managed()

    def engine_for(store, source):
        engine = Engine(store, source, None, clock=lambda: now)
        engine.apply_policy(values, held)
        return engine

    rows, homes, stored, left = _conversations(control, sources, engine_for, now, redact)
    try:
        status = control.get_status()
    except Exception:
        status = {}
    running = bool(status.get("watcher_running"))
    try:
        notices = (presence or _presence)()
    except Exception:
        notices = {"route": None, "do_not_disturb": None, "app_allowed": None}
    try:
        compat = _compatibility(control)
        codex = {"version": (compat.get("engine") or {}).get("version"), "tier": compat.get("overall"),
                 "engine_found": bool((compat.get("engine") or {}).get("found"))}
    except Exception:
        codex = {"version": None, "tier": None, "engine_found": False}
    cloud = [home["cloud_tasks"] for home in homes if isinstance(home["cloud_tasks"], int)]
    result = {"summary": _summary(rows, running, sum(cloud)), "watcher_running": running,
              "conversations": rows, "left_out": left,
              "split": sorted({(row["thread"], row["turns_under"]) for row in rows if row["turns_under"]}),
              "homes": homes, "cloud_tasks": sum(cloud) if cloud else None,
              "usage": _usage(status, now), "notices": notices, "codex": codex,
              "skips": _skip_lines(control, redact)}
    result["split"] = [{"thread": thread, "turns_under": other} for thread, other in result["split"]]
    result["lines"] = lines(result, now, locale)
    if unread is not None:
        # The verdicts above are on the defaults, which the watcher does not act on while the file cannot be read.
        result["lines"].insert(1, l10n.text("check.settings_unreadable", locale, reason=unread))
    return result


def lines(result, now, locale) -> list:
    """The result in words, a line each, the summary first."""
    t = lambda key, **fields: l10n.text(key, locale, **fields)  # noqa: E731
    said = []
    summary = result["summary"]
    if summary in ("nothing", "cloud", "ready", "taken"):
        said.append(t("check.summary." + summary, hours=str(HOURS)))
    else:
        said.append(t("check.summary", reason=_reason(summary, None, locale)))
    said.append("")
    said.append(t("check.part1", hours=str(HOURS)))
    if not result["conversations"]:
        said.append("  " + t("check.none_recent", hours=str(HOURS)))
    if result["left_out"]["conversations"]:
        said.append("  " + t("check.left_out", n=str(result["left_out"]["conversations"]), newest=str(NEWEST)))
    if result["left_out"]["unchecked"]:
        said.append("  " + t("check.unchecked", n=str(result["left_out"]["unchecked"])))
    for row in result["conversations"]:
        if row["brought"]:
            verdict = t("check.yes")
        elif row["status"] != "failed" and row["reason"] in (None,):
            verdict = t("check.no", reason=_reason("not_failed", None, locale))
        else:
            verdict = t("check.no", reason=_reason(row["reason"] or "not_failed", row["kind"], locale))
        when = _ago(now - row["completed_at"], locale) if row["completed_at"] else t("check.never")
        said.append("  " + t("check.row", when=when, thread=row["thread"], status=row["status"] or "?",
                               category=" (%s)" % row["category"] if row["category"] else "", verdict=verdict))
    said.append("")
    said.append(t("check.part2"))
    brought = [row for row in result["conversations"] if row["brought"]]
    if not brought:
        said.append("  " + t("check.part2_none"))
    for row in brought:
        if row["records"]:
            said.append("  " + t("check.recorded", thread=row["thread"], state=", ".join(row["records"])))
            continue
        held = list(row["remaining"]) + ([] if result["watcher_running"] else ["watcher_stopped"])
        if not held:
            said.append("  " + t("check.held_none", thread=row["thread"]))
        for code in held:
            said.append("  " + t("check.held", thread=row["thread"], reason=_reason(code, None, locale)))
    said.append("")
    said.append(t("check.split_title"))
    if not result["split"]:
        said.append("  " + t("check.split_none"))
    for pair in result["split"]:
        said.append("  " + t("check.split_row", thread=pair["thread"], other=pair["turns_under"]))
    said.append("")
    said.append(t("check.homes_title"))
    for home in result["homes"]:
        name = t("check.home_default") if home["home"] is None else t("check.home_other", n=str(home["home"]))
        if not home["readable"]:
            said.append("  " + t("check.home_unreadable", home=name))
            continue
        said.append("  " + t("check.home_row", home=name,
                               state=_ago(None if home["state_written"] is None else now - home["state_written"], locale),
                               history=_ago(None if home["history_written"] is None
                                            else now - home["history_written"], locale),
                               current=t("check.home_current") if home["current"] else ""))
    said.append("")
    count = result["cloud_tasks"]
    said.append(t("check.cloud", count=str(count)) if count else t("check.cloud_none"))
    usage = result["usage"]
    if usage["read"]:
        percent = lambda value: "?" if value is None else "%g" % value  # noqa: E731
        said.append(t("check.usage", when=_ago(now - usage["read_at"], locale) if usage["read_at"] else "?",
                      five=percent(usage["five_hour"]), weekly=percent(usage["weekly"]),
                      reset=_within(usage["reset_at"] - now, locale) if usage["reset_at"] else "?"))
    else:
        said.append(t("check.usage_none"))
    notices = result["notices"]
    word = lambda value, yes, no: t("check.unknown") if value is None else t(yes) if value else t(no)  # noqa: E731
    said.append(t("check.notices",
                  route=t("check.route." + notices["route"]) if notices["route"] else t("check.unknown"),
                  dnd=word(notices["do_not_disturb"], "check.on", "check.off"),
                  allowed=word(notices["app_allowed"], "check.allowed", "check.blocked")))
    codex = result["codex"]
    said.append(t("check.codex", version=codex["version"] or t("check.unknown"), tier=codex["tier"] or t("check.unknown"),
                  found=t("check.found") if codex["engine_found"] else t("check.not_found")))
    said.append("")
    said.append(t("check.skips_title"))
    if not result["skips"]:
        said.append("  " + t("check.skips_none"))
    said.extend("  " + line for line in result["skips"])
    return said

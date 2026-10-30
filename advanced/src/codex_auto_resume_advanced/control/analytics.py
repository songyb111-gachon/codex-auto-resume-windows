# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's usage and token analytics (v0.6.20, usage_analytics): its card read, and its CSV saved.

Each is the long-lived bridge's, the Dashboard's alone (surfaces.py); no MCP tool reaches either, and neither writes
anything of the edition's state.

* advanced-analytics {days}: the pace of each window the meter reads (engine/analytics.pace), and the tokens of each
  project over the last `days` local days (7, 30 or 90 - the capability's own choice where none is given), each with
  its conversations - aggregated here from token_days, the labels resolved now by core's own reader of each watched
  Codex home (codex/history.identity: Codex's project name, else the folder's last part; a conversation's own name),
  never stored (B8). A conversation the rollouts gave nothing for, of those that finished a turn in those days
  (codex/turns.recent), is shown with its lifetime total alone (`threads.tokens_used`, core's task_facts) - and where
  MTOK failed on the Codex in force that is all the card shows (route "lifetime", engine/analytics.route).
* advanced-analytics-csv {days, path, replace}: the same numbers as a CSV file at `path`, which the person chose in the
  Dashboard's save dialog - an absolute path, written only there (F3); never over a file unless the dialog itself asked
  and the person said yes (`replace`, D5's rule). Its columns: day, project, input, cached, output, reasoning, turns,
  lifetime - one row a day and project, then one a project of lifetime totals where there are any.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
import time

from ..codex import tokens
from ..engine.analytics import CAPABILITY, DAYS, DEFAULT_DAYS, pace, route
from ..engine.usage import WINDOWS
from ..vocabulary import ArmingState, Measurement, OptionKey, Refusal, ReportRefusal
from .resets import _refused

# How many projects the card lists, and conversations under each, at most.
PROJECTS_LIMIT = 50
CONVERSATIONS_LIMIT = 50
# The CSV's columns, in order.
COLUMNS = ("day", "project", "input", "cached", "output", "reasoning", "turns", "lifetime")
# A label a spreadsheet would take for a formula gets a quote before it.
FORMULA = ("=", "+", "-", "@", "\t", "\r")
NUMBERS = ("input", "cached", "output", "reasoning", "turns")


# ------------------------------------------------------------------------- seams (a test fills them)
def _homes(runtime) -> list:
    return tokens.watched_homes(runtime.paths)


def _source(home):
    """Core's read-only reader of one Codex home, for labels and lifetime totals."""
    from codex_auto_resume.codex import LocalSource
    return LocalSource(home)


def _recent(home, since) -> list:
    """The conversations of `home` that finished a turn since `since`, at most codex/turns.RECENT_LIMIT."""
    from ..codex.turns import Turns
    return Turns(home).recent(since)


# ------------------------------------------------------------------------- reading
def _standing(runtime) -> bool:
    try:
        return runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) in (ArmingState.ARMED, ArmingState.SHADOW)
    except Exception:
        return False


def _days(runtime, value):
    """The days asked for: one on offer, or the capability's own choice where none was asked; None for a wrong one."""
    if value is None:
        try:
            value = runtime.state.options(CAPABILITY).get(OptionKey.ANALYTICS_DAYS, DEFAULT_DAYS)
        except Exception:
            value = DEFAULT_DAYS
    return value if type(value) is int and value in DAYS else None


def _verdict(runtime):
    try:
        return runtime.arming.verdict(Measurement.MTOK)
    except Exception:
        return None


def first_day(now, days, local=time.localtime) -> str:
    """The first local day of the last `days` days up to `now`'s, as token_days writes a day."""
    return time.strftime("%Y-%m-%d", local(now - (days - 1) * 86400))


class _Labels:
    """Labels resolved at display time, never stored: each conversation's own name and its project's, through core's
    reader of whichever watched home holds it; None where none holds it or it has none."""

    def __init__(self, homes):
        self.homes = homes
        self._sources = {}
        self._seen = {}

    def source(self, home):
        if home not in self._sources:
            try:
                self._sources[home] = _source(home)
            except Exception:
                self._sources[home] = None
        return self._sources[home]

    def identity(self, thread):
        if thread not in self._seen:
            found = {"name": None, "project": None, "cwd_basename": None}
            for home in self.homes:
                source = self.source(home)
                try:
                    seen = source.identity(thread) if source is not None else None
                except Exception:
                    seen = None
                if seen and any(seen.get(name) for name in ("name", "project", "cwd_basename")):
                    found = dict(seen, home=home)
                    break
            self._seen[thread] = found
        return self._seen[thread]

    def project(self, thread):
        seen = self.identity(thread)
        return seen.get("project") or seen.get("cwd_basename")


def _lifetime(runtime, homes, labels, now, days, known) -> list:
    """(thread, project key, lifetime tokens) for each conversation that finished a turn in the last `days` and
    is not one of `known` - its count from core's reader, its key core's own, cut to 16 hex digits."""
    found, seen = [], set(known)
    for home in homes:
        try:
            threads = _recent(home, now - days * 86400)
        except Exception:
            threads = []
        source = labels.source(home)
        for thread in threads:
            if thread in seen or source is None:
                continue
            seen.add(thread)
            try:
                count = source.task_facts(thread, tokens=True).get("tokens")
                key = source.project_key(thread)
            except Exception:
                continue
            if count is None:
                continue
            found.append((thread, key[:16] if isinstance(key, str) and len(key) >= 16 else None, count))
    return found


def _numbers():
    return {name: 0 for name in NUMBERS}


def aggregate(runtime, days, *, now=None) -> dict:
    """The card's numbers: {"projects": [...], "total": {...}, "route": ...} - each project's key, label, five
    numbers, lifetime total and conversations, the largest first. Raises what the state raises."""
    now = runtime.clock() if now is None else now
    verdict = _verdict(runtime)
    way = route(verdict)
    homes = _homes(runtime)
    labels = _Labels(homes)
    rows = runtime.state.token_days(first_day(now, days)) if way == "per_day" else []
    projects, threads = {}, {}
    for row in rows:
        key = row["project_digest"]
        project = projects.setdefault(key, {"key": key, "label": None, **_numbers(), "lifetime": None,
                                            "conversations": {}})
        thread = project["conversations"].setdefault(row["thread_id"], {"thread_id": row["thread_id"], "label": None,
                                                                        **_numbers(), "lifetime": None})
        for name in NUMBERS:
            project[name] += row[name]
            thread[name] += row[name]
        threads[row["thread_id"]] = key
    for thread, key, count in _lifetime(runtime, homes, labels, now, days, threads):
        project = projects.setdefault(key, {"key": key, "label": None, **_numbers(), "lifetime": None,
                                            "conversations": {}})
        project["lifetime"] = (project["lifetime"] or 0) + count
        project["conversations"][thread] = {"thread_id": thread, "label": None, **_numbers(), "lifetime": count}
    shown = []
    for project in projects.values():
        conversations = sorted(project["conversations"].values(),
                               key=lambda item: (-(item["input"] + item["output"]), -(item["lifetime"] or 0)))
        for item in conversations[:CONVERSATIONS_LIMIT]:
            item["label"] = labels.identity(item["thread_id"]).get("name")
        for item in conversations:
            if project["label"] is None:
                project["label"] = labels.project(item["thread_id"])
        project["conversations"] = conversations[:CONVERSATIONS_LIMIT]
        project["more"] = max(0, len(conversations) - CONVERSATIONS_LIMIT)
        shown.append(project)
    shown.sort(key=lambda item: (-(item["input"] + item["output"]), -(item["lifetime"] or 0), item["key"] or "~"))
    total = _numbers()
    lifetime = None
    for project in shown:
        for name in NUMBERS:
            total[name] += project[name]
        if project["lifetime"] is not None:
            lifetime = (lifetime or 0) + project["lifetime"]
    total["lifetime"] = lifetime
    return {"route": way, "measured": verdict, "projects": shown[:PROJECTS_LIMIT],
            "more": max(0, len(shown) - PROJECTS_LIMIT), "total": total, "homes": homes}


def _paces(runtime, now) -> list:
    """Each five-hour and weekly window the meter last read, with its pace."""
    try:
        rows = runtime.state.meter()
        samples = runtime.state.usage_samples(now - 3600)
    except Exception:
        return []
    found = [pace(samples, row, now) for row in rows.values() if row.get("minutes") in WINDOWS]
    return sorted(found, key=lambda item: (item["minutes"], item["bucket"] or ""))


def _behind(runtime, homes, now) -> bool:
    """Whether more is left to read than one pass reads: older conversations still being read."""
    try:
        known = runtime.state.token_files()
        left = 0
        for rollout in tokens.rollouts(homes, now):
            row = known.get(rollout.key)
            left += rollout.size - (row["offset"] if row is not None and row.get("thread_id") else 0)
            if left > tokens.PASS_BYTES:
                return True
    except Exception:
        return False
    return False


def view(runtime, days=None) -> dict:
    """advanced-analytics: the card's numbers - the pace of each window, the tokens of each project and its
    conversations over the last `days`, the route, when the last pass ran and whether older conversations are still
    being read."""
    days = _days(runtime, days)
    if days is None:
        return _refused(Refusal.INVALID_REQUEST)
    if not _standing(runtime):
        return _refused(Refusal.NOT_ON)
    now = runtime.clock()
    try:
        found = aggregate(runtime, days, now=now)
        last = runtime.state.stamped(CAPABILITY, OptionKey.LAST_INGEST)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE)
    homes = found.pop("homes")
    return dict(found, done=True, refusal=None, days=days, choices=list(DAYS), paces=_paces(runtime, now),
                last_ingest=last, behind=found["route"] == "per_day" and _behind(runtime, homes, now))


# ------------------------------------------------------------------------- the CSV
def _cell(label) -> str:
    text = label if isinstance(label, str) else ""
    return "'" + text if text.startswith(FORMULA) else text


def rows_of(runtime, days, *, now=None) -> list:
    """The CSV's rows after its header: one a local day and project, oldest first, then one a project of lifetime
    totals. Labels as the card shows them; a project with none is left blank."""
    now = runtime.clock() if now is None else now
    found = aggregate(runtime, days, now=now)
    label = {project["key"]: project["label"] for project in found["projects"]}
    per_day = {}
    if found["route"] == "per_day":
        for row in runtime.state.token_days(first_day(now, days)):
            numbers = per_day.setdefault((row["day"], row["project_digest"]), _numbers())
            for name in NUMBERS:
                numbers[name] += row[name]
    lines = [[day, _cell(label.get(key))] + [numbers[name] for name in NUMBERS] + [""]
             for (day, key), numbers in sorted(per_day.items(), key=lambda item: (item[0][0], item[0][1] or "~"))]
    for project in found["projects"]:
        if project["lifetime"] is not None:
            lines.append(["", _cell(project["label"])] + [""] * len(NUMBERS) + [project["lifetime"]])
    return lines


def save_csv(runtime, argument) -> dict:
    """advanced-analytics-csv: the numbers written as CSV at the path the person chose, and nowhere else."""
    days = _days(runtime, argument.get("days"))
    path, replace = argument.get("path"), argument.get("replace", False)
    if days is None or type(replace) is not bool:
        return _refused(Refusal.INVALID_REQUEST)
    if not isinstance(path, str) or not path or "\x00" in path or not Path(path).is_absolute():
        return {"done": False, "refusal": ReportRefusal.SAVE_FAILED}
    if not _standing(runtime):
        return _refused(Refusal.NOT_ON)
    try:
        lines = rows_of(runtime, days)
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    writer.writerows(lines)
    try:
        with open(path, "w" if replace else "x", encoding="utf-8-sig", newline="") as handle:
            handle.write(buffer.getvalue())
    except FileExistsError:
        return {"done": False, "refusal": ReportRefusal.FILE_EXISTS}
    except OSError:
        return {"done": False, "refusal": ReportRefusal.SAVE_FAILED}
    return {"done": True, "refusal": None, "rows": len(lines)}

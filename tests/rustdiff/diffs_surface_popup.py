"""S6.0, car-surface: ui/popup/model.py (the v0.6.26 final's), the words it reads, and ui/tray/model.py and stored.py.

* WordsDiff - `say`, `one_line`, `locale_of`, `kept` and `vocabulary` over every catalog and the odd vocabularies.
* HeaderDiff - `activity`, `light_for`, `icon_attention`, `watcher_known_running`, `snapshot_activity`, `urgency`,
  `is_waiting` and `_blocked` over generated statuses, rows and tick snapshots: a watcher running, stopped, not known,
  not ticking, on an engine that is not supported or failed here, blocked by its own judge (v0.6.26), an upgrade
  pending, every overlay, held rows, rows in Codex, rows due, the status's own counts; and the wrong types.
* ViewDiff - `task_item`, `row_menu` and `view_model` in all 22 languages over the picture inputs' rows (the
  Dashboard sample's, build/make_screenshots.py `popup_rows`/`popup_status`, rebuilt here) and generated ones: a reset
  waited for, a retry, offline, held, the app's server unmatched, Codex changed, paused, switched off, postponed,
  words for this time, long and right-to-left names; the usage line, the share LEFT (the owner's rule for a glance
  surface), from the watcher's reading or the advanced meter's newer one (`newest`, v0.6.26 final).
* ModelDiff - `PopupModel` over scripted reads, clicks, answers and refusals (stale rows, failed calls, busy
  switches), its row menus, the icon's attention while it is open (`tray.popup_attention`); `perform` over every
  action against a recording control layer and Dashboard; `select_action`; `busy_key`.
* TrayDiff - `snapshot_from` over stores of every shape, and `StoredMixin` over scripted settings files (a stamp
  that changes or not, a missing file, a read that fails, a control layer without the calls, Reduce motion said once).
"""
from __future__ import annotations

from rustdiff.surface import Surface, counted

RECORD: list[str] = []

ROWS = r'''
import random
from codex_auto_resume import l10n
NOW = 1_800_000_000.0
UUIDS = ["11111111-1111-7111-8111-%012d" % n for n in range(8)]
KEYS = [str(n) * 64 for n in range(1, 9)]
NAMES = ["example-project", "example-service", "example-docs", "example-app"]
rng = random.Random(1)

def strings_of(spec):
    if isinstance(spec, list) and spec[:1] == ["catalog"]:
        return l10n.catalog(spec[1])
    return spec

def picture_rows():
    """The Dashboard sample's four conversations at POPUP_NOW, as the popup's read lists them (make_screenshots'
    popup_rows): a usage limit waiting for its reset, a retry, one in Codex, one held."""
    return [{"interruption_id": KEYS[0], "thread_id": UUIDS[0], "state": "waiting_reset", "code": "waiting_reset",
             "category": "usage_limit", "eligible_at": NOW + 5400, "reset_at": NOW + 5400, "detected_at": NOW - 600,
             "overlays": [], "thread_enabled": True, "name": NAMES[0], "hold": None, "terminal": False,
             "cancel_requested": False, "tier": None, "postponed_until": None, "once_words": False, "reason": "reset"},
            {"interruption_id": KEYS[1], "thread_id": UUIDS[1], "state": "waiting_retry", "code": "scheduled",
             "category": "server_5xx", "eligible_at": NOW + 95, "reset_at": None, "detected_at": NOW - 300,
             "overlays": [], "thread_enabled": True, "name": NAMES[1], "hold": None, "terminal": False,
             "cancel_requested": False, "tier": "ask_first", "postponed_until": None, "once_words": True},
            {"interruption_id": KEYS[2], "thread_id": UUIDS[2], "state": "submitted", "code": "submitted",
             "category": "usage_limit", "eligible_at": None, "reset_at": NOW - 60, "detected_at": NOW - 7200,
             "overlays": [], "thread_enabled": True, "name": NAMES[2]},
            {"interruption_id": KEYS[3], "thread_id": UUIDS[3], "state": "waiting_reset", "code": "waiting_reset",
             "category": "usage_limit", "eligible_at": None, "reset_at": NOW + 600, "detected_at": NOW - 50,
             "overlays": ["held"], "thread_enabled": False, "name": NAMES[3], "hold": "ask", "terminal": False}]

def picture_status():
    return {"enabled": True, "watcher_running": True,
            "watcher": {"running": True, "ticking": True, "engine_state": "verified"}}

STATES = ["waiting_reset", "waiting_poll", "waiting_for_app", "waiting_retry", "waiting_backoff", "waiting_for_usage",
          "submitted", "turn_started", "submitting", "queued", "recovered", "nope"]
OVERLAYS = ["held", "app_server_unmatched", "codex_changed", "engine_unavailable", "paused", "thread_disabled",
            "compatibility_blocked", "watcher_not_ticking", "cancel_pending"]

def random_row(n):
    row = {"interruption_id": rng.choice(KEYS + [None, ""]), "thread_id": rng.choice(UUIDS + [None]),
           "state": rng.choice(STATES), "category": rng.choice(["usage_limit", "server_5xx", "terminal_auth", "unknown",
                                                                "nope", None, "rate_limit_transient"]),
           "eligible_at": rng.choice([None, NOW - 5, NOW, NOW + 0.4, NOW + 59, NOW + 3600, int(NOW) + 7, NOW + 10 ** 6]),
           "reset_at": rng.choice([None, NOW + 600, 0]), "detected_at": rng.choice([NOW - 10, NOW - 1000, None, 0]),
           "overlays": rng.sample(OVERLAYS, rng.choice([0, 0, 0, 1, 1, 2])), "name": rng.choice(
               NAMES + [None, "", "   ", "x" * 200, "\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd", 5, "a\n\tb"])}
    for key, choices in (("thread_enabled", [True, False, None, 0, 1]), ("hold", [None, "ask", "notify_only"]),
                         ("terminal", [False, True]), ("cancel_requested", [False, True, None]),
                         ("tier", [None, "automatic", "objection_window", "ask_first", "notify_only", "x"]),
                         ("postponed_until", [None, NOW + 600, NOW - 600, 0]), ("once_words", [False, True, 1]),
                         ("reason", [None, "offline", "reset"]), ("last_error", [None, "app_server_unmatched: x", "x"])):
        if rng.random() < 0.7:
            row[key] = rng.choice(choices)
    return row

def reading(at, used=42):
    return {"read_at": at, "windows": [{"bucket": "codex", "window": "primary", "used_percent": used,
                                        "window_minutes": 300, "reset_at": int(NOW) + 3600},
                                       {"bucket": "codex", "window": "secondary", "used_percent": 97.5,
                                        "window_minutes": 10080, "reset_at": int(NOW) + 86400 * 3}]}

METER = {"meter": {"read_at": NOW - 10, "windows": [{"bucket": "codex", "window_minutes": 300, "used_percent": 55,
                                                     "reset_at": int(NOW) + 3000}]}}

def random_status():
    status = {}
    for key, choices in (("enabled", [True, False, None]), ("watcher_running", [True, True, False, None]),
                         ("upgrade_pending", [None, False, True]), ("pending", [None, 0, 3]),
                         ("observe_only", [None, True, False]), ("codes", [None, {}, {"submitted": 1}, {"turn_running": 0},
                                                                            {"withdrawing": 2}])):
        if rng.random() < 0.8:
            status[key] = rng.choice(choices)
    watcher = {}
    for key, choices in (("ticking", [True, True, False, None]), ("engine_state", ["verified", "incompatible",
                                                                                   "failed_here", "unknown"]),
                         ("self_check", [None, {}, {"blocked": None}, {"blocked": "codex_changed"}]),
                         ("usage", [None, reading(NOW - 300), reading(NOW - 5, 101), {"read_at": None}])):
        if rng.random() < 0.7:
            watcher[key] = rng.choice(choices)
    if rng.random() < 0.85:
        status["watcher"] = watcher
    if rng.random() < 0.2:
        status["advanced"] = rng.choice([METER, {}, {"meter": None}])
    if rng.random() < 0.3:
        status["settings"] = rng.choice([{}, {"default_tier": "ask_first"}, {"default_tier": "x"}])
    return status
'''

WORDS = ROWS + r'''
from codex_auto_resume.ui.popup import words
cases = []
for locale in l10n.LOCALES:
    strings = ["catalog", locale]
    for key in ["tray.title", "popup.more", "no.such.key", "activity.paused", "msg.toast_unnamed"]:
        cases.append(["popup.say", strings, key, {"n": 3, "time": "1:00"}])
    for current in ("en", locale, "ar"):
        cases.append(["popup.locale_of", strings, current])
        cases.append(["popup.kept", strings, current, "2026-11-12 21:49"])
    cases.append(["popup.vocabulary", locale])
for odd in [{}, {"tray.title": ""}, {"tray.title": 5}, {"popup.more": "{n} more {n}"}, {"activity.monitoring": "x"},
            {"activity.monitoring": l10n.catalog("ko")["activity.monitoring"], "popup.nothing": l10n.catalog("ja")["popup.nothing"]}]:
    for current in ("en", "ko"):
        cases.append(["popup.locale_of", odd, current])
    cases.append(["popup.say", odd, "popup.more", {"n": "{n}"}])
    cases.append(["popup.say", odd, "tray.title", {}])
for language in ["system", "", None, 5, "xx", "ko", "zh-CN", " ko "]:
    cases.append(["popup.vocabulary", language])
for text in ["", "  a  b  ", "x" * 130, "\u3000a\u3000", "line\nbreak\ttab", 5, None, ["a"], "\U0001f600" * 125]:
    for limit in (120, 200, 1, 0):
        cases.append(["popup.one_line", text, limit])

def vocabulary(language):
    found = words.vocabulary(language)
    return {"n": len(found), "title": found.get("tray.title"), "probe": found.get("activity.monitoring")}

ops = {"popup.say": lambda strings, key, fields: words.say(strings_of(strings), key, **fields),
       "popup.locale_of": lambda strings, current: (speak(current), words.locale_of(strings_of(strings)))[1],
       "popup.kept": lambda strings, current, value: (speak(current), words.kept(strings_of(strings))(value))[1],
       "popup.vocabulary": vocabulary, "popup.one_line": words.one_line}
finish(cases, ops)
'''

HEADER = ROWS + r'''
from codex_auto_resume.ui.popup import model
cases = []
for _ in range(1500):
    status = random_status() if rng.random() < 0.9 else rng.choice([None, {}, "x", []])
    rows = None if rng.random() < 0.1 else [random_row(n) for n in range(rng.randint(0, 5))]
    now = rng.choice([NOW, int(NOW), NOW + 100])
    cases.append(["popup.activity", status, rows, now])
    cases.append(["popup.light", status, rng.choice(model.STATES), rows])
    cases.append(["popup.icon_attention", status, rows])
    cases.append(["popup.known_running", status, rows])
for _ in range(400):
    snapshot = {key: rng.choice(choices) for key, choices in (
        ("enabled", [True, False, None, 0]), ("held", [0, 1]), ("unconfirmed", [0, 2, None]), ("unmatched", [0, 1]),
        ("blocked", [None, True]), ("running", [0, 1, 3]), ("waiting", [0, 2]),
        ("next_at", [None, NOW - 1, NOW, NOW + 1, int(NOW)])) if rng.random() < 0.6}
    cases.append(["popup.snapshot_activity", snapshot, NOW, rng.random() < 0.1])
cases += [["popup.snapshot_activity", None, NOW, False], ["popup.snapshot_activity", {}, NOW, False],
          ["popup.snapshot_activity", "x", NOW, False], ["popup.snapshot_activity", {"waiting": 1, "next_at": "x"}, NOW,
                                                         False]]
for _ in range(300):
    row = random_row(0)
    cases.append(["popup.urgency", row])
    cases.append(["popup.is_waiting", row])
for odd in [{"state": []}, {}, "x", {"eligible_at": "x", "state": "waiting_reset"}, {"overlays": "held"},
            {"overlays": ["held", []]}, {"overlays": {"held": 1}}, {"overlays": 5}]:
    cases += [["popup.urgency", odd], ["popup.is_waiting", odd],
              ["popup.activity", picture_status(), [odd], NOW], ["popup.icon_attention", picture_status(), [odd]]]
for watcher in [None, {}, {"self_check": None}, {"self_check": {}}, {"self_check": {"blocked": None}},
                {"self_check": {"blocked": "x"}}, {"self_check": {"blocked": False}}, {"self_check": "x"}, "x"]:
    cases.append(["popup.blocked", watcher])
cases.append(["popup.activity", {"watcher_running": True, "watcher": "x"}, [], NOW])
cases.append(["popup.activity", {"watcher_running": True, "watcher": {"ticking": True}, "enabled": True, "codes": "x"},
              [], NOW])
cases.append(["popup.activity", {"watcher_running": True, "enabled": True, "codes": {"submitted": "x"}}, [], NOW])

ops = {"popup.activity": model.activity, "popup.light": model.light_for, "popup.icon_attention": model.icon_attention,
       "popup.known_running": model.watcher_known_running,
       "popup.snapshot_activity": lambda snapshot, now, attention: model.snapshot_activity(snapshot, now,
                                                                                            attention=attention),
       "popup.urgency": model.urgency, "popup.is_waiting": model.is_waiting, "popup.blocked": model._blocked}
finish(cases, ops)
'''

VIEW = ROWS + r'''
from codex_auto_resume.ui.popup import model, words
from codex_auto_resume.domain import usage
cases = []
for locale in l10n.LOCALES:
    strings = ["catalog", locale]
    cases.append(["popup.view_model", picture_rows(), picture_status(), strings, NOW, None, None, locale])
    cases.append(["popup.view_model", picture_rows(), dict(picture_status(), watcher=dict(
        picture_status()["watcher"], usage=reading(NOW - 300)), advanced=METER), strings, NOW, "notice", None, locale])
    cases.append(["popup.view_model", None, None, strings, NOW, None, "error", locale])
    cases.append(["popup.view_model", [], {"enabled": False, "watcher_running": False}, strings, NOW, None, None, locale])
    for row in picture_rows():
        cases.append(["popup.task", row, strings, NOW, locale])
    for _ in range(25):
        cases.append(["popup.task", random_row(0), strings, NOW, locale])
        rows = [random_row(n) for n in range(rng.randint(0, 6))]
        cases.append(["popup.view_model", rows, random_status(), strings, rng.choice([NOW, NOW + 400]), None, None,
                      locale])
    for task in [model.task_item(row, l10n.catalog(locale), NOW) for row in picture_rows()] + [
            {"interruption_id": None, "thread_id": UUIDS[0]}, {"interruption_id": KEYS[0], "thread_id": UUIDS[0],
                                                               "waiting": True, "postponed": True, "held": True,
                                                               "tier": "notify_only", "once_words": True}]:
        for default in (None, "ask_first", "x", []):
            cases.append(["popup.row_menu", task, strings, default])
for odd in [{"category": []}, {"state": "waiting_reset", "eligible_at": "x"}, {"state": "waiting_reset",
            "postponed_until": "x"}, "x", {"state": "waiting_reset", "overlays": [[]]}]:
    cases.append(["popup.task", odd, ["catalog", "en"], NOW, "en"])
    cases.append(["popup.view_model", [odd], picture_status(), ["catalog", "en"], NOW, None, None, "en"])
cases.append(["popup.view_model", [{"eligible_at": "x", "state": "waiting_reset"}, {"eligible_at": 5.0,
              "state": "waiting_reset"}], picture_status(), ["catalog", "en"], NOW, None, None, "en"])
cases.append(["popup.view_model", picture_rows(), "x", ["catalog", "en"], NOW, None, None, "en"])
for reading_value in [None, reading(NOW - 300), {"read_at": NOW, "windows": []}, "x"]:
    for added in [None, METER, {"meter": {"read_at": NOW - 1000, "windows": []}}, {"meter": {"read_at": True,
                  "windows": []}}, {"meter": {"read_at": NOW, "windows": [{"bucket": "codex", "window_minutes": 60,
                  "used_percent": 5, "reset_at": None}, {"bucket": "codex", "window_minutes": 300, "used_percent": 7,
                  "reset_at": None}]}}, {"meter": {"read_at": NOW, "windows": ["x"]}}, "x",
                  {"meter": {"read_at": NOW, "windows": [{"bucket": [], "window_minutes": 60}]}}]:
        cases.append(["popup.newest", reading_value, added])

ops = {"popup.task": lambda row, strings, now, current: (speak(current), model.task_item(row, strings_of(strings), now))[1],
       "popup.row_menu": lambda task, strings, default: model.row_menu(task, strings_of(strings), default),
       "popup.view_model": lambda rows, status, strings, now, notice, error, current: (speak(current), model.view_model(
           rows, status, strings_of(strings), now, notice=notice, error=error))[1],
       "popup.newest": usage.newest}
finish(cases, ops)
'''

MODEL = ROWS + r'''
from codex_auto_resume.ui.popup import model
from codex_auto_resume.ui.tray import model as tray_model
import copy, types, json as _json
ACTIONS = [["read"], ["recovery", KEYS[0], UUIDS[0], False], ["recovery", KEYS[0], UUIDS[0]], ["enabled", True],
           ["enabled"], ["postpone", KEYS[0], UUIDS[0], "1_hour"], ["unpostpone", KEYS[0], UUIDS[0]],
           ["release", KEYS[0], UUIDS[0]], ["tier", KEYS[0], UUIDS[0], "ask_first"], ["project", KEYS[0], UUIDS[0], True],
           ["unsay", KEYS[0], UUIDS[0]], ["dashboard"], ["dashboard_row", "message", KEYS[0], UUIDS[0]],
           ["dashboard_row", "nope", KEYS[0], UUIDS[0]], ["dashboard_row", "once_words", KEYS[0]], ["nope"], []]
ANSWERS = [{"enabled": True}, {"enabled": False}, [["enabled", True]], None, "ab", {"raise": "ControlError",
           "code": "thread_mismatch"}, {"raise": "ControlError", "code": "already_finished"},
           {"raise": "ControlError", "code": "nope"}, {"raise": "RuntimeError"}, {"raise": "ControlError", "code": ""}]

class Control:
    def __init__(self, spec, calls):
        self.spec, self.calls = spec, calls
    def _answer(self, name, *args):
        self.calls.append([name] + list(args))
        return answer(self.spec.get(name, {"ok": True}))
    def list_pending(self, source=None):
        return self._answer("list_pending", source)
    def get_status(self):
        return self._answer("get_status")
    def set_enabled(self, enabled):
        return self._answer("set_enabled", enabled)
    def set_interruption_recovery(self, interruption_id, thread_id, enabled):
        return self._answer("set_interruption_recovery", interruption_id, thread_id, enabled)
    def postpone(self, interruption_id, thread_id, preset=None):
        return self._answer("postpone", interruption_id, thread_id, preset)
    def unpostpone(self, interruption_id, thread_id):
        return self._answer("unpostpone", interruption_id, thread_id)
    def release_hold(self, interruption_id, thread_id):
        return self._answer("release_hold", interruption_id, thread_id)
    def set_thread_tier(self, thread_id, tier, interruption_id=None):
        return self._answer("set_thread_tier", thread_id, tier, interruption_id)
    def set_project_rule(self, interruption_id, thread_id, always, source=None):
        return self._answer("set_project_rule", interruption_id, thread_id, always, source)
    def set_once_words(self, interruption_id, thread_id, words):
        return self._answer("set_once_words", interruption_id, thread_id, words)

def perform(action, spec, source, dashboard):
    calls = []
    def opener(row=None):
        calls.append(["dashboard", None if row is None else list(row)])
        return answer(dashboard)
    found = model.perform(action, Control(spec, calls), source=source, dashboard=None if dashboard is None else opener)
    return {"result": list(found), "calls": calls}

cases = []
for action in ACTIONS:
    for answered in ANSWERS:
        spec = {name: answered for name in model.CONTROL_CALLS}
        spec["list_pending"] = picture_rows() if answered == {"enabled": True} else answered
        for dashboard in (None, True, 0, {"raise": "OSError"}):
            cases.append(["popup.perform", action, spec, None, dashboard])
        cases.append(["popup.perform", action, spec, "source-x", True])
for action in ACTIONS + [["recovery", [1]], ["row"]]:
    cases.append(["popup.busy_key", action])
for visible in (True, False):
    for keyboard in (True, False):
        for hidden, double, previous in [(None, None, None), (NOW - 0.2, None, None), (NOW - 0.6, None, None),
                                         (None, NOW - 0.5, None), (None, NOW - 0.7, None), (None, None, NOW - 0.1),
                                         (None, None, NOW - 0.31), (NOW + 1, NOW + 1, NOW + 1), (NOW, NOW, NOW)]:
            cases.append(["popup.select", visible, NOW, hidden, double, previous, keyboard])

def state(m):
    # A copy: the model changes its rows in place later, and the answer is what they were now.
    return copy.deepcopy({"rows": m.rows, "status": m.status, "read_failed": m.read_failed, "notice_key": m.notice_key,
            "notice_until": float(m.notice_until), "busy": sorted(_json.dumps(list(each)) for each in m.busy),
            "drawn_paused": m.drawn_paused, "wants_read": m.wants_read})

def script(strings, current, steps):
    speak(current)
    m, out = model.PopupModel(strings_of(strings)), []
    for step in steps:
        kind = step[0]
        try:
            if kind == "view":
                out.append({"ok": m.view(step[1])})
            elif kind == "apply":
                out.append({"ok": m.apply_outcome(tuple(step[1]), tuple(step[2]), step[3])})
            elif kind == "begin":
                out.append({"ok": m.begin(tuple(step[1]))})
            elif kind == "action_for":
                found = m.action_for(tuple(step[1]))
                out.append({"ok": None if found is None else list(found)})
            elif kind == "menu_for":
                out.append({"ok": m.menu_for(step[1])})
            elif kind == "attention":
                out.append({"ok": m.attention()})
            elif kind == "popup_attention":
                popup = None if step[1] is None else types.SimpleNamespace(visible=step[1], attention=m.attention)
                out.append({"ok": tray_model.popup_attention(popup)})
            else:
                out.append({"ok": state(m)})
        except Exception as error:
            out.append({"error": type(error).__name__})
    return out

def random_steps():
    steps, drawn = [], []
    for _ in range(rng.randint(2, 25)):
        kind = rng.choice(["read", "read", "view", "view", "click", "toggle", "apply", "begin", "menu", "attention",
                           "popup", "state", "fail"])
        now = NOW + rng.choice([0, 1, 3.9, 4, 10])
        if kind == "read":
            rows = picture_rows() if rng.random() < 0.5 else [random_row(n) for n in range(rng.randint(0, 5))]
            steps.append(["apply", ["read"], ["ok", {"rows": rows, "status": random_status()}], now])
        elif kind == "fail":
            steps.append(["apply", ["read"], ["failed", "OSError"], now])
        elif kind == "view":
            steps.append(["view", now])
        elif kind == "click":
            steps.append(["action_for", ["check", rng.choice(KEYS[:4] + [None])]])
        elif kind == "toggle":
            steps.append(["action_for", [rng.choice(["toggle", "dashboard", "nope"])]])
        elif kind == "apply":
            action = rng.choice(ACTIONS[1:12])
            outcome = rng.choice([["ok", {"enabled": rng.choice([True, False])}], ["refused", "thread_mismatch"],
                                  ["refused", "no_such_interruption"], ["refused", "other"], ["failed", "OSError"],
                                  ["ok"]])
            steps.append(["apply", action, outcome, now])
        elif kind == "begin":
            steps.append(["begin", rng.choice(ACTIONS)])
        elif kind == "menu":
            steps.append(["menu_for", rng.choice(KEYS[:4] + [None, []])])
        elif kind == "attention":
            steps.append(["attention"])
        elif kind == "popup":
            steps.append(["popup_attention", rng.choice([True, False, None, 1])])
        else:
            steps.append(["state"])
    return steps

for locale in l10n.LOCALES:
    cases.append(["popup.model", ["catalog", locale], locale, [
        ["view", NOW], ["apply", ["read"], ["ok", {"rows": picture_rows(), "status": picture_status()}], NOW],
        ["view", NOW], ["action_for", ["check", KEYS[0]]], ["begin", ["recovery", KEYS[0], UUIDS[0], False]],
        ["view", NOW], ["apply", ["recovery", KEYS[0], UUIDS[0], False], ["refused", "thread_mismatch"], NOW],
        ["view", NOW + 1], ["view", NOW + 5], ["menu_for", KEYS[1]], ["action_for", ["toggle"]], ["attention"],
        ["popup_attention", True], ["state"]]])
for _ in range(500):
    cases.append(["popup.model", ["catalog", rng.choice(l10n.LOCALES)], "en", random_steps()])
cases.append(["popup.model", {}, "en", [["view", NOW], ["apply", ["read"], ["ok", {"rows": "x", "status": {}}], NOW],
                                         ["apply", ["read"], ["ok", {"rows": [], "status": None}], NOW], ["state"],
                                         ["apply", ["read"], ["ok", []], NOW], ["apply", [], ["ok"], NOW],
                                         ["apply", ["read"], [], NOW], ["action_for", []],
                                         ["apply", ["recovery", KEYS[0]], ["ok", {"enabled": True}], NOW],
                                         ["begin", ["recovery", [1]]], ["action_for", ["check", [1]]]]])

ops = {"popup.perform": perform, "popup.busy_key": lambda action: (lambda key: None if key is None else list(key))(
           model.busy_key(tuple(action))),
       "popup.select": lambda visible, now, hidden, double, previous, keyboard: model.select_action(
           visible, now, hidden_at=hidden, double_click_at=double, previous_key_at=previous, keyboard=keyboard),
       "popup.model": script}
finish(cases, ops)
'''

TRAY = ROWS + r'''
import copy, types
from codex_auto_resume.ui.tray import model as tray_model, stored
from codex_auto_resume.ui import popup as tray_popup

class Store:
    def __init__(self, spec):
        self.spec = spec
    def pending(self):
        return answer(self.spec["pending"])
    def disabled_threads(self):
        return frozenset(answer(self.spec["disabled"]))
    def settings(self):
        return answer(self.spec["settings"])
    def failure_marks(self):
        return answer(self.spec["marks"])

cases = []
for _ in range(500):
    rows = [random_row(n) for n in range(rng.randint(0, 7))]
    for row in rows:
        if rng.random() < 0.5:
            row["state"] = rng.choice(["waiting_reset", "waiting_retry", "submitted"])
    spec = {"pending": rows, "disabled": rng.choice([[], UUIDS[:2], UUIDS]),
            "settings": rng.choice([{"enabled": True}, {"enabled": False}, {"enabled": None}]),
            "marks": rng.choice([None, {"failed_at": NOW - 5, "recovering_at": None}, []])}
    cases.append(["tray.snapshot", spec])
for odd in [{"pending": {"raise": "OSError"}, "disabled": [], "settings": {"enabled": True}, "marks": None},
            {"pending": [{"thread_id": UUIDS[0]}], "disabled": [], "settings": {"enabled": True}, "marks": None},
            {"pending": [{"state": []}], "disabled": [], "settings": {"enabled": True}, "marks": None},
            {"pending": [], "disabled": [], "settings": {}, "marks": None},
            {"pending": [], "disabled": [], "settings": {"enabled": True}, "marks": {"raise": "OSError"}},
            {"pending": [{"state": "waiting_reset", "last_error": "app_server_unmatched"}], "disabled": [],
             "settings": {"enabled": True}, "marks": None},
            {"pending": [{"state": "waiting_reset", "last_error": "app_server_unmatched", "thread_id": UUIDS[0]}],
             "disabled": {"raise": "OSError"}, "settings": {"enabled": True}, "marks": None},
            {"pending": ["x"], "disabled": [], "settings": {"enabled": True}, "marks": None},
            {"pending": [{"state": "waiting_reset", "next_retry_at": "x", "reset_at": 5}], "disabled": [],
             "settings": {"enabled": True}, "marks": None}]:
    cases.append(["tray.snapshot", odd])

def snapshot(spec):
    return tray_model.snapshot_from(Store(spec), NOW)

class Icon(stored.StoredMixin):
    def __init__(self, control, strings, record):
        import threading
        self.control, self.strings, self.record = control, strings, record
        self._settings_stamp, self._settings_values, self._motion_read_failed = None, None, False
        self._lock = threading.Lock()
    def set_strings(self, strings):
        self.strings = strings
        self.record.append(["set_strings", strings.get("tray.title"), len(strings)])
    def log(self, line):
        self.record.append(["log", line])

def icon_script(strings, steps):
    record, out = [], []
    control = types.SimpleNamespace()
    stamps = {"value": None}
    def stat(path):
        record.append(["stat", path])
        return types.SimpleNamespace(st_mtime_ns=stamps["value"][0], st_size=stamps["value"][1]) \
            if isinstance(stamps["value"], list) else answer(stamps["value"])
    stored.os = types.SimpleNamespace(stat=stat)
    adopt = {"spec": None}
    def adopt_settings(values):
        record.append(["adopt_settings", values])
        answer(adopt["spec"])
    tray_popup.adopt_settings = adopt_settings
    motion = types.SimpleNamespace(set_reduce_motion=lambda value: record.append(["reduce_motion", value]))
    icon = Icon(control, strings_of(strings), record)
    for step in steps:
        kind = step[0]
        if kind == "control":
            spec = step[1]
            icon.control = control = types.SimpleNamespace()
            if "settings" in spec:
                control.get_settings = (lambda value: lambda: (record.append(["get_settings"]), answer(value))[1])(
                    spec["settings"])
            if "path" in spec:
                control.settings_path = (lambda value: lambda: answer(value))(spec["path"])
            out.append(None)
        elif kind == "stamp":
            stamps["value"] = step[1]
            out.append(None)
        elif kind == "adopt_raises":
            adopt["spec"] = step[1]
            out.append(None)
        elif kind == "stored":
            try:
                out.append({"ok": icon._stored_settings()})
            except Exception as error:
                out.append({"error": type(error).__name__})
        elif kind == "adopt":
            out.append(icon._adopt_settings())
        elif kind == "motion":
            out.append(icon._adopt_reduce_motion(motion))
        else:
            out.append(copy.deepcopy({"stamp": None if icon._settings_stamp is None else list(icon._settings_stamp),
                                      "values": icon._settings_values, "failed": icon._motion_read_failed}))
    return {"out": out, "record": record}

SETTINGS = [{"interface_language": "ko", "reduce_motion": True}, {"interface_language": "system"},
            {"interface_language": "xx", "reduce_motion": "x"}, [["interface_language", "de"]], None, "ab",
            {"raise": "OSError"}, {"raise": "ValueError"}]
for _ in range(400):
    steps = [["control", {"settings": rng.choice(SETTINGS), "path": rng.choice(["C:/x/settings.json", None,
                                                                               {"raise": "OSError"},
                                                                               {"raise": "RuntimeError"}])}]]
    for _ in range(rng.randint(1, 14)):
        kind = rng.choice(["stamp", "stamp", "stored", "adopt", "adopt", "motion", "motion", "state", "control",
                           "adopt_raises"])
        if kind == "stamp":
            steps.append(["stamp", rng.choice([[100, 5], [100, 5], [200, 5], [100, 6], {"raise": "FileNotFoundError"},
                                               {"raise": "PermissionError"}, {"raise": "TypeError"}])])
        elif kind == "control":
            spec = {}
            if rng.random() < 0.8:
                spec["settings"] = rng.choice(SETTINGS)
            if rng.random() < 0.7:
                spec["path"] = rng.choice(["C:/x/settings.json", {"raise": "OSError"}])
            steps.append(["control", spec])
        elif kind == "adopt_raises":
            steps.append(["adopt_raises", rng.choice([None, {"raise": "RuntimeError"}])])
        else:
            steps.append([kind])
    cases.append(["tray.stored", rng.choice([["catalog", "en"], ["catalog", "ko"], {}]), steps])

ops = {"tray.snapshot": snapshot, "tray.stored": icon_script}
finish(cases, ops)
'''


class WordsDiff(Surface):
    def test_words(self):
        done = self.family(WORDS, label="popup-words")
        RECORD.append("popup words: %d say, locale_of, kept, vocabulary and one_line cases equal the tag's"
                      % len(done["cases"]))


class HeaderDiff(Surface):
    def test_header(self):
        done = self.family(HEADER, label="popup-header")
        RECORD.append("headers: %d activity, light, attention, known-running, snapshot-word, urgency and blocked cases "
                      "equal the tag's" % len(done["cases"]))


class ViewDiff(Surface):
    def test_view(self):
        done = self.family(VIEW, label="popup-view", chunk=500)
        RECORD.append("popup view: %d view_model, %d task_item, %d row_menu and %d newest cases in 22 languages equal "
                      "the tag's (the picture inputs' rows among them)" % (
                          counted(done, "popup.view_model"), counted(done, "popup.task"),
                          counted(done, "popup.row_menu"), counted(done, "popup.newest")))


class ModelDiff(Surface):
    def test_model(self):
        done = self.family(MODEL, label="popup-model", chunk=500)
        steps = sum(len(case[3]) for case in done["cases"] if case[0] == "popup.model")
        RECORD.append("popup model: %d PopupModel scripts (%d steps), %d perform, %d select and %d busy_key cases equal "
                      "the tag's" % (counted(done, "popup.model"), steps, counted(done, "popup.perform"),
                                     counted(done, "popup.select"), counted(done, "popup.busy_key")))


class TrayDiff(Surface):
    def test_tray(self):
        done = self.family(TRAY, label="tray")
        RECORD.append("tray: %d snapshot_from and %d StoredMixin scripts equal the tag's"
                      % (counted(done, "tray.snapshot"), counted(done, "tray.stored")))

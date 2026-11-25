"""S6.0, car-surface: notifier.py - one notification built once, shown one way, ended once; and a card's buttons.

* BuildDiff - `build` for every notice kind (an interruption detected or held or in its objection window, a
  continuation starting, each result, a stop and a stop that is no stop, needs-you, after a long sleep, the memory
  guard, the usage meter and its forced stop, an update offered, a restart given up, an account changed, every saved
  account at its limit, Python taken back, the five power events, and events never announced) in all 22 languages,
  with each click destination and the kinds kept on screen; the demo card; the cancel's and the power stop's notices
  afterwards; Open Codex; the click's destination, page and URI; the toast's buttons; `sounds`; `STATUS`.
* RouteDiff - `deliver` (the card's setting, no host, a host that is or is not woken, the presence answers of every
  kind, a probe that raises, a notice with its own sound, the toast's answer), `complete` (seen, not seen, the demo),
  `show_demo`, and `told` (the place in Pending, a store that raises, categories of every kind).
* ActivateDiff - `activate` over every URI a button can carry and the malformed ones: the Codex app's link, the chat,
  a page with a Dashboard or without, a power stop, a cancel the control layer answers, refuses with a code (an
  identifier or not) or breaks on, a cancel of a finished recovery; the word, every log line and every announced
  notice compared.
"""
from __future__ import annotations

from rustdiff.surface import Surface, counted

RECORD: list[str] = []

SETUP = r'''
from codex_auto_resume import l10n, notifier, notify, failures
from codex_auto_resume.notice_inbox import Inbox
UUID = "019a1b2c-3d4e-7f80-9a0b-1c2d3e4f5a6b"
KEY = "1" * 64
NONCE = "0123456789abcdef"
T = 1_800_000_000
DETAILS = {
    "interruption": [{"thread_id": UUID, "interruption_id": KEY, "reset_at": T, "category": "usage_limit"},
                     {"thread_id": UUID, "interruption_id": KEY, "reset_at": None, "category": "server_5xx"},
                     {"thread_id": UUID, "interruption_id": KEY, "reset_at": T, "category": None, "hold": "ask"},
                     {"thread_id": UUID, "interruption_id": KEY, "category": "terminal_auth", "hold": "context_cost"},
                     {"thread_id": None, "interruption_id": None}, {}, "notadict",
                     {"thread_id": UUID, "interruption_id": KEY, "category": []}],
    "objection": [{"thread_id": UUID, "interruption_id": KEY, "until": T + 120, "category": "usage_limit"},
                  {"thread_id": UUID, "interruption_id": KEY, "until": T + 0.5, "category": "rate_limit_transient"},
                  {"thread_id": UUID, "interruption_id": KEY, "until": "x"}],
    "starting": [{"thread_id": UUID}, {"thread_id": UUID, "task_changed": True}, {"thread_id": UUID, "task_changed": 1}],
    "result": [{"thread_id": UUID, "state": "turn_started"}, {"thread_id": UUID, "state": "resumed"},
               {"thread_id": UUID, "state": "submission_unknown"}, {"thread_id": UUID, "state": "failed"}, {}],
    "needs_you": [{"thread_id": UUID, "category": "terminal_auth"}, {"thread_id": UUID, "category": "stalled_turn",
                                                                       "minutes": 25},
                  {"thread_id": UUID, "category": None}, {"thread_id": UUID, "category": "terminal_policy", "minutes": 0}],
    "after_sleep": [{"slept": 7300, "count": 2}, {"slept": None, "count": None}, {}],
    "memory_warning": [{"used": 600, "limit": 512}, {}],
    "memory_stopped": [{"used": 900.5, "limit": "512"}],
    "near_limit": [{"minutes": 300, "percent": 92, "reset_at": T + 3600}, {"minutes": 10080, "percent": 99.6},
                   {"minutes": None, "percent": None}, {"kind": "not_stopped"}, {"kind": "press_resume"},
                   {"kind": "not_continued"}, {"kind": "x", "minutes": 1440, "percent": 50, "reset_at": T + 0.5}],
    "update_offered": [{"version": "0.6.27"}, {"version": "0.6.27-beta.2", "prerelease": True},
                       {"version": "bad"}, {"version": "0.6.27", "prerelease": 1}],
    "restart_gave_up": [{}],
    "account_changed": [{"count": 3}, {"count": None}, {"count": "x"}],
    "accounts_exhausted": [{}, {"why": "not_finished"}, {"why": "x"}],
    "python_returned": [{"content": {"title": "Python", "body": "back", "extra": ["e"],
                                     "more": [["Open", "codex-auto-resume:open?page=diagnostics"]]}},
                        {"content": {"title": "t", "body": "b"}}, {"content": {"body": "b"}}, {"content": None}, {},
                        {"content": {"title": "t", "body": "b", "extra": "xy", "more": {"ab": 1}}},
                        {"content": {"title": 5, "body": None, "button": "B", "uri": "codex-auto-resume:open?page=history"}}],
    "power_grace": [{"action": "hibernate", "until": T + 300, "nonce": NONCE, "tasks": True},
                    {"action": "x", "until": T, "nonce": None}],
    "power_now": [{"action": "shut_down"}, {}],
    "power_failed": [{}],
    "power_not_met": [{"tasks": True}, {}],
    "power_stopped": [{}],
    "stopped": [{"thread_id": UUID, "state": "no_progress_exhausted"}, {"thread_id": UUID, "reason": "chain_time_cap"},
                {"thread_id": UUID, "state": "retry_budget_exhausted"}, {"thread_id": UUID},
                {"thread_id": UUID, "reason": "parent_handed_over", "category": "usage_limit"},
                {"thread_id": UUID, "reason": "parent_cancelled"}, {"thread_id": UUID, "reason": []}],
    "nope": [{}],
}
IDENTITIES = [None, {"name": "example-project", "project": "example-service"}, {"cwd_basename": "docs"}]
STAYS = [[], ["interruption", "needs_you", "power", "memory", "failed"], ["stopped", "cancelled", "after_sleep"]]
DESTINATIONS = ["page", "chat", "codex", "x"]

def built(locale, event, detail, identity, sound=False, destination="page", stay=()):
    speak(locale)
    return notifier.build(event, detail, identity, sound=sound, destination=destination, stay=stay)
'''

BUILD = SETUP + r'''
cases = []
for locale in l10n.LOCALES:
    for event, details in DETAILS.items():
        for index, detail in enumerate(details):
            identity = IDENTITIES[index % len(IDENTITIES)]
            cases.append(["notifier.build", locale, event, detail, identity, False, "page", []])
    for event in ("interruption", "needs_you", "stopped", "result"):
        cases.append(["notifier.build", locale, event, DETAILS[event][0], None, True, "page", STAYS[1]])
    cases.append(["notifier.demo", locale, T])
    cases.append(["notifier.cancelled", locale, UUID, STAYS[2]])
    cases.append(["notifier.power_stopped", locale, ["power"]])
for event in ("interruption", "objection", "needs_you", "stopped", "power_grace", "after_sleep", "result"):
    for destination in DESTINATIONS:
        for stay in STAYS + ["interruption", None]:
            for thread in (UUID, "not-a-uuid"):
                detail = dict(DETAILS[event][0], thread_id=thread)
                cases.append(["notifier.build", "en", event, detail, None, False, destination, stay])
cases.append(["notifier.build", "en", "interruption", DETAILS["interruption"][0], None, False, "page", 5])
cases.append(["notifier.build", None, "interruption", DETAILS["interruption"][0], None, False, "page", []])
for event in ("interruption", "objection", "stopped", "needs_you", "power_grace", "starting"):
    for destination in DESTINATIONS:
        for thread in (UUID, None, "x"):
            for on in (True, False, 1):
                detail = dict(DETAILS[event][0], thread_id=thread)
                cases.append(["notifier.open_codex", "en", event, detail, destination, on])
for values in [None, {}, {"notice_click": "chat"}, {"notice_click": "codex"}, {"notice_click": "x"},
               {"notice_click": []}, "notadict", {"notice_click": "page"}]:
    for chat in (True, False, 1, None):
        cases.append(["notifier.click_destination", values, chat])
actions = [[], [["Open", "codex-auto-resume:open?page=history"]], [["Stop", "codex-auto-resume:cancel?i=" + KEY]],
           [["A", "x"], ["B", "codex-auto-resume:open?page=settings"]], [["A", "codex-auto-resume:open?page=nope"]]]
for kind in ["starting", "resumed", "failed", "unknown", "stopped", "cancelled", "power_stopped", "interruption", "x"]:
    for listed in actions:
        cases.append(["notifier.notice_page", kind, listed])
        for key in (UUID, None, "x"):
            for destination in DESTINATIONS:
                cases.append(["notifier.click_uri", kind, listed, key, destination])
for content in [{}, {"button": "b", "uri": "u"}, {"button": "", "uri": "u"}, {"more": [["a", "b"]] * 7, "button": "x",
                "uri": "y"}, {"more": None}, {"more": [["a", ""], ["", "b"], [0, 1]]}, {"more": ["ab"]}, {"more": [1]}]:
    cases.append(["notifier.toast_actions", content])
cases.append(["notifier.statuses"])
for event in ("needs_you", "interruption"):
    for sound in (True, False):
        cases.append(["notifier.sounds", "en", event, DETAILS[event][0], sound])

ops = {
    "notifier.build": lambda locale, event, detail, identity, sound, destination, stay: notice_out(
        built(locale, event, detail, identity, sound, destination, stay)),
    "notifier.demo": lambda locale, now: (speak(locale), notice_out(notifier.build_demo(now)))[1],
    "notifier.cancelled": lambda locale, thread, stay: (speak(locale), notice_out(notifier.build_cancelled(thread, stay)))[1],
    "notifier.power_stopped": lambda locale, stay: (speak(locale), notice_out(notifier.build_power_stopped(stay)))[1],
    "notifier.open_codex": lambda locale, event, detail, destination, on: notice_out(notifier.with_open_codex(
        built(locale, event, detail, None, False, destination), on)),
    "notifier.click_destination": notifier.click_destination,
    "notifier.notice_page": lambda kind, listed: notifier.notice_page(kind, [tuple(each) for each in listed]),
    "notifier.click_uri": lambda kind, listed, key, destination: notifier.click_uri(
        kind, [tuple(each) for each in listed], key, destination),
    "notifier.toast_actions": notifier.toast_actions,
    "notifier.statuses": lambda: notifier.STATUS,
    "notifier.sounds": lambda locale, event, detail, sound: notifier.sounds(built(locale, event, detail, None, sound)),
}
finish(cases, ops)
'''

ROUTE = SETUP + r'''
import itertools
ANSWERS = [{"notification_state": 5, "notification_mode": 0, "app_notifications": 0, "screen_reader": False,
            "remote_session": False, "session_locked": False},
           {"notification_state": 2, "notification_mode": 0, "app_notifications": 0, "screen_reader": False,
            "remote_session": False, "session_locked": False},
           {"notification_state": 5, "notification_mode": 1, "app_notifications": 0, "screen_reader": False,
            "remote_session": False, "session_locked": False},
           {"notification_state": 5, "notification_mode": 0, "app_notifications": 0, "screen_reader": None,
            "remote_session": False, "session_locked": False},
           {}, None, "raise", [["notification_state", 5]], [["x"]]]
cases = []
for host, setting, answers, shown in itertools.product([None, "detached", "wakes", "asleep"], [True, False, 1],
                                                        ANSWERS, [True, False, 0, "x", "raise"]):
    cases.append(["notifier.deliver", "en", "interruption", DETAILS["interruption"][0], host, setting, answers, shown])
for event in ("needs_you", "stopped", "power_grace"):
    for host in ("wakes", "asleep"):
        cases.append(["notifier.deliver", "ko", event, DETAILS[event][0], host, True, ANSWERS[0], True])
for event in ("interruption", "demo", "needs_you"):
    for card_shown in (True, False, 1, None):
        for shown in (True, False, "raise"):
            detail = T if event == "demo" else DETAILS[event][0]
            cases.append(["notifier.complete", "ja", event, detail, card_shown, shown])
for host, setting, answers in itertools.product([None, "detached", "wakes", "asleep"], [True, False], ANSWERS):
    cases.append(["notifier.show_demo", "de", T, host, setting, answers])
pendings = [None, "raise", [], [{"interruption_id": KEY, "thread_id": UUID}],
            [{"interruption_id": "2" * 64, "thread_id": UUID}, {"interruption_id": KEY, "thread_id": UUID}],
            [{"interruption_id": "2" * 64, "thread_id": "x"}], ["notadict"], [{"thread_id": UUID}]]
for event in ("interruption", "stopped", "after_sleep", "needs_you", "power_now"):
    for pending in pendings:
        for detail in (DETAILS[event][0], {"category": "server_5xx", "thread_id": UUID}, {"category": []},
                       {"interruption_id": KEY}, "notadict", {"category": "nope"}):
            cases.append(["notifier.told", "en", event, DETAILS[event][0], detail, pending, T + 5])

def make_host(host):
    if host is None:
        return None
    box = Inbox()
    if host != "detached":
        box.attach(lambda: host == "wakes")
    return box

def recorder_show(shown, calls):
    def show(content, silent=False):
        calls.append([content, silent])
        if shown == "raise":
            raise ValueError("toast")
        return shown
    return show

def probe_of(answers):
    def probe():
        if answers == "raise":
            raise OSError("probe")
        return answers
    return probe

def deliver(locale, event, detail, host, setting, answers, shown):
    sound = event == "needs_you"
    notice = built(locale, event, detail, None, sound)
    box, calls = make_host(host), []
    try:
        result = {"ok": list(notifier.deliver(notice, inbox=box, setting=setting, probe=probe_of(answers),
                                              show=recorder_show(shown, calls)))}
    except Exception as error:
        result = {"error": type(error).__name__}
    return {"result": result, "calls": calls, "taken": None if box is None else [notice_out(n) for n in box.take()]}

def complete(locale, event, detail, card_shown, shown):
    speak(locale)
    notice = notifier.build_demo(detail) if event == "demo" else built(locale, event, detail, None)
    calls = []
    try:
        result = {"ok": notifier.complete(notice, card_shown, show=recorder_show(shown, calls))}
    except Exception as error:
        result = {"error": type(error).__name__}
    return {"result": result, "calls": calls}

def show_demo(locale, now, host, setting, answers):
    speak(locale)
    notice, box = notifier.build_demo(now), make_host(host)
    result = notifier.show_demo(notice, inbox=box, setting=setting, probe=probe_of(answers))
    return {"result": result, "taken": None if box is None else [notice_out(n) for n in box.take()]}

class Store:
    def __init__(self, pending):
        self.listed, self.closed = pending, False
    def pending(self):
        if self.listed == "raise":
            raise OSError("store")
        return self.listed
    def close(self):
        self.closed = True

def told(locale, event, build_detail, detail, pending, at):
    notice = built(locale, event, build_detail, None)
    opened = None if pending is None else (lambda: Store(pending))
    return notifier.told(notice, detail, opened, at)

ops = {"notifier.deliver": deliver, "notifier.complete": complete, "notifier.show_demo": show_demo,
       "notifier.told": told}
finish(cases, ops)
'''

ACTIVATE = SETUP + r'''
import itertools
CHAT = "codex-auto-resume:chat?thread=" + UUID
uris = ["codex://threads/" + UUID, CHAT, notify.open_uri("history"), notify.open_uri("nope"),
        notify.power_stop_uri(NONCE), notify.cancel_uri(KEY), notify.with_open_codex_flag(notify.cancel_uri(KEY)),
        "codex-auto-resume:cancel?i=bad", "", None, "x:y", "codex://threads/" + UUID.upper(), 5]
controls = [None, {"cancel": {"thread_id": UUID}, "stop": "stopped"},
            {"cancel": {"thread_id": UUID, "changed": False}, "stop": "over"},
            {"cancel": {"raise": "ControlError", "code": "no_such_interruption"}, "stop": {"raise": "ControlError",
                                                                                         "code": "power_unavailable"}},
            {"cancel": {"raise": "ControlError", "code": "Bad Code!"}, "stop": {"raise": "ControlError", "code": ""}},
            {"cancel": {"raise": "RuntimeError"}, "stop": {"raise": "OSError"}},
            {"cancel": {"raise": "ControlError", "code": 5}, "stop": None},
            {"cancel": None, "stop": "stopped"}, {"cancel": {}, "stop": "stopped"},
            {"cancel": [1], "stop": "stopped"}, {"cancel": {"changed": True}, "stop": "stopped"},
            {"cancel": {"thread_id": None}, "stop": "stopped"}]
openers = [None, True, False, 1, "x", {"raise": "OSError"}]
cases = []
for uri, control in itertools.product(uris, controls):
    cases.append(["notifier.activate", "en", uri, control, True, True, True, True, ["cancelled", "power"]])
for uri, opener in itertools.product(uris[:4], openers):
    cases.append(["notifier.activate", "fr", uri, controls[1], opener, opener, opener, True, []])
for uri in (notify.cancel_uri(KEY), notify.power_stop_uri(NONCE)):
    for announce, log in itertools.product([True, False, "raise"], [True, False, "raise"]):
        cases.append(["notifier.activate", "ar", uri, controls[1], True, announce, log, True, []])

def activate(locale, uri, control, opener, announce, log, chat, stay):
    speak(locale)
    lines, announced, calls = [], [], []

    class Control:
        def cancel_interruption(self, interruption_id, actor):
            calls.append(["cancel", interruption_id, actor])
            return answer(control["cancel"])
        def stop_power_countdown(self, nonce, actor):
            calls.append(["stop", nonce, actor])
            return answer(control["stop"])

    def opening(what):
        def open_it(value):
            calls.append([what, value])
            return answer(opener)
        return open_it

    def announcing(notice):
        if announce == "raise":
            raise OSError("announce")
        announced.append(notice_out(notice))

    def logging(line):
        if log == "raise":
            raise OSError("log")
        lines.append(line)

    try:
        result = {"ok": notifier.activate(
            uri, control=None if control is None else Control(),
            open_dashboard=None if opener is None else opening("dashboard"),
            announce=announcing if announce else None, log=logging if log else None,
            open_link=None if opener is None else opening("link"), stay=stay,
            open_chat=None if opener is None or not chat else opening("chat"))}
    except Exception as error:
        result = {"error": type(error).__name__}
    return {"result": result, "log": lines, "announced": announced, "calls": calls}

ops = {"notifier.activate": activate}
finish(cases, ops)
'''


class BuildDiff(Surface):
    def test_build(self):
        done = self.family(BUILD, label="notifier-build", chunk=1500)
        RECORD.append("notifier: %d build cases (every notice kind in 22 languages, each destination and kept kind), %d "
                      "Open Codex, %d click and %d other cases equal the tag's" % (
                          counted(done, "notifier.build"), counted(done, "notifier.open_codex"),
                          counted(done, "notifier.click") + counted(done, "notifier.notice_page"),
                          len(done["cases"]) - counted(done, "notifier.build") - counted(done, "notifier.open_codex")
                          - counted(done, "notifier.click") - counted(done, "notifier.notice_page")))


class RouteDiff(Surface):
    def test_routes(self):
        done = self.family(ROUTE, label="notifier-route")
        RECORD.append("routes: %d deliver, %d complete, %d show_demo and %d told cases equal the tag's (the toast's "
                      "content and silence recorded, nothing raised)" % (
                          counted(done, "notifier.deliver"), counted(done, "notifier.complete"),
                          counted(done, "notifier.show_demo"), counted(done, "notifier.told")))


class ActivateDiff(Surface):
    def test_activate(self):
        done = self.family(ACTIVATE, label="notifier-activate")
        RECORD.append("buttons: %d activate cases equal the tag's - the word, every log line, every announced notice and "
                      "every call made" % counted(done, "notifier.activate"))

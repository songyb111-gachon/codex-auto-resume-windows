"""S6.0, car-surface: notify.py - what every toast says, in every language, its XML document, and what `show` would
hand PowerShell.

* ContentDiff - every `*_content` builder and the sentences beside them (`headline`, `_origin_line`, `held_message`,
  `needs_you_*`, `slept_for`, `objection_message`, `not_resumed_message`, `_local_time`) in all 22 languages, over the
  identities, conversation ids, categories, holds, times, counts, windows, shares (the share LEFT, the owner's rule
  for a glance surface), versions and power events the tests build, and the odd ones (wrong types, huge ints,
  NaN, right-to-left names, long names, blank names).
* ToastDiff - `_toast_xml` over generated arguments (escaping, quoting, the five-button and three-line limits, the
  history copy, the sound, a body's launch, a reminder that stays), and `show`/`show_content` with PowerShell present
  or not and answering 0, 1, an OSError or a timeout: the argv (the script whole after `-Command`, never an encoded
  command - issue #65), the argument variables (XML, AUMID, SILENT), the creation flags, the streams and the timeout,
  recorded and compared; nothing is started.
"""
from __future__ import annotations

from rustdiff.surface import Surface, counted

RECORD: list[str] = []

CONTENT = r'''
from codex_auto_resume import l10n, notify, failures
UUID = "0a1b2c3d-3d4e-7f80-9a0b-1c2d3e4f5a6b"
NONCE = "0123456789abcdef"
T = 1_800_000_000
identities = [None, {}, {"name": "example-project"}, {"name": "  "}, {"project": "example-service"},
              {"name": "n", "project": "n"}, {"name": "n", "project": "p", "cwd_basename": "c"}, {"cwd_basename": "c"},
              {"name": "x" * 300}, {"name": "שלום", "project": "مشروع"},
              {"name": 5}, "notadict", {"name": "a\tb  c\n"}, {"project": " p ", "cwd_basename": "p"},
              {"name": "été \U0001f600"}]
threads = [UUID, "", None, 5, "x"]
categories = sorted(failures.CATEGORIES) + ["nope", None, []]
holds = [None, "ask", "notify_only", "workspace_changed", "context_cost", "after_sleep", "x", []]
times = [None, 0, T, T + 0.5, "x", True, -5, 10 ** 20, 2 ** 53 + 5, float("nan")]
cases = []
for locale in l10n.LOCALES:
    for identity in identities:
        cases.append(["notify.headline", locale, identity])
        cases.append(["notify.origin", locale, identity, "n", UUID])
        cases.append(["notify.starting", locale, UUID, identity, True])
        cases.append(["notify.resumed", locale, UUID, identity])
        cases.append(["notify.failed", locale, UUID, identity, False])
    for thread in threads:
        cases.append(["notify.cancelled", locale, thread])
        cases.append(["notify.starting", locale, thread, None, False])
        cases.append(["notify.failed", locale, thread, {"name": "n"}, True])
    for category in categories:
        cases.append(["notify.scheduled", locale, UUID, "1" * 64, T, category, {"name": "n"}, None])
        cases.append(["notify.scheduled", locale, UUID, "1" * 64, None, category, None, "ask"])
        cases.append(["notify.objection", locale, UUID, "1" * 64, T + 60, category, {"name": "n"}])
        cases.append(["notify.not_resumed", locale, UUID, None, "parent_handed_over", category])
        cases.append(["notify.needs_label", locale, category])
        cases.append(["notify.needs_message", locale, category, 15])
    for hold in holds:
        cases.append(["notify.held", locale, hold])
        cases.append(["notify.scheduled", locale, UUID, "1" * 64, T, "usage_limit", {"name": "n"}, hold])
    for when in times:
        cases.append(["notify.scheduled", locale, UUID, "1" * 64, when, "usage_limit", None, None])
        if when is not None:
            cases.append(["notify.objection_message", locale, when])
            cases.append(["notify.local_time", locale, when])
            cases.append(["notify.grace", locale, "hibernate", when, NONCE, False])
    for reason in ["no_progress", "attempts", "time", None, "x", []]:
        cases.append(["notify.stopped", locale, UUID, {"name": "n"}, reason])
    for reason in ["parent_handed_over", "parent_cancelled", "x", None, []]:
        cases.append(["notify.not_resumed_message", locale, reason])
        cases.append(["notify.not_resumed", locale, UUID, {"project": "p"}, reason, "terminal_auth"])
    for kind in ["stalled_turn", "terminal_auth", "terminal_failure", "terminal_invalid", "terminal_policy",
                 "terminal_user", "nope", None, [], 5]:
        for minutes in [None, 0, 25, -1, True, 10 ** 30, 2.5, "15"]:
            cases.append(["notify.needs_message", locale, kind, minutes])
        cases.append(["notify.needs_label", locale, kind])
        cases.append(["notify.needs", locale, UUID, kind, {"name": "n"}, 30, True])
        cases.append(["notify.needs", locale, UUID, kind, None, None, False])
    for seconds in [None, 0, 59, 60, 61, 3599, 3600, 3660, 7200, 86399, -100, 1.5e4, "4000", "x", True,
                    10 ** 25, float("inf"), float("nan"), [1]]:
        cases.append(["notify.slept", locale, seconds])
        cases.append(["notify.after_sleep", locale, seconds, 3])
    for count in [None, 0, 1, 5, -2, "7", 2.9, 10 ** 22, "x", True]:
        cases.append(["notify.after_sleep", locale, 7200, count])
    for event in ["memory_warning", "memory_stopped", "x", None]:
        for used, limit in [(300, 256), (-5, 512), ("x", None), (1e3, 2048.9), (10 ** 20, "512"), (True, False)]:
            cases.append(["notify.memory", locale, event, used, limit])
    for minutes in [None, 0, -5, 300, 10080, 1440, 2880, 60, 90, 10 ** 20, 10 ** 20 + 60, True, 5.0, "300"]:
        for percent in [None, 0, 50, 99.6, 150, -3, True, "40", float("nan"), 10 ** 30]:
            cases.append(["notify.near", locale, minutes, percent, T + 3600, None])
        cases.append(["notify.near", locale, minutes, 25, T + 1.5, None])
        cases.append(["notify.near", locale, minutes, 25, None, None])
    for kind in ["not_stopped", "press_resume", "not_continued", "x", [], None]:
        cases.append(["notify.near", locale, 300, 40, T, kind])
    for version in ["0.6.26", "0.6.27-alpha", "1.2.3-beta.10", "01.2.3", "1.2.3\n", 5, None, "1.2.3-beta.1",
                    "123456.0.0-beta.999", "١.2.3"]:
        for prerelease in [False, True, 1, None]:
            cases.append(["notify.update", locale, version, prerelease])
    cases.append(["notify.restart", locale])
    for action in ["sleep", "hibernate", "shut_down", "x", None, []]:
        for tasks in [False, True]:
            cases.append(["notify.grace", locale, action, T + 300, NONCE, tasks])
    for event in ["power_grace", "power_now", "power_failed", "power_not_met", "power_stopped", "x", None]:
        for detail in [{"until": T}, {"action": "hibernate", "until": T + 0.5, "nonce": NONCE, "tasks": True},
                       {"action": "shut_down", "tasks": 1, "until": T}, {"action": "x", "until": T},
                       {"until": "x"}, {"until": T, "tasks": True, "nonce": None}]:
            cases.append(["notify.power", locale, event, detail])
        if event != "power_grace":
            cases.append(["notify.power", locale, event, "notadict"])

def at(locale, function):
    def call(*args):
        speak(locale)
        return function(*args)
    return call

def run_case(case):
    name, locale, args = case[0], case[1], case[2:]
    speak(locale)
    return OPS[name](*args)

OPS = {
    "notify.headline": notify.headline,
    "notify.origin": notify._origin_line,
    "notify.scheduled": lambda t, i, r, c, ident, h: notify.scheduled_content(t, i, r, c, ident, hold=h),
    "notify.objection": notify.objection_content,
    "notify.objection_message": notify.objection_message,
    "notify.cancelled": notify.cancelled_content,
    "notify.starting": lambda t, ident, changed: notify.starting_content(t, ident, task_changed=changed),
    "notify.resumed": notify.resumed_content,
    "notify.failed": lambda t, ident, certain: notify.attempt_failed_content(t, ident, certain=certain),
    "notify.stopped": lambda t, ident, reason: notify.stopped_content(t, ident, reason=reason),
    "notify.not_resumed": lambda t, ident, reason, c: notify.not_resumed_content(t, ident, reason=reason, category=c),
    "notify.not_resumed_message": notify.not_resumed_message,
    "notify.held": notify.held_message,
    "notify.needs_label": notify.needs_you_label,
    "notify.needs_message": notify.needs_you_message,
    "notify.needs": lambda t, kind, ident, minutes, sound: notify.needs_you_content(t, kind, ident, minutes=minutes,
                                                                                    sound=sound),
    "notify.slept": notify.slept_for,
    "notify.after_sleep": notify.after_sleep_content,
    "notify.memory": notify.memory_content,
    "notify.near": notify.near_limit_content,
    "notify.update": notify.update_offered_content,
    "notify.restart": notify.restart_gave_up_content,
    "notify.grace": notify.power_grace_content,
    "notify.power": notify.power_content,
    "notify.local_time": notify._local_time,
}
ops = {name: (lambda name: lambda locale, *args: (speak(locale), OPS[name](*args))[1])(name) for name in OPS}
finish(cases, ops)
'''

TOAST = r'''
import random
from codex_auto_resume import notify, pwsh
recorder = Recorder()
pwsh.subprocess = recorder
real_executable = pwsh.executable
rng = random.Random(65)
texts = ["", "plain", "a & b", "<x>", "\"q\"", "'s'", "both ' \"", "line\nbreak", "tab\tcr\r", "שלום",
         "é\U0001f600", "&amp;", "]]>", " "]
uris = ["codex-auto-resume:cancel?i=" + "1" * 64, "codex-auto-resume:open?page=pending", "", "a\"b'c", "x&y"]
def options():
    chosen = {}
    if rng.random() < 0.6:
        chosen["button"] = rng.choice(texts + [None])
    if rng.random() < 0.6:
        chosen["uri"] = rng.choice(uris + [None])
    if rng.random() < 0.6:
        chosen["extra"] = [rng.choice(texts) for _ in range(rng.randint(0, 4))]
    if rng.random() < 0.6:
        chosen["more"] = [[rng.choice(texts), rng.choice(uris)] for _ in range(rng.randint(0, 7))]
    if rng.random() < 0.4:
        chosen["silent"] = rng.choice([True, False, 1, None])
    if rng.random() < 0.4:
        chosen["sound"] = rng.choice([True, False, None, 1, "x"])
    if rng.random() < 0.4:
        chosen["launch"] = rng.choice(uris + [None, 5])
    if rng.random() < 0.4:
        chosen["stays"] = rng.choice([True, False, 1, None])
    return chosen
cases = []
for _ in range(1500):
    cases.append(["notify.xml", rng.choice(texts), rng.choice(texts), options()])
odd = [{"extra": None}, {"more": None}, {"more": ["ab"]}, {"more": ["abc"]}, {"more": [[1, 2]]}, {"more": "xy"},
       {"button": 5, "uri": "u"}, {"extra": "abc"}, {"extra": [5]}, {"more": [["l", 5]]}, {"more": {"ab": 1}},
       {"extra": [0, None, "", "x"]}]
for chosen in odd:
    cases.append(["notify.xml", "t", "b", chosen])
cases.append(["notify.xml", 5, "b", {}])
cases.append(["notify.xml", "t", None, {}])
for _ in range(300):
    cases.append(["notify.show", rng.choice(texts), rng.choice(texts), options(), rng.random() < 0.85,
                  rng.choice([0, 0, 1, -1, "oserror", "timeout"])])
cases += [["notify.show", "x" * 17000, "b", {}, True, 0], ["notify.show", "a\x00b", "b", {}, True, 0],
          ["notify.show", "t", "b", {"silent": True}, True, 0], ["notify.show", 5, "b", {}, True, 0],
          ["notify.show", "t", "b", {"more": None}, True, 0]]
contents = [{"title": "t", "body": "b"}, {"title": "t", "body": "b", "button": "Stop", "uri": uris[0], "extra": ["e"],
             "more": [["Open", uris[1]]], "sound": True, "launch": uris[1], "stays": True},
            {"title": "t"}, {"body": "b"}, {"title": "t", "body": "b", "other": 5, "sound": False}]
for content in contents:
    for silent in [False, True]:
        for outcome in [0, 1, "timeout"]:
            cases.append(["notify.show_content", content, silent, True, outcome])
    cases.append(["notify.show_content", content, False, False, 0])
cases.append(["notify.consts"])

def show(title, body, chosen, available, outcome):
    recorder.calls, recorder.outcome = [], outcome
    pwsh.executable = real_executable if available else (lambda: None)
    try:
        result = {"ok": notify.show(title, body, **chosen)}
    except Exception as error:
        result = {"error": type(error).__name__}
    return {"result": result, "calls": recorder.calls}

def show_content(content, silent, available, outcome):
    recorder.calls, recorder.outcome = [], outcome
    pwsh.executable = real_executable if available else (lambda: None)
    try:
        result = {"ok": notify.show_content(content, silent=silent)}
    except Exception as error:
        result = {"error": type(error).__name__}
    return {"result": result, "calls": recorder.calls}

def consts():
    return [notify._SCRIPT, notify.MAX_TOAST_ACTIONS, notify.MAX_TOAST_LINES, notify.NEEDS_YOU_SOUND,
            notify.DEFAULT_SOUND, notify.aumid(), notify.TIMEOUT_SECONDS, notify.LEGACY_POWERSHELL_AUMID,
            list(notify.NEAR_LIMIT_KINDS), list(notify.POWER_ACTIONS), dict(notify.NOT_RESUMED),
            dict(notify.HELD_MESSAGES), notify.UPDATE_VERSION.pattern, notify.CODEX_THREAD_LINK, notify.SCHEME,
            notify.OPEN_CODEX_FLAG]

ops = {"notify.xml": lambda title, body, chosen: notify._toast_xml(title, body, **chosen), "notify.show": show,
       "notify.show_content": show_content, "notify.consts": consts}
finish(cases, ops)
'''


class ContentDiff(Surface):
    def test_contents(self):
        done = self.family(CONTENT, label="notify-content", chunk=3000)
        failed = sum(1 for result in done["results"] if "error" in result)
        RECORD.append("notify: %d content and sentence cases in all 22 languages equal the tag's (%d of them raise, alike)"
                      % (len(done["cases"]), failed))


class ToastDiff(Surface):
    def test_toasts(self):
        done = self.family(TOAST, label="notify-toast")
        started = sum(len(result["ok"]["calls"]) for case, result in zip(done["cases"], done["results"])
                      if case[0].startswith("notify.show") and "ok" in result)
        RECORD.append("toast: %d XML documents equal the tag's; %d show/show_content cases equal, %d PowerShell starts "
                      "recorded (argv with -Command and the script whole, XML/AUMID/SILENT variables, CREATE_NO_WINDOW, "
                      "NUL streams, 20 s) and none made" % (
                          counted(done, "notify.xml"), counted(done, "notify.show"), started))

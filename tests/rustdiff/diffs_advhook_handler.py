"""The Stop hook's handler (car-adv `hook/handler.rs`) held to the tag's `hook/handler.py` over recorded inputs.

What Codex hands the hook is one JSON object on standard input; the handler reads it through an allow-list of keys, decides
(is the capability on, is the conversation's latest turn a failure a hook may continue, does the shared claim grant it) and
answers with one block on standard output, or nothing. Here each case is an input and the hands - the capability's state,
the person's settings, Codex's latest turn, the claim, the clock - as data; the tag's handler and the Rust one run them and
write down the answer, the exit code and every claim asked for (its failure, its turn digest, its time).

* InputDiff - `read_input` and `pick` over every shape of input (a stop, the same with the message, the transcript's path and
  the prompt of a conversation beside it, keys repeated, the wrong event, a stop that follows a block, ids that are not ids,
  over a megabyte, not UTF-8, a BOM, not JSON, an array, nesting past recursion), `stop_of`, `turn_key`, `continues`.
* DecideDiff - `decide` over each kind of failure (every transient kind, a usage limit, an unknown one, a turn that is
  another's, a status that is not failed), under settings that switch a category off or lengthen its first wait past a minute,
  in every language, with every outcome the claim can answer, a claim that raises, a budget spent before the claim.
* MainDiff - `main` as the launcher runs it: its arguments, a block written, nothing written, and the time budget: a read that
  passes the budget before a claim begins is a pass, a claim begun is let finish within its grace.
"""
from __future__ import annotations

import unittest

from rustdiff import advreport

RECORD = []

PRELUDE = r'''
import io, itertools, threading, time
from codex_auto_resume import settings
from codex_auto_resume_advanced.hook import handler, format as hookformat
from codex_auto_resume_advanced.vocabulary import HookOutcome

def uuid(number, kind=1):
    return "0a1b2c3d-%04d-7000-8000-%012d" % (kind, number)

THREAD, TURN = uuid(1), uuid(1, 2)

def stop(thread=THREAD, turn=TURN, **more):
    document = {"hook_event_name": "Stop", "session_id": thread, "turn_id": turn, "stop_hook_active": False}
    document.update(more)
    return document

def failure_row(kind="serverOverloaded", thread=THREAD, turn=TURN, status="failed", completed=1763999910.0, ordinal=4, message="x"):
    return {"thread_id": thread, "turn_id": turn, "status": status, "started_at": 1763999900.0, "completed_at": completed,
            "ordinal": ordinal, "error_json": json.dumps({"codexErrorInfo": kind, "message": message})}

def values(**changes):
    return json.loads(json.dumps(settings.coerce(dict({"continuation_language": "en"}, **changes))))

class Hands:
    """The tag's Hands, answering from a case; every claim written down."""
    def __init__(self, case):
        self.case, self.log, self.ticks = case, [], itertools.count()
        self.hands = handler.Hands(armed=self.armed, settings=self.settings, latest=self.latest, claim=self.claim, clock=self.clock)
    def _pause(self, name):
        if self.case.get(name):
            time.sleep(self.case[name])
    def _item(self, name):
        item = self.case.get(name)
        if isinstance(item, dict) and "raise" in item:
            raise {"RuntimeError": RuntimeError, "KeyError": KeyError, "OSError": OSError}[item["raise"]]("boom")
        return item
    def armed(self):
        return self._item("armed") is True
    def settings(self):
        return self._item("settings")
    def latest(self, thread):
        self._pause("delay_latest")
        latest = self.case.get("latest") or {}
        item = latest.get(thread, latest.get("*"))
        if isinstance(item, dict) and "raise" in item:
            raise RuntimeError("boom")
        return item
    def claim(self, failure, turn_key, now):
        self.log.append([failure, turn_key, now])
        self._pause("delay_claim")
        item = self._item("claim")
        return None if item is None else HookOutcome(item)
    def clock(self):
        clock = self.case.get("clock") or {"start": 0.0, "step": 0.0}
        return clock["start"] + clock["step"] * next(self.ticks)

def error_name(error):
    return {"error": type(error).__name__}
'''

INPUT_SCRIPT = PRELUDE + r'''
big = {"hook_event_name": "Stop", "session_id": THREAD, "turn_id": TURN, "stop_hook_active": False,
       "last_assistant_message": "private words", "transcript_path": "C:\\Users\\ExampleUser\\secret.jsonl", "prompt": "hello"}
INPUTS = [
    json.dumps(stop()), json.dumps(big), json.dumps(stop(extra={"nested": [1, {"session_id": "no"}]})),
    '{"hook_event_name": "Stop", "session_id": "' + THREAD + '", "session_id": "' + uuid(2) + '"}',
    json.dumps(stop(stop_hook_active=True)), json.dumps(stop(stop_hook_active="true")), json.dumps(stop(stop_hook_active=1)),
    json.dumps(stop(hook_event_name="SessionStart")), json.dumps(stop(hook_event_name="stop")), json.dumps(stop(hook_event_name=None)),
    json.dumps(stop(thread="not-an-id")), json.dumps(stop(thread=None)), json.dumps(stop(thread=7)), json.dumps(stop(thread=THREAD.upper())),
    json.dumps(stop(turn=None)), json.dumps(stop(turn="x")), json.dumps(stop(turn=5)),
    json.dumps({k: v for k, v in stop().items() if k != "turn_id"}), json.dumps({k: v for k, v in stop().items() if k != "session_id"}),
    "[]", "[1, 2]", "null", "7", '"text"', "true", "{}", "", " ", "not json", "{", '{"a": NaN}', '{"hook_event_name": "Stop", "x": Infinity}',
    "\ufeff" + json.dumps(stop()), json.dumps(stop(), indent=4), json.dumps(stop()) + " trailing", json.dumps(stop()) + "\n",
    "[" * 5000 + "]" * 5000, '{"a": ' * 3000 + "1" + "}" * 3000,
    json.dumps({"session_id": THREAD, "turn_id": TURN, "hook_event_name": "Stop", "stop_hook_active": None}),
]
for text in INPUTS:
    case("handler.read_input", text, ref=lambda text=text: handler.read_input(io.BytesIO(text.encode("utf-8", "surrogatepass"))))
for data in (b"\xff\xfe{}", b'{"hook_event_name": "Stop"}\xff', "\u00e9".encode("latin-1"), json.dumps(stop()).encode("utf-16"), b"\x00" * 10):
    case("handler.read_input", list(data), ref=lambda data=data: handler.read_input(io.BytesIO(data)))
limit = handler.MAX_INPUT
prefix = b'{"hook_event_name": "Stop", "session_id": "' + THREAD.encode() + b'", "pad": "'
for total in (limit - 1, limit, limit + 1, limit + 100):
    data = prefix + b"a" * (total - len(prefix) - 2) + b'"}'
    case("handler.read_input", data.decode("ascii"), ref=lambda data=data: handler.read_input(io.BytesIO(data)))
case("handler.read_input", {"repeat": [32, limit + 1]}, ref=lambda: handler.read_input(io.BytesIO(b" " * (limit + 1))))
case("handler.read_input", {"repeat": [32, limit]}, ref=lambda: handler.read_input(io.BytesIO(b" " * limit)))

for picked in (stop(), big, {}, {"hook_event_name": "Stop"}, {"session_id": THREAD}, [], None, "x", 7, stop(stop_hook_active=True), stop(thread="x"), stop(turn="x"),
               stop(turn=None), stop(hook_event_name="Other"), {"extra": 1}):
    case("handler.pick", picked, ref=lambda picked=picked: handler.pick(picked))
    if isinstance(picked, dict):
        case("handler.stop_of", picked, ref=lambda picked=picked: handler.stop_of(picked))
for turn in (TURN, "x", "", uuid(7, 3)):
    case("handler.turn_key", turn, ref=lambda turn=turn: handler.turn_key(turn))

DEFAULT = values()
TIMINGS = ["immediate", "gentle", "patient", "slow", "relaxed", "steady", "default"]
for kind in ("serverOverloaded", "httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected", "internalServerError",
             "usageLimitExceeded", "unauthorized", "badRequest", "other", "responseTooManyFailedAttempts", None):
    from codex_auto_resume.codex import detect
    failure = detect(failure_row(kind))
    if failure is None:
        failure = {"category": "unknown", "thread_id": THREAD, "turn_id": TURN}
    for category in ("network_transient", "timeout", "server_5xx", "stream_interrupted", "rate_limit_transient", "usage_limit", "unknown", None, 5):
        failure = dict(failure, category=category)
        for shaped in (DEFAULT, values(retry_timing="gentle"), values(recover_network_transient=False), values(recover_server_5xx=False),
                       values(retry_timing="patient"), {}, None, {"retry_timing": "custom"}, values(retry_timing="custom", retry_steps=[30, 90, 300])):
            case("handler.continues", failure, shaped, ref=lambda failure=failure, shaped=shaped: handler.continues(failure, shaped))
finish()
'''

DECIDE_SCRIPT = PRELUDE + r'''
TURN2 = uuid(1, 3)
KINDS = ["serverOverloaded", "httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected", "internalServerError",
         "usageLimitExceeded", "unauthorized", "badRequest", "other"]
LANGUAGES = ["en", "ko", "de", "ja", "fr", "es", "zh-CN", "ru", "pt-BR", "ar"]
SETTINGS = [values(), values(retry_timing="gentle"), values(recover_network_transient=False), values(retry_timing="patient")] + [
    values(continuation_language=language) for language in LANGUAGES]

def decide_case(picked, **given):
    case_data = dict({"armed": True, "settings": values(), "latest": {"*": failure_row()}, "claim": "blocked",
                      "clock": {"start": 100.0, "step": 0.0}, "started": 100.0}, **given)
    case_data["picked"] = picked
    hands = Hands(case_data)
    claiming = threading.Event()
    try:
        outcome = handler.decide(picked, hands.hands, started=case_data["started"], claiming=claiming)
        result = outcome
    except Exception as error:
        result = error_name(error)
    CASES.append(["handler.decide", case_data])
    RESULTS.append({"ok": {"result": result, "claiming": claiming.is_set(), "claims": json.loads(json.dumps(hands.log))}})

for kind in KINDS:
    for shaped in SETTINGS:
        decide_case(stop(), latest={"*": failure_row(kind)}, settings=shaped)
for claim in ("blocked", "passed", "refused", None, {"raise": "RuntimeError"}, {"raise": "KeyError"}):
    decide_case(stop(), claim=claim)
for armed in (True, False, None, {"raise": "RuntimeError"}):
    decide_case(stop(), armed=armed)
for latest in ({"*": None}, {"*": failure_row(thread=uuid(9))}, {"*": failure_row(turn=TURN2)}, {"*": failure_row(status="completed")}, {"*": failure_row(status="inProgress")},
               {"*": failure_row(completed=None)}, {"*": failure_row(ordinal=-1)}, {"*": {"raise": "RuntimeError"}}, {"*": "text"}, {"*": []}, {THREAD: failure_row(), "*": None}, {}):
    decide_case(stop(), latest=latest)
decide_case(stop(turn=None))
decide_case(stop(turn=None), latest={"*": failure_row(turn=TURN2)})
decide_case(stop(), settings={"raise": "OSError"})
decide_case(stop(stop_hook_active=True))
decide_case(stop(hook_event_name="x"))
for clock in ({"start": 100.0, "step": 0.0}, {"start": 100.0, "step": 0.5}, {"start": 100.0, "step": 1.39}, {"start": 100.0, "step": 1.41}, {"start": 100.0, "step": 3.0}):
    decide_case(stop(), clock=clock)
decide_case(stop(), started=None, clock={"start": 5.0, "step": 1.0})
decide_case(stop(), started=None, clock={"start": 5.0, "step": 1.5})
decide_case(stop(), started=98.6)
decide_case(stop(), started=98.59)
finish()
'''

MAIN_SCRIPT = PRELUDE + r'''
def main_case(argv, data, **given):
    case_data = dict({"armed": True, "settings": values(), "latest": {"*": failure_row()}, "claim": "blocked",
                      "clock": {"start": time.time(), "step": 0.0}}, **given)
    case_data["argv"] = argv
    case_data["input"] = data if isinstance(data, str) else list(data)
    hands = Hands(case_data)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    out = io.BytesIO()
    code = handler.main(argv, stdin=io.BytesIO(raw), stdout=out, hands=hands.hands)
    CASES.append(["handler.main", case_data])
    RESULTS.append({"ok": {"code": code, "stdout": out.getvalue().decode("utf-8"), "claims": json.loads(json.dumps(hands.log))}})

good = json.dumps(stop())
main_case(["--home", "C:\\x"], good)
main_case([], good)
main_case(["--home"], good)
main_case(["--home=C:\\x"], good)
main_case(["--ho", "x"], good)
main_case(["--h", "x"], good)
main_case(["-x", "--home", "-5"], good)
main_case(["--home", "-5"], good)
main_case(["--home", "--other"], good)
main_case(["--unknown", "1", "--home", "x", "tail"], good)
main_case(["--home", "x"], "not json")
main_case(["--home", "x"], "")
main_case(["--home", "x"], good, claim="passed")
main_case(["--home", "x"], good, claim="refused")
main_case(["--home", "x"], good, armed=False)
main_case(["--home", "x"], good, latest={"*": failure_row("usageLimitExceeded")})
main_case(["--home", "x"], good, settings={"raise": "OSError"})
main_case(["--home", "x"], good, claim={"raise": "RuntimeError"})
for language in ("en", "ko", "de", "ja"):
    main_case(["--home", "x"], good, settings=values(continuation_language=language))
main_case(["--home", "x"], json.dumps(stop(thread="\u00e9")))
# the time budget: a read that is slow before a claim begins passes; a claim begun is let finish, within its grace
main_case(["--home", "x"], good, delay_latest=2.6)
main_case(["--home", "x"], good, delay_claim=2.4)
main_case(["--home", "x"], good, delay_claim=1.0)
main_case(["--home", "x"], good, delay_latest=1.5, clock={"start": time.time(), "step": 0.0})
finish()
'''


def _wait_started() -> None:
    return None


class InputDiff(advreport.ReportDiff):
    EXAMPLE = "advhook"

    def test_the_input_is_read_through_its_allow_list(self):
        found = self.family(INPUT_SCRIPT, label="hook-input", expect_cases=150)
        RECORD.append("hook input: %d cases - read_input, pick, stop_of, turn_key and continues over every shape of input and "
                      "failure; nothing but the allowed keys survives" % len(found["cases"]))


class DecideDiff(advreport.ReportDiff):
    EXAMPLE = "advhook"

    def test_what_a_stop_is_decided_to_be(self):
        found = self.family(DECIDE_SCRIPT, label="hook-decide", expect_cases=100)
        reasons = [result["ok"]["result"] for result in found["results"] if isinstance(result["ok"]["result"], str)]
        self.assertTrue(reasons, "no case blocks")
        RECORD.append("hook decide: %d cases - %d blocks, every failure kind, every language, every claim answer, a clock that "
                      "spends the budget" % (len(found["cases"]), len(reasons)))


class MainDiff(advreport.ReportDiff):
    EXAMPLE = "advhook"

    def test_the_handler_as_the_launcher_runs_it(self):
        found = self.family(MAIN_SCRIPT, label="hook-main", expect_cases=20)
        blocks = [result["ok"]["stdout"] for result in found["results"] if result["ok"]["stdout"]]
        self.assertTrue(blocks)
        RECORD.append("hook main: %d runs - arguments, a block written, nothing written, the budget and the commit grace"
                      % len(found["cases"]))


if __name__ == "__main__":
    unittest.main()

"""S7.2c remainder: `codex/headless.py` as the v0.6.26 final has it, held equal to car-adv's `codex::headless`.

A case is one `HeadlessRun` (turn, compact or fallback mode; with and without the app look and the owed model) over a
scripted session stand-in: every method's answers (results, Codex's refusal of that method or another, a timeout, a
refusal by the session, any other raise), the notifications each drain gives (a turn/completed for this turn, another
turn, another thread, of every status; a Stop asked from inside a drain), the launch guard's permission and its exit,
core's look asked again, opening and entering that raise. Its follower is its own, on a clock that counts its readings.
Each resume is followed to its end; compared are the answers, `refused`, `on_default`, `model`, what the follower
drained for the capability and for another, EMPTY_REFUSED, and the whole log in order: every call with its
parameters, every look, every clock reading, every drain, the open, enter and exit.
The pure readers: `settings_allowed` (every sandbox, policy, reviewer and profile shape, unhashable words), `_model`,
`_default_model`, `_turn_id`, `_completed`.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_headless`.
"""
from __future__ import annotations

import random

from rustdiff.advcodexd import AdvCodexRestDiff

THREAD = "0a1b2c3d-0001-7000-8000-00000000000a"
TURN = "0a1b2c3d-0001-7000-8000-0000000000bb"
OTHER_TURN = "0a1b2c3d-0001-7000-8000-0000000000cc"
GOOD = {"sandbox": {"type": "workspaceWrite"}, "approvalPolicy": "on-request", "approvalsReviewer": "user",
        "model": "gpt-5.1"}
CLIENT = "car-0123456789abcdef0123456789abcdef"


def completed(turn=TURN, status="completed", thread=THREAD):
    return {"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": turn, "status": status}}}


def settings_shapes() -> list:
    shapes = [None, [], "x", {}, GOOD, dict(GOOD, sandbox={"type": "dangerFullAccess"}),
              dict(GOOD, sandbox={"type": ["readOnly"]}), dict(GOOD, sandbox="readOnly"),
              dict(GOOD, approvalPolicy={"granular": {}}), dict(GOOD, approvalPolicy="sometimes"),
              dict(GOOD, approvalsReviewer="auto_review"), dict(GOOD, approvalsReviewer=["user"]),
              dict(GOOD, approvalsReviewer=None), dict(GOOD, activePermissionProfile=None),
              dict(GOOD, activePermissionProfile={"id": ":workspace"}),
              dict(GOOD, activePermissionProfile={"id": ":read-only", "extends": None}),
              dict(GOOD, activePermissionProfile={"id": ":workspace", "extends": ":full"}),
              dict(GOOD, activePermissionProfile={"id": "mine"}),
              dict(GOOD, activePermissionProfile={"id": ":workspace", "more": 1}),
              dict(GOOD, activePermissionProfile={"id": [":workspace"]}),
              dict(GOOD, activePermissionProfile=":workspace"), dict(GOOD, sandbox={"type": "readOnly"}),
              dict(GOOD, approvalPolicy="never"), dict(GOOD, approvalPolicy="untrusted")]
    return shapes


def resume_spec(rng: random.Random, index: int) -> dict:
    mode = rng.choice(["turn", "turn", "compact", "fallback"])
    session = {}
    resumed = rng.choice(settings_shapes()[4:] + [GOOD, GOOD, GOOD, dict(GOOD, model="gpt-5-mini"), dict(GOOD, model=7)])
    session["thread/resume"] = [rng.choice([resumed, resumed, {"raise": "RuntimeError"}, {"raise": "RefusedByCodex"}])]
    if rng.random() < 0.5:
        session["thread/resume"].append(rng.choice([dict(GOOD, model="gpt-5.1"), dict(GOOD, model="other"),
                                                    {"raise": "RuntimeError"}]))
    session["model/list"] = [rng.choice([{"data": [{"model": "gpt-5", "isDefault": True}]},
                                         {"data": [{"id": "gpt-5.1", "isDefault": True}]},
                                         {"data": [{"model": "", "id": "x" * 129, "isDefault": True}]},
                                         {"data": [{"model": "m", "isDefault": 1}]}, {"data": "no"},
                                         {"raise": "RuntimeError"}])]
    start = rng.choice([{"turn": {"id": TURN}}, {"turn": {"id": "not-a-uuid"}}, {"turn": {}}, {},
                        {"raise": "RefusedByCodex"}, {"raise": "RefusedByCodex", "method": "elsewhere"},
                        {"raise": "SessionRefused"}, {"raise": "protocol_timeout"}, {"raise": "RuntimeError"}])
    session["turn/start"] = [start]
    session["thread/compact/start"] = [rng.choice([{}, {"raise": "RefusedByCodex"}, {"raise": "protocol_timeout"}])]
    session["turn/interrupt"] = [rng.choice([{}, {}, {"raise": "RuntimeError"}])]
    session["thread/settings/update"] = [rng.choice([{}, {}, {"raise": "RuntimeError"}])]
    session["thread/unsubscribe"] = [rng.choice([{}, {"raise": "RuntimeError"}])]
    events = []
    for _ in range(rng.randint(0, 6)):
        events.append(rng.choice([[], [], [completed()], [completed(status="failed")], [completed(status="weird")],
                                  [completed(status="interrupted")], [completed(turn=OTHER_TURN)],
                                  [completed(thread="other")], [{"method": "turn/started"}, completed()],
                                  ["not an event"], [{"method": "turn/completed", "params": {"threadId": THREAD}}],
                                  {"stop": ["k1", "interrupted"]}, {"stop": ["other-key", "interrupted"]},
                                  {"stop": [None, "yielded"]}]))
    spec = {"mode": mode, "session": session, "events": events, "seconds": rng.choice([3, 5, 12, 30]),
            "tick": rng.choice([1.0, 2.5, 7.0]), "key": rng.choice(["k1", "k2"])}
    if rng.random() < 0.4:
        spec["app"] = [rng.choice([False, False, True, "raise", 1, 0])]
    if mode == "fallback" and rng.random() < 0.8:
        spec["owe"] = [rng.choice([True, True, False, "raise", 1])]
    if rng.random() < 0.05:
        spec["open"] = "raise"
    if rng.random() < 0.05:
        spec["enter"] = "raise"
    if rng.random() < 0.2:
        spec["guard"] = [rng.choice([True, False, "raise", 1, None])]
        spec["guard_exit"] = [rng.choice(["ok", "ok", "raise"])]
    if rng.random() < 0.2:
        spec["still"] = [rng.choice([True, False, "raise", 1])]
    resumes = []
    for _ in range(rng.randint(1, 3)):
        resumes.append({"thread": rng.choice([THREAD, THREAD, THREAD, THREAD.upper(), "nope", None, 5]),
                        "words": rng.choice(["go on", "", None, 5, "x" * 30001, "é" * 30000, "y" * 30000]),
                        "client_id": rng.choice([None, None, CLIENT, "bad id", 5]),
                        "guard": rng.random() < 0.5, "still": rng.random() < 0.5})
    spec["resumes"] = resumes
    return spec


class HeadlessDiff(AdvCodexRestDiff):
    def test_pure(self):
        cases = [["hl.pure", "settings_allowed", shape] for shape in settings_shapes()]
        for value in (None, {}, {"model": ""}, {"model": "m"}, {"model": "x" * 128}, {"model": "x" * 129},
                      {"model": 5}, {"model": "é" * 128}, [1]):
            cases.append(["hl.pure", "model", value])
        for value in (None, {"data": []}, {"data": [{"model": "a", "isDefault": True}, {"model": "b", "isDefault": True}]},
                      {"data": [{"model": None, "id": "i", "isDefault": True}]}, {"data": [{"model": "a"}]},
                      {"data": [5, {"model": "z", "isDefault": True}]}, {"data": {"model": "a"}}):
            cases.append(["hl.pure", "default_model", value])
        for value in (None, {"turn": {"id": TURN}}, {"turn": {"id": ""}}, {"turn": {"id": 5}}, {"turn": []}, {}):
            cases.append(["hl.pure", "turn_id", value])
        events = [completed(), completed(status="failed"), completed(turn=OTHER_TURN, status="weird"),
                  completed(thread="x"), {"method": "turn/completed"}, 5]
        for turn in (TURN, OTHER_TURN, None, "absent"):
            for start in range(len(events)):
                cases.append(["hl.pure", "completed", [events[start:], THREAD, turn]])
        self.same("pure", cases)

    def test_runs(self):
        rng = random.Random(7213)
        cases = [["hl.case", {"session": {"thread/resume": [GOOD], "turn/start": [{"turn": {"id": TURN}}]},
                              "events": [[], [], [completed()]], "resumes": [{"thread": THREAD, "words": "go on"}]}],
                 ["hl.case", {"session": {"thread/resume": [GOOD], "turn/start": [{"turn": {"id": TURN}}]},
                              "seconds": 3, "resumes": [{"thread": THREAD, "words": "go on"}]}],
                 ["hl.case", {"mode": "fallback", "owe": [True],
                              "session": {"thread/resume": [GOOD, dict(GOOD, model="gpt-5.1")],
                                          "model/list": [{"data": [{"model": "gpt-5", "isDefault": True}]}],
                                          "turn/start": [{"turn": {"id": TURN}}]},
                              "events": [[completed(status="failed")]], "resumes": [{"thread": THREAD, "words": "x"}]}],
                 ["hl.case", {"mode": "fallback", "owe": [True],
                              "session": {"thread/resume": [GOOD],
                                          "model/list": [{"data": [{"model": "gpt-5", "isDefault": True}]}],
                                          "turn/start": [{"raise": "RefusedByCodex"}]},
                              "resumes": [{"thread": THREAD, "words": ""}]}],
                 ["hl.case", {"app": [False, True], "seconds": 100,
                              "session": {"thread/resume": [GOOD], "turn/start": [{"turn": {"id": TURN}}]},
                              "events": [[], [], [], [], [], [], [], [], [], [], [], [], [completed(status="interrupted")]],
                              "resumes": [{"thread": THREAD, "words": "go"}]}],
                 ["hl.case", {"mode": "compact", "session": {"thread/resume": [GOOD]},
                              "events": [{"stop": ["k1", "interrupted"]}], "resumes": [{"thread": THREAD}]}]]
        cases += [["hl.case", resume_spec(rng, index)] for index in range(260)]
        want = self.same("runs", cases, chunk=40)
        ends = [end["end"] for one in want if "ok" in one for step in one["ok"]["steps"] for end in step["ends"]]
        for word in ("completed", "failed", "interrupted", "capped", "yielded", "lost"):
            self.assertIn(word, ends)

"""S7.4b: the 31 measurement probes S7.4 left (`measure.py` of the v0.6.26 final), held equal on car-adv's `advmeasure`
probe over the tests' kind of fakes only - never a real Codex, turn, process or Codex home (the owner's Q2 (a)).

The same harness as diffs_advmeasure.py (`advmeasure.both`): every probe through no session, odd answers, every raise,
failed opens and enters, a thread given or not, versions read or unreadable; then each probe's own scripts. A Codex home
is a scratch folder each side builds the same (`advmeasure.build_home`: codexdiff.Home's tables and rollouts), the lock's
holders are the case's `users` (windows.resource_users), the app's identity and core's loaded check the backend's, the
restart, the hands and the clock the case's script. MQP's adds run on threads of their own on both sides; their part of
the log is compared as a set (advmeasure._settle).
"""
from __future__ import annotations

import json
import unittest

from rustdiff import advmeasure
from rustdiff.diffs_advmeasure import ODD, RAISES, THREAD, OTHER, VERSIONS, Compare, completed, run_case

THIRD = "0a1b2c3d-0001-7000-8000-0000000000cc"
T1 = "0a1b2c3d-0002-7000-8000-000000000001"
T2 = "0a1b2c3d-0002-7000-8000-000000000002"
T3 = "0a1b2c3d-0002-7000-8000-000000000003"
METHODS = ("thread/loaded/list", "thread/queue/list", "thread/queue/add", "thread/goal/get", "thread/goal/set",
           "account/read", "thread/resume", "turn/start", "turn/interrupt", "thread/unsubscribe", "hooks/list",
           "thread/compact/start", "model/list", "thread/settings/update", "config/read", "config/value/write",
           "thread/list", "thread/read", "turn/steer", "account/rateLimits/read")
APP = {"server": {"pid": 41, "created": 7}}
USER = {"pid": 41, "created": 7}
OTHER_USER = {"pid": 52, "created": 9}
ALL = ("M4", "ME", "MS", "MK", "MO", "MX", "MXA", "MF", "M3B", "MB", "MB2", "MC1", "MC2", "MQO", "MQP", "MQG", "MTOK",
       "MOPEN", "MAL", "MALR", "MWAKE", "MHK", "M4B", "MANCHOR", "MIMG", "MSTEER", "MSTEER2", "MGAVE", "MPROFILE",
       "MSWAP", "MAUTO")
FAST = {"m2b_queue": 3.0, "m2b_poll": 1.0, "m6_turn": 2.0, "m6_interrupt": 1.0, "m6_poll": 0.5, "m4_turn": 2.0,
        "m4_note": 1.5, "mc1_queue": 3.0, "mc1_start": 2.0, "mc2": 3.0, "mc2_poll": 1.0, "mqp_add": 30.0,
        "mqg_settle": 3.0, "mqo_open": 3.0, "mqo_find": 2.0, "mopen": 2.0, "mopen_poll": 0.5, "mal": 9.0,
        "mal_poll": 2.0, "msteer_look": 2.0, "msteer_poll": 0.5, "manchor_gap": 20}
SIMPLE_HISTORY = {"threads": [{"id": THREAD}], "turns": [{"thread": THREAD, "turn": T1, "status": "completed",
                                                           "ordinal": 1}]}


def given(measurement, session=None, **extra):
    """A run on the named throwaway conversation, the backend's home and holders as given."""
    extra.setdefault("thread", THREAD)
    extra.setdefault("timing", FAST)
    return run_case(measurement, session, **extra)


def history(*turns, items=(), users=(), threads=(THREAD,), **more):
    found = {"threads": [{"id": thread} for thread in threads],
             "turns": [dict(zip(("thread", "turn", "status", "ordinal"), turn)) for turn in turns],
             "items": [dict(zip(("thread", "turn", "item", "type", "payload", "ordinal"), item)) for item in items],
             "users": [dict(zip(("thread", "turn", "item", "text", "client_id", "ordinal"), user)) for user in users]}
    found.update(more)
    return found


def backend(**more):
    found = {"engine_version": "0.155.0", "app_identity": APP, "loaded": "not_loaded", "codex_exe": "C:\\x\\codex.exe"}
    found.update(more)
    return found


class Base(Compare):
    def common(self, measurement):
        """Every probe through the same ways in and out (diffs_advmeasure's `common`, with this seat's methods)."""
        cases = [run_case(measurement), run_case(measurement, {})]
        cases += [run_case(measurement, {"replies": {method: reply for method in METHODS}}, thread=THREAD,
                           timing=FAST) for reply in ODD]
        cases += [run_case(measurement, {"replies": {method: reply for method in METHODS}}, thread=THREAD,
                           timing=FAST, users=[[]]) for reply in RAISES]
        cases += [run_case(measurement, {"open_raises": reply}, thread=THREAD, timing=FAST, users=[[]])
                  for reply in RAISES[:4]]
        cases += [run_case(measurement, {"enter_raises": reply}, thread=THREAD, timing=FAST, users=[[]])
                  for reply in RAISES[:4]]
        cases += [run_case(measurement, {}, thread=THREAD, timing=FAST), run_case(measurement, {}, thread="nope"),
                  run_case(measurement, {}, versions=None, backend={"engine_version": "0.156.0"},
                           windows_build="10.0.22631", timing=FAST),
                  run_case(measurement, {}, versions=None, backend=None),
                  run_case(measurement, {}, versions={"codex_version": ""}),
                  run_case(measurement, {}, dir="$missing", timing=FAST),
                  run_case(measurement, {}, clock={"time": -5.0}, timing=FAST),
                  run_case(measurement, {"takes_home": True, "takes_config": True}, thread=THREAD, timing=FAST,
                           users=[[]], backend=backend(), home=SIMPLE_HISTORY)]
        return cases


class MeasureHeldDiff(Base):
    def test_common(self):
        cases = []
        for measurement in ("M4", "MQO", "MQP", "MQG", "MC1", "MOPEN", "MSTEER", "MSTEER2"):
            cases += self.common(measurement)
        self.held(cases)

    def test_m4(self):
        hook = {"eventName": "Stop", "source": "plugin", "trustStatus": "trusted"}
        listings = [{"data": [{"hooks": [hook]}]}, {"data": [{"hooks": [dict(hook, eventName="stop_")]}]},
                    {"data": [{"hooks": [dict(hook, enabled=False)]}]},
                    {"data": [{"hooks": [dict(hook, trustStatus="managed"), dict(hook, source="user")]}]},
                    {"data": [{"hooks": [dict(hook, trustStatus=5), "x"]}, "y", {"hooks": "z"}]},
                    {"data": [{"hooks": [dict(hook, eventName="ST\u00d6P")]}]}, {"data": "x"}]
        run = {"eventName": "Stop", "source": "plugin", "status": "completed"}
        events = [[completed(THREAD, "t-1", "failed")],
                  [{"method": "hook/started", "params": {"threadId": THREAD, "run": run}},
                   {"method": "hook/completed", "params": {"threadId": THREAD, "run": run}}],
                  [{"method": "hook/completed", "params": {"threadId": OTHER, "run": run}}]]
        notes = [[{"at": 1790000001, "keys": ["session_id", "turn_id", 5], "status": "failed"}],
                 [{"at": 1789999999, "keys": ["session_id"], "status": "failed"}],
                 [{"at": True, "status": "failed"}], [{"at": 1790000000.0, "keys": "session_id", "status": None}],
                 [{"at": 1790000002, "keys": {"stop_hook_active": 1}, "status": "completed"}],
                 [{"at": 1790000002, "keys": 5, "status": "failed"}], ["x", {"at": "now"}], "x"]
        starts = [{"turn": {"id": "t-1"}}, {"turn": {"id": ""}}, RAISES[0], RAISES[1], {"turn": {"id": 5}}, None]
        cases = []
        for listed in listings:
            cases.append(given("M4", {"replies": {"hooks/list": listed, "turn/start": starts[0]},
                                      "events": events}, users=[[]], backend=backend(),
                               hands={"m4_hook_note": [notes[0]]}))
        for start in starts:
            for batch in (events, events[1:], []):
                cases.append(given("M4", {"replies": {"hooks/list": listings[0], "turn/start": start},
                                          "events": batch}, users=[[]], backend=backend(),
                                   hands={"m4_hook_note": [notes[0]]}))
        for note in notes:
            cases.append(given("M4", {"replies": {"hooks/list": listings[0], "turn/start": starts[0]},
                                      "events": events}, users=[[]], backend=backend(), hands={"m4_hook_note": [note]}))
        cases.append(given("M4", {"replies": {"hooks/list": listings[0], "turn/start": starts[0],
                                              "turn/interrupt": RAISES[0], "thread/unsubscribe": RAISES[1]},
                                  "events": [[], [], [], []]}, users=[[]], backend=backend()))
        for users in ([[USER]], [RAISES[4]], None, [[USER, OTHER_USER]]):
            cases.append(given("M4", {"replies": {"hooks/list": listings[0]}}, users=users, backend=backend()))
        cases.append(given("M4", {}, users=[[]], backend={"engine_version": "x"}))
        self.held(cases)

    def test_queue_probes(self):
        added = {"queuedSubmission": {}}
        lists = {"MQO": "00000000-0000-7000-8000-000000000005", "MC1": "00000000-0000-7000-8000-000000000004",
                 "MQG": "00000000-0000-7000-8000-00000000000a"}
        cases = []
        for measurement, client in lists.items():
            waiting = {"data": [{"clientUserMessageId": client}]}
            homes = [history((THREAD, T1, "inProgress", 1)),
                     history((THREAD, T1, "completed", 1), (THREAD, T2, "completed", 2),
                             users=[(THREAD, T2, "u1", "words", client, 1)]),
                     history((THREAD, T1, "completed", 1), users=[(THREAD, T1, "u1", "words " + client, None, 1)]),
                     None]
            for home in homes:
                for queue in ([waiting, {"data": []}], [waiting], [{"data": []}], [{"data": [5, {"x": 1}]}],
                              [waiting, RAISES[0]], [waiting, RAISES[4]]):
                    case = given(measurement, {"replies": {"thread/queue/add": added, "thread/queue/list": queue,
                                                           "thread/goal/get": [{"goal": {"status": "paused"}},
                                                                               {"goal": {"status": "active"}}]}},
                                 users=[[]], backend=backend(), home=home)
                    if home is None:
                        case.pop("home")
                    cases.append(case)
            for users, app, loaded in (([[USER]], APP, "loaded"), ([[]], APP, "loaded"), ([[]], None, "loaded"),
                                       (None, APP, "loaded"), (None, APP, "not_loaded"), ([RAISES[4]], 5, "loaded"),
                                       ([[]], APP, RAISES[4]), ([[OTHER_USER]], {}, "loaded")):
                cases.append(given(measurement, {"replies": {"thread/queue/list": waiting}}, users=users,
                                   backend=backend(app_identity=app, loaded=loaded)))
        cases.append(given("MQG", {"replies": {"thread/goal/get": [{"goal": None}]}}, users=[[]], backend=backend()))
        cases.append(given("MQG", {"replies": {"thread/goal/get": [{"goal": {"status": "paused"}}, {}],
                                               "thread/queue/list": {"data": []}}}, users=[[]],
                           backend=backend(app_identity=None)))
        self.held(cases)

    def test_mqp(self):
        threads = ",".join([THREAD, OTHER, THIRD])
        ids = ["00000000-0000-4000-8000-%012x" % n for n in (1, 2, 3)]
        homes = [history((THREAD, T1, "completed", 1), (OTHER, T2, "completed", 1), threads=(THREAD, OTHER, THIRD),
                         users=[(THREAD, T1, "u1", "w", ids[0], 1), (OTHER, T2, "u2", "w", ids[0], 1)]), None]
        cases = []
        for home in homes:
            for queue in ([{"data": [{"clientUserMessageId": each} for each in ids]}, {"data": []}],
                          [{"data": [{"clientUserMessageId": ids[0]}]}], [{"data": []}], ["x"], [RAISES[0]]):
                for add in ({}, "x", RAISES[0], RAISES[4]):
                    case = given("MQP", {"replies": {"thread/queue/add": add, "thread/queue/list": queue}},
                                 thread=threads, users=[[]], backend=backend(), home=home)
                    if home is None:
                        case.pop("home")
                    cases.append(case)
        for users, loaded in (([[], [USER], []], "not_loaded"), ([[]], "loaded"), ([[], RAISES[4]], "not_loaded"),
                              (None, "loaded"), (None, "not_loaded")):
            cases.append(given("MQP", {}, thread=threads, users=users, backend=backend(loaded=loaded)))
        cases.append(given("MQP", {}, thread=THREAD + "," + OTHER, users=[[]], backend=backend()))
        cases.append(given("MQP", None, thread=THREAD + "," + OTHER, users=[[]], backend=backend()))
        cases.append(given("MQP", {"open_raises": RAISES[0]}, thread=threads, users=[[]], backend=backend()))
        cases.append(given("MQP", {}, users=[[]], backend=backend()))
        self.held(cases)

    def test_mopen_and_steer(self):
        cases = []
        for users in ([[], [], [USER]], [[], [], [], [], [], [], [], []], [[], RAISES[4], [USER, OTHER_USER]],
                      [[USER]], [RAISES[4]], None, [[], [OTHER_USER]]):
            for link in (True, False, "yes", RAISES[4]):
                for loaded in ("loaded", "not_loaded"):
                    cases.append(given("MOPEN", None, users=users, backend=backend(loaded=loaded),
                                       hands={"open_link": [link]}))
        cases.append(given("MOPEN", None, users=[[], [USER]], backend=backend(), hands={"open_link": [True]},
                           timing=dict(FAST, mopen=30.0, mopen_poll=0.3)))
        cases.append(given("MOPEN", None, users=[[]], backend=backend(app_identity=None)))
        running = history((THREAD, T1, "completed", 1), (THREAD, T2, "inProgress", 2),
                          users=[(THREAD, T2, "u1", "w", "00000000-0000-7000-8000-00000000000d", 1)])
        later = history((THREAD, T2, "completed", 2))
        for home in (running, later, history(), None):
            for answer in ({"turnId": T2}, {"turnId": T1}, {"turnId": 5}, "x", RAISES[0], RAISES[1], RAISES[4]):
                case = given("MSTEER", {"replies": {"turn/steer": answer}}, users=[[]], backend=backend(), home=home)
                if home is None:
                    case.pop("home")
                cases.append(case)
            for word in ("steered", "unconfirmed", "broken", "refused", "version_mismatch", "no_pipe", "no_client",
                         "x", 5, RAISES[4]):
                case = given("MSTEER2", None, users=[[]], backend=backend(), home=home, hands={"steer_ipc": [word]})
                if home is None:
                    case.pop("home")
                cases.append(case)
            case = given("MSTEER2", None, users=[[]], backend=backend(), home=home)
            if home is None:
                case.pop("home")
            cases.append(case)
        cases.append(given("MSTEER", {}, users=[[]], backend=backend(), home={"remove": ["thread_history_1.sqlite"]}))
        self.held(cases)


class MeasureHistoryDiff(Base):
    def test_common(self):
        cases = []
        for measurement in ("ME", "MS", "MK", "MO", "MX", "MXA", "MC2", "M3B", "MTOK", "MGAVE"):
            cases += self.common(measurement)
        self.held(cases)

    def test_homes(self):
        kinds = [(THREAD, T1, "i1", "userMessage", {"x": 1}, 1), (THREAD, T1, "i2", "reasoning", {}, 2)]
        homes = [history((THREAD, T1, "completed", 1), items=kinds),
                 history((THREAD, T1, "failed", 1), items=kinds + [(THREAD, T1, "i3", "agentMessage", {}, 3)]),
                 history((THREAD, T1, "weird", 1), items=[(THREAD, T1, "i1", "contextCompaction", {}, 1),
                                                          (THREAD, T1, "i2", "reasoning", {}, 2)]),
                 history((THREAD, T1, "inProgress", 1), items=[(THREAD, T1, "i1", "plan",
                                                               {"steps": [{"status": "completed"},
                                                                          {"status": "pending"}, {"status": 5},
                                                                          {"status": "in_progress"}]}, 1)]),
                 history(), {"remove": ["thread_history_1.sqlite"]},
                 history((THREAD, T1, "completed", 1), edges=[[THREAD, OTHER, "open"], [THREAD, "junk", "x"]],
                         threads=(THREAD, OTHER)),
                 {"threads": [{"id": THREAD, "source": "cli", "thread_source": "subagent", "history_mode": 5,
                               "originator": "codex-tui", "extra_meta": {"cli_version": "0.1"}}]},
                 {"threads": [{"id": THREAD, "source": "exec", "originator": "codex_vscode"}]},
                 {"threads": [{"id": THREAD, "first_hex": b"not json\n".hex()}]}]
        cases = []
        for measurement in ("ME", "MS", "MK", "MO", "MXA", "M3B", "MX"):
            for home in homes:
                for users, holder in (([[]], [False]), ([[USER]], [False]), ([[OTHER_USER]], [True]),
                                      ([[OTHER_USER, USER]], [True]), ([RAISES[4]], [False])):
                    cases.append(given(measurement, {"replies": {"turn/start": {"turn": {"id": T1}},
                                                                 "thread/compact/start": {}},
                                                     "events": [[{"method": "item/started",
                                                                  "params": {"item": {"type": "contextCompaction"}}},
                                                                 completed(THREAD, T1, "completed")]]},
                                       users=users, holder=holder, backend=backend(), home=home))
            cases.append(given(measurement, {}, users=[[OTHER_USER]], holder=[True],
                               backend={"engine_version": "x", "app_identity": {}}, home=homes[0]))
        self.held(cases)

    def test_mc2(self):
        thread_row = {"threads": [{"id": THREAD}]}
        rollout = [{"type": "event_msg", "payload": {"type": "task_started"}},
                   {"type": "event_msg", "payload": {"type": "exec_approval_request"}},
                   {"type": "event_msg", "payload": {"type": "task_complete"}}]
        cases = []
        for home in (dict(history((THREAD, T1, "completed", 1)), append={THREAD: rollout}),
                     dict(history((THREAD, T1, "other", 1)), append={THREAD: rollout[:1]}),
                     thread_row, history(), {"remove": ["state_5.sqlite"]}):
            for timing in (FAST, dict(FAST, mc2=1.0)):
                cases.append(given("MC2", None, backend=backend(), home=home, timing=timing))
        self.held(cases)

    def test_mtok(self):
        def count(total, **more):
            usage = {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 2, "reasoning_output_tokens": 0,
                     "total_tokens": total}
            usage.update(more)
            return {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": usage}}}
        rollouts = [[count(3), count(5)], [count(5), count(3)], [count(3), count(4, input_tokens=True)], [count(3)],
                    [count(3), {"$hex": b'{"x": "token_count"\n'.hex()}, {"$hex": b'"token_count" \xff\n'.hex()},
                     count(9)], [count(2 ** 70), count(2 ** 70 + 1)]]
        schemas = [{"$files": {"a.json": json.dumps({"methods": ["thread/tokenUsage/read", "thread/list"]}),
                               "sub/B.JSON": json.dumps({"x": "thread/x"}), "c.json": "not json",
                               "d.json": "\ufeff{}"}, "$answer": "ok"},
                   {"$files": {"a.json": json.dumps({"m": "thread/list"})}, "$answer": "ok"}, None, RAISES[4]]
        cases = []
        for rollout in rollouts:
            for column, used in ((True, 5), (True, 3), (False, None), (True, "5")):
                home = history((THREAD, T1, "completed", 1), append={THREAD: rollout})
                if column:
                    home["state_sql"] = [["ALTER TABLE threads ADD COLUMN tokens_used"]]
                    home["after_sql"] = [["UPDATE threads SET tokens_used=? WHERE id=?", used, THREAD]]
                cases.append(given("MTOK", None, backend=backend(), home=home,
                                   hands={"scratch_cli": [schemas[0]]}))
        for schema in schemas:
            cases.append(given("MTOK", None, backend=backend(), home=history((THREAD, T1, "completed", 1)),
                               hands={"scratch_cli": [schema]}))
        cases.append(given("MTOK", None, backend=backend(), home={"remove": ["state_5.sqlite"]}))
        self.held(cases)

    def test_mgave(self):
        def failed(thread, turn, info, end=None, completed_at=1790000000):
            return {"thread": thread, "turn": turn, "status": "failed", "ordinal": 1, "completed": completed_at,
                    "error_json": None if info is None else json.dumps({"codexErrorInfo": info}), "end": end}

        def started(turn):
            return {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn}}

        def retry(info, key="codex_error_info"):
            return {"type": "event_msg", "payload": {"type": "stream_error", key: info}}
        lines = [started(T1), retry("server_overloaded"), retry({"server_overloaded": {}}, "codexErrorInfo"),
                 {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": T1}}, started(T2),
                 retry("x_y_z"), retry("bad word"), started(T3)]
        homes = [
            {"threads": [{"id": THREAD}, {"id": OTHER}],
             "turns": [failed(THREAD, T1, "serverOverloaded"), failed(THREAD, T2, "responseTooManyFailedAttempts"),
                       failed(OTHER, T3, {"serverOverloaded": {}}, end=10 ** 9),
                       failed(THREAD, T3, "usageLimitExceeded"), failed(THREAD, "old", "serverOverloaded",
                                                                       completed_at=1)],
             "append": {THREAD: lines}},
            {"threads": [{"id": THREAD}], "turns": [failed(THREAD, T2, "response_too_many_failed_attempts", end=5)],
             "append": {THREAD: [started(T2), retry("serverOverloaded")]}},
            {"threads": [{"id": THREAD, "write_file": False}], "turns": [failed(THREAD, T1, "serverOverloaded")]},
            {"threads": [{"id": THREAD}], "turns": [failed(THREAD, T1, "serverOverloaded")],
             "append": {THREAD: [retry("serverOverloaded")]}},
            {"history_sql": [["INSERT INTO thread_turns (thread_id, turn_id, status, completed_at, error_json) "
                              "VALUES (?,?,?,?,?)", 5, T1, "failed", 1790000000, "not json"]]},
            {"remove": ["thread_history_1.sqlite"]}, history()]
        cases = [given("MGAVE", None, backend=backend(), home=home) for home in homes]
        cases.append(given("MGAVE", None, backend=backend(), home=homes[0], clock={"time": 1790000000.0 + 86400 * 95}))
        self.held(cases)


class MeasureScratchDiff(Base):
    def test_common(self):
        cases = []
        for measurement in ("MB", "MB2", "MF", "MHK", "M4B", "MANCHOR", "MWAKE", "MIMG"):
            cases += self.common(measurement)
        self.held(cases)

    def test_config_probes(self):
        def read(value=None, version="v1", layers=None):
            config = {"model_providers": {"openai": {"request_max_retries": value, "stream_max_retries": value}}}
            if value is None:
                config = {}
            found = {"config": config}
            if version is not None:
                found["version"] = version
            if layers is not None:
                found["layers"] = layers
            return found
        user = [{"name": {"type": "user"}, "version": "u1"}, {"name": {"type": "system"}, "version": "s"}]
        cases = []
        for reads in ([read(), read(8), read(8), read()], [read(version=None, layers=user), read(8.0, None, user)],
                      [read(), read(True)], ["x"], [read(version=True)]):
            for writes in ([{}, {}, {}, RAISES[1]], [{}, {}, {}, RAISES[0]], [{}, {}, {}, {}], ["x"], [RAISES[4]]):
                for takes in (True, False):
                    cases.append(given("MB", {"replies": {"config/read": reads, "config/value/write": writes},
                                              "takes_home": takes}))
        provider = "codex_auto_resume_retries"
        ours = {"config": {"model_provider": provider,
                           "model_providers": {provider: {"request_max_retries": 8, "stream_max_retries": 8}}}}
        for config in (ours, {"config": {"model_provider": "openai"}}, {}):
            for writes in (False, True):
                for thread in (THREAD, None):
                    for account, turn in (({"account": {"type": "chatgpt", "email": "a@b.cd"}},
                                           {"turn": {"id": "t-1"}}), ({"account": None}, {}),
                                          ({"account": {"type": "chatgpt"}}, {"turn": "x"}),
                                          ({"account": {"type": "chatgpt"}}, {"turn": {"id": 7}})):
                        case = given("MB2", {"replies": {"config/read": config, "account/read": account,
                                                         "thread/list": {"data": [{"id": THREAD}]},
                                                         "turn/start": turn,
                                                         "thread/read": {"thread": {"modelProvider": "openai"}}},
                                             "takes_home": True, "takes_config": True, "writes_config": writes,
                                             "events": [[completed(THREAD, "t-1", "completed"),
                                                         completed(THREAD, 7, "completed")]]})
                        if thread is None:
                            case.pop("thread")
                        cases.append(case)
        cases.append(given("MB2", {"takes_home": True}))
        models = [{"data": [{"isDefault": True, "model": "m-default"}]}, {"data": [{"isDefault": True, "id": "x"}]},
                  {"data": [{"isDefault": 1, "model": "m"}, {"isDefault": True, "model": ""}]}, {"data": "x"}]
        for listed in models:
            for resumes in ([{"model": "m-own"}], [{"model": "m-own"}, {"model": "m-default"}, {"model": "m-own"}],
                            [{"model": "m-default"}], [{}]):
                cases.append(given("MF", {"replies": {"model/list": listed, "thread/resume": resumes,
                                                      "turn/start": {"turn": {"id": "t-1"}}},
                                          "events": [[completed(THREAD, "t-1", "completed")]]}))
        self.held(cases)

    def test_schema_probes(self):
        schema = {"definitions": {"HookEventName": {"enum": ["Stop", "PreToolUse", "", 5]},
                                  "HookSource": {"oneOf": [{"const": "plugin"}, {"enum": "user"}]},
                                  "StopHookInput": {"properties": {"session_id": {}, "turnId": {}, "": {}}},
                                  "StopHookOutput": {"properties": {"decision": {"anyOf": [{"const": "block"}]}}}},
                  "$defs": {"x": 5}}
        bad = {"definitions": {"HookEventName": {"enum": 5}}}
        files = [{"$files": {"s.json": json.dumps(schema)}, "$answer": "ok"},
                 {"$files": {"s.json": json.dumps(bad)}, "$answer": "ok"}, {"$files": {}, "$answer": "ok"}, None]
        features = ["plugin_hooks  experimental  true\n", "plugin_hooks stable false\n", "plugin_hooks x\n", "x\n",
                    None, RAISES[4]]
        cases = []
        for found in files:
            for listed in features:
                cases.append(given("MHK", None, hands={"scratch_cli": [found, listed]}))
        for ours in ({"declared": True, "commands": ["run-ours"]}, {"declared": True, "commands": "run"},
                     {"declared": False}, {"commands": 5}, "x", None):
            for hooks in ({"data": [{"hooks": [{"command": "run-ours"}]}]}, [], "x", {"data": ["r"]}):
                cases.append(given("M4B", {"replies": {"hooks/list": hooks}}, hands={"stop_hook": [ours]}))
        self.held(cases)

    def test_anchor_and_wake(self):
        def limits(used, reset):
            return {"rateLimits": {"primary": {"usedPercent": used, "windowDurationMins": 300, "resetsAt": reset},
                                   "secondary": {"usedPercent": 1, "windowDurationMins": 10080,
                                                 "resetsAt": 1790500000}}}
        cases = []
        for replies in ([limits(0, 1790018000), limits(0, 1790018020), limits(1, 1790018040),
                         limits(1, 1790018040)],
                        [limits(5, 1790010000)], [{}], ["x"], [limits(0, 1790018000), limits(0, 1790018020),
                                                         limits(0, 1790018040), limits(0, 1790018060)]):
            for ran in ({"code": 0, "input": 3, "cached": True, "output": 2.0, "folder_empty_after": True},
                        {"code": False}, {"code": 1}, "x", RAISES[4]):
                cases.append(given("MANCHOR", {"replies": {"account/rateLimits/read": replies}},
                                   hands={"anchor_request": [ran]}))
        for power in ({"wake_ac": 1, "wake_dc": True, "on_battery": False, "modern_standby": True, "lid_present": 1},
                      {"on_battery": True}, "x", None):
            for woke in ({"set": True, "fired": True, "slept_seconds": 600, "late_seconds": 3},
                         {"set": True, "fired": True, "slept_seconds": 600.5, "late_seconds": 121},
                         {"set": True, "slept_seconds": 59}, {"set": True, "fired": True, "slept_seconds": True},
                         {"set": 1}, {}, RAISES[4]):
                cases.append(given("MWAKE", None, hands={"power": [power], "wake_after": [woke]}))
        self.held(cases)

    def test_mimg(self):
        ids = ("00000000-0000-7000-8000-00000000000b", "00000000-0000-7000-8000-00000000000c")
        held = history((THREAD, T1, "inProgress", 1), users=[(THREAD, T1, "u1", "w", ids[0], 1)])
        cases = []
        for added in ({"queuedSubmission": {"input": [{"type": "text"}] + [{"type": "localImage"}] * 10}},
                      {"queuedSubmission": {"input": [{"type": "image"}]}}, {"_oversize": True}, "x",
                      [RAISES[1], {"queuedSubmission": {}}], [RAISES[1], RAISES[1]], [RAISES[0]], [RAISES[4]]):
            for queue in ([{"data": []}], [{"data": "x"}]):
                cases.append(given("MIMG", {"replies": {"thread/queue/add": added, "thread/queue/list": queue}},
                                   backend=backend(), home=held))
        self.held(cases)


class MeasureAccountDiff(Base):
    def test_common(self):
        cases = []
        for measurement in ("MAL", "MALR", "MPROFILE", "MSWAP", "MAUTO"):
            cases += self.common(measurement)
        self.held(cases)

    def test_accounts(self):
        signed = {"account": {"type": "chatgpt", "planType": "Plus"}}
        out = {"account": None}
        cases = []
        for reads in ([signed, out, {"account": {"plan_type": "weird"}}], [signed, RAISES[0], out, RAISES[3], signed],
                      [signed], [out], [{}], [{"account": "x"}], [signed, out, RAISES[4]],
                      [{"account": {"planType": 5}}, out, {"account": {}}]):
            cases.append(given("MAL", {"replies": {"account/read": reads}}))
            for restart in ({"reads": 1, "answer": {"outcome": "restarted", "how": "closed"}},
                            {"reads": 2, "answer": {"outcome": "not_ended", "busy": ["queued", "x"]}},
                            {"reads": 0, "answer": {"outcome": "not_started", "how": ["closed"]}},
                            {"reads": 1, "answer": {"outcome": ["x"], "busy": "turn_running"}},
                            {"reads": 0, "answer": {"busy": 5}}, {"reads": 1, "answer": RAISES[4]},
                            {"reads": 3, "answer": "x"}, None):
                cases.append(given("MALR", {"replies": {"account/read": reads + [signed]}}, restart=restart,
                                   backend=backend()))
        for answered in ({"profile_given": True, "account_read": True, "own_account": True, "usage_read": True,
                          "real_file_unchanged": True, "app_unchanged": True, "real_still_signed_in": True,
                          "store_word": "usable"},
                         {"profile_given": True, "app_unchanged": None, "store_word": "x"},
                         {"profile_given": True, "app_unchanged": False, "real_file_unchanged": 1},
                         {"profile_given": 1}, {"store_word": "not_file"}, {"store_word": ["usable"]}, "x", RAISES[4]):
            cases.append(given("MPROFILE", None, hands={"profile_read": [answered]}, backend=backend()))
        for answered in ({"profiles_given": True, "swapped": True, "signed_in_as_target": True, "swapped_back": True,
                          "first_usage_read": True, "looked": True},
                         {"profiles_given": True, "swapped": True, "signed_in_as_target": False},
                         {"profiles_given": True, "swapped": True, "swapped_back": True, "first_usage_read": False},
                         {"profiles_given": True, "swapped": True, "signed_in_as_target": True},
                         {"profiles_given": True, "swapped": True}, {"profiles_given": True}, {},
                         {"store_word": "no_file"}, None):
            cases.append(given("MSWAP", None, hands={"account_swap": [answered]}))
        for answered in ({"engine_accepted": True, "experimental_taken": True, "schema_whole": True,
                          "features_answered": True, "scratch_home_files": 3,
                          "results": {"mhk": "pass", "m4b": "fail", "mtok": "unknown", "nope": "pass", "mw": 5}},
                         {"engine_accepted": True, "experimental_taken": False, "results": {"m1": "pass"}},
                         {"engine_accepted": True, "experimental_taken": True, "schema_whole": True,
                          "scratch_home_files": True},
                         {"results": ["x"]}, {"results": {"m1": ["pass"]}}, {"results": {"x": ["pass"]}},
                         {"engine_accepted": 1}, "x", RAISES[4]):
            cases.append(given("MAUTO", None, hands={"auto_check": [answered]}))
        cases.append(given("MAUTO", None, hands={"auto_check": [{"engine_accepted": True}]},
                           versions=dict(VERSIONS, codex_version="0.160.0")))
        self.held(cases)


if __name__ == "__main__":
    unittest.main()

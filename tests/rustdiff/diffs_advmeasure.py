"""S7.4: the measurement harness (`measure.py`, `evidence.py`) of the v0.6.26 final, held equal on car-adv's
`advmeasure` probe over the tests' kind of fakes only - never a real Codex, turn or Codex home (the owner's Q2 (a)).

Each test sends one batch of cases to both sides (`advmeasure.both`) and compares, case by case, the answer (or the
class raised) and every call the fakes saw in order, then every file left in the evidence folders, byte for byte.
"""
from __future__ import annotations

import itertools
import json
import unittest

from rustdiff import advmeasure

THREAD = "0a1b2c3d-0001-7000-8000-0000000000aa"
OTHER = "0a1b2c3d-0001-7000-8000-0000000000bb"
VERSIONS = {"product_version": "0.6.26", "codex_version": "0.155.0", "windows_build": "10.0.26100"}
RAISES = [{"$raise": {"class": "AdapterError", "code": "protocol_timeout"}},
          {"$raise": {"class": "RefusedByCodex", "method": "thread/queue/list", "code": -32600}},
          {"$raise": {"class": "RefusedByCodex", "method": "thread/goal/get", "code": None}},
          {"$raise": {"class": "SessionRefused"}},
          {"$raise": {"class": "ValueError"}},
          {"$raise": {"class": "EvidenceUnavailable"}}]
ODD = [{}, [], None, "x", 3, {"data": []}, {"data": "x"}, {"goal": {"status": "active"}}, {"goal": {"status": 5}},
       {"goal": "x"}, {"turn": {"id": "t-1"}}, {"turn": {"id": 7}}]


def run_case(measurement, session=None, **extra):
    case = {"op": "run", "measurement": measurement, "dir": "$dir", "versions": VERSIONS, "session": session}
    case.update(extra)
    return case


def completed(thread, turn, status):
    return {"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": turn, "status": status}}}


class Compare(unittest.TestCase):
    maxDiff = 4000

    @classmethod
    def setUpClass(cls):
        advmeasure.build()

    def held(self, cases):
        (want, want_files), (got, got_files) = advmeasure.both(cases)
        self.assertEqual(len(want), len(got))
        for index, (one, two) in enumerate(zip(want, got)):
            if one != two:
                self.fail("case %d differs: %s\nreference: %s\nprobe:     %s" % (
                    index, json.dumps(cases[index])[:600], json.dumps(one)[:1500], json.dumps(two)[:1500]))
        self.assertEqual(want_files, got_files)
        return want


class MeasureEvidenceDiff(Compare):
    def test_pure(self):
        values = [None, True, False, 0, -1, 10 ** 30, 1.5, "", "pass", "fail", "blocked", "completed", "inProgress",
                  "usage_limit", "unknown", "thread-0123abcd", "thread-0123abcd\n", "thread-0123ABCD", "chain-00000000",
                  "record-ffffffff", "record-fffffffff", "x-00000000", "thread/queue/list", "account/rateLimits/read",
                  "usable", "no_file", "plus", "under_1s", "measured", "hello", [], {}, ["pass"], "\u00e9"]
        texts = ["", "0.6.26", "0.155.0", "10.0.26100", "2026-11-27T10:00Z", "C:\\x", "c:/x", "\\\\server", "a\\b",
                 "x@example.com", "a@b.c", "a@b.cd", THREAD, THREAD.upper(), "x" + THREAD, "_" + THREAD,
                 "0123456789ab", "0123456789abc", "0123456789AB", "g0123456789ab", "0123456789ab_",
                 "deadbeef" * 8, "deadbeef" * 9, "note with words", "\u00e90123456789ab", "a" * 300, "\u4e2d\u6587"]
        cases = [{"op": "content_free", "value": value} for value in values]
        cases += [{"op": "no_content", "value": text} for text in texts]
        cases += [{"op": "iso", "value": value} for value in (0, 0.9, 59.999, 1790000000, 1790000000.5,
                                                              951782400, 4102444800, 32536850399, 32536850400,
                                                              -1, -0.5, 86399.99, -43200, -43200.5, -43201, -86400 * 400, 1e18)]
        cases += [{"op": "goal_status", "value": value} for value in ODD]
        events = [[], [completed(THREAD, "t-1", "failed")], [completed(THREAD, "t-1", "weird")],
                  [completed(THREAD, "t-1", 3)], [completed(OTHER, "t-1", "completed")],
                  [{"method": "turn/completed", "params": {"threadId": THREAD, "turn": "x"}}],
                  [{"method": "turn/started"}, completed(THREAD, "t-2", "interrupted"),
                   completed(THREAD, "t-1", "completed")], ["x", None, 3, {"method": "turn/completed"}]]
        for batch, turn in itertools.product(events, (None, "t-1", "t-2")):
            cases.append({"op": "completed_status", "events": batch, "thread": THREAD, "turn": turn})
        for measurement, value in itertools.product(("M1", "MQP", "Nope"), (
                THREAD, THREAD.upper(), "x", None, 5, THREAD + "," + OTHER, THREAD + "," + THREAD,
                ",".join([THREAD, OTHER, THREAD[:-1] + "c", THREAD[:-1] + "d", THREAD[:-1] + "e"]),
                ",".join([THREAD, OTHER, THREAD[:-1] + "c", THREAD[:-1] + "d"]), THREAD + ",")):
            cases.append({"op": "threads_valid", "measurement": measurement, "value": value})
        self.held(cases)

    def test_build_and_write(self):
        good = {"queue_listed": True, "count": 3, "thread_given": False}
        observed = [good, {}, [], None, {"Bad": True}, {"a" * 48: True}, {"a" * 49: True}, {"9x": True},
                    {"ok": 1.5}, {"ok": "words"}, {"ok": "thread-0123abcd"}, {"ok": None}, {"ok": [1]},
                    {"ok": "completed", "b_2": "usage_limit"}]
        notes = [None, "", "  ", "what happened", 5, "C:\\path", THREAD, "\u00e9t\u00e9"]
        cases = []
        for verdict, seen, note in itertools.product(("pass", "fail", "blocked", "maybe"), observed, notes):
            cases.append({"op": "build", "measurement": "M3", "verdict": verdict, "observed": seen, "note": note,
                          "product_version": "0.6.26", "codex_version": "0.155.0", "windows_build": "10.0.26100",
                          "recorded_at": "2026-11-27T10:00Z"})
        for field, value in itertools.product(("product_version", "codex_version", "windows_build", "recorded_at"),
                                              ("C:\\x", THREAD, 5, None, "1.2.3", "a@b.cd")):
            case = {"op": "build", "measurement": "M1", "verdict": "pass", "observed": good,
                    "product_version": "0.6.26", "codex_version": "0.155.0", "windows_build": "10.0.26100",
                    "recorded_at": "2026-11-27T10:00Z"}
            case[field] = value
            cases.append(case)
        for measurement in ("M1", "M2b", "MQP", "Mgave"):
            cases.append({"op": "build_write", "measurement": measurement, "verdict": "blocked", "observed": good,
                          "note": "\u00e9 line\nnext", "product_version": "0.6.26", "codex_version": "0.155.0",
                          "windows_build": "10.0.26100", "recorded_at": "2026-11-27T10:00Z", "dir": "$dir"})
        cases.append(dict(cases[-1], dir="$missing"))
        self.held(cases)

    def test_complete_and_outcome(self):
        def record(**changes):
            found = {"format": "codex-auto-resume-measurement/1", "step": "M1", "verdict": "blocked",
                     "recorded_at": "2026-11-27T10:00Z", "product_version": "0.6.26", "codex_version": "0.155.0",
                     "windows_build": "10.0.26100", "observed": {"a": True}, "note": "n"}
            found.update(changes)
            return found
        seeds = [json.dumps(record(), indent=2).encode(), json.dumps(record()).replace("\n", "\r\n").encode(),
                 json.dumps(record(verdict="pass")).encode(), json.dumps(record(step="M2")).encode(),
                 json.dumps(record(format="other")).encode(), json.dumps(record(codex_version="0.154.0")).encode(),
                 json.dumps(record(codex_version=155)).encode(), json.dumps(record(codex_version=None)).encode(),
                 json.dumps(record(completion={"verdict": "fail"})).encode(), b"[1, 2]", b"not json", b"\xff\xfe",
                 b"\xef\xbb\xbf" + json.dumps(record()).encode(), json.dumps(record(extra=float("nan"))).encode(),
                 json.dumps(record(note="\ud800"), ensure_ascii=True).encode(), b""]
        cases = []
        for seed in seeds:
            for verdict, note, version in (("pass", "as_expected", "0.155.0"), ("fail", "partial", "0.155.0"),
                                           ("blocked", "as_expected", "0.155.0"), ("pass", "nope", "0.155.0"),
                                           ("pass", "as_expected", "155"), ("pass", "as_expected", None)):
                cases.append({"op": "ev_complete", "measurement": "M1", "verdict": verdict, "note": note,
                              "codex_version": version, "recorded_at": "2026-11-27T10:00Z", "dir": "$dir",
                              "seed": {"measurement-M1.json": seed.hex()}})
        cases.append({"op": "ev_complete", "measurement": "M1", "verdict": "pass", "note": "as_expected",
                      "codex_version": "0.155.0", "recorded_at": "C:\\x", "dir": "$dir",
                      "seed": {"measurement-M1.json": seeds[0].hex()}})
        cases.append({"op": "ev_complete", "measurement": "M1", "verdict": "pass", "note": "as_expected",
                      "codex_version": "0.155.0", "recorded_at": "x", "dir": "$dir"})
        for versions, backend in ((VERSIONS, None), (None, {"engine_version": "0.155.0"}), (None, None),
                                  ({"codex_version": "unknown"}, None), ({}, {"engine_version": ""}),
                                  ({"codex_version": 155}, None)):
            for note in ("as_expected", "bad"):
                cases.append({"op": "complete", "measurement": "M1", "verdict": "pass", "note": note,
                              "versions": versions, "backend": backend, "dir": "$dir",
                              "seed": {"measurement-M1.json": seeds[0].hex()}})
        records = [record(), record(verdict="pass"), record(verdict="fail"), record(completion={"verdict": "pass"}),
                   record(completion={"verdict": "blocked"}), record(completion="x"), record(codex_version=5),
                   record(format="x"), record(verdict="pass", completion={"verdict": "fail"}), [], None, "x"]
        cases += [{"op": "outcome", "record": each} for each in records]
        self.held(cases)


class MeasureProbeDiff(Compare):
    def common(self, measurement):
        """Every probe through the same ways in and out: no session, a session that answers {}, odd answers,
        every raise, a failed open and enter, a thread given, versions read from a backend or unreadable."""
        cases = [run_case(measurement), run_case(measurement, {})]
        cases += [run_case(measurement, {"replies": {method: reply for method in METHODS}}) for reply in ODD]
        cases += [run_case(measurement, {"replies": {method: reply for method in METHODS}}) for reply in RAISES]
        cases += [run_case(measurement, {"open_raises": reply}) for reply in RAISES[:4]]
        cases += [run_case(measurement, {"enter_raises": reply}) for reply in RAISES[:4]]
        cases += [run_case(measurement, {}, thread=THREAD), run_case(measurement, {}, thread="nope"),
                  run_case(measurement, {}, versions=None, backend={"engine_version": "0.156.0"},
                           windows_build="10.0.22631"),
                  run_case(measurement, {}, versions=None, backend=None),
                  run_case(measurement, {}, versions={"codex_version": ""}),
                  run_case(measurement, {}, versions={"codex_version": 7, "product_version": "x"}),
                  run_case(measurement, {}, dir="$missing"),
                  run_case(measurement, {}, clock={"time": -5.0})]
        return cases

    def test_simple_probes(self):
        cases = []
        for measurement in ("M1", "M2", "M3", "M5", "M7", "MH", "MA", "MQ", "MT"):
            cases += self.common(measurement)
        for first, second in itertools.product(ODD[:6], ODD[:6]):
            cases.append(run_case("M3", {"replies": {"thread/queue/add": first, "thread/queue/list": second}}))
        self.held(cases)

    def test_m2b(self):
        cases = self.common("M2b")
        goals = [{"goal": {"status": "paused"}}, {"goal": {"status": "active"}}, {"goal": None}, {}]
        queues = [[{"data": [{"clientUserMessageId": "00000000-0000-7000-8000-000000000002"}]}],
                  [{"data": [{"clientUserMessageId": "00000000-0000-7000-8000-000000000002"}]}, {"data": []}],
                  [{"data": "x"}], [RAISES[0]], [RAISES[1]], [RAISES[4]], [{"data": [{"x": 1}, 5]}], [None]]
        for goal, queue in itertools.product(goals, queues):
            cases.append(run_case("M2b", {"replies": {"thread/goal/get": [goal, {"goal": {"status": "active"}}, goal],
                                                      "thread/queue/list": queue}},
                                  timing={"m2b_queue": 3.0, "m2b_poll": 1.0}))
        cases.append(run_case("M2b", {"replies": {"thread/goal/get": goals[0], "thread/queue/list": queues[0]}},
                              timing={"m2b_queue": 2.5, "m2b_poll": 0.7}, thread=THREAD))
        self.held(cases)

    def test_m6(self):
        cases = self.common("M6")
        starts = [{"turn": {"id": "t-1"}}, {"turn": {"id": 5}}, {}, None, RAISES[0], RAISES[1]]
        events = [[], [[completed(SAMPLE, "t-1", "completed")]], [[], [], [completed(SAMPLE, "t-1", "failed")]],
                  [[completed(SAMPLE, "t-2", "completed")], [completed(SAMPLE, "t-1", "x")]],
                  [[completed(OTHER, "t-1", "completed")]], [[{"method": "turn/completed"}], ["x"]]]
        for start, batch in itertools.product(starts, events):
            for interrupt, unsubscribe in ((None, None), (RAISES[0], RAISES[1]), (RAISES[4], None)):
                replies = {"turn/start": start}
                if interrupt is not None:
                    replies["turn/interrupt"] = interrupt
                if unsubscribe is not None:
                    replies["thread/unsubscribe"] = unsubscribe
                cases.append(run_case("M6", {"replies": replies, "events": batch, "declined": 2},
                                      timing={"m6_turn": 1.0, "m6_interrupt": 0.5, "m6_poll": 0.25}))
        cases.append(run_case("M6", {"replies": {"turn/start": starts[0]}, "declined": "x"},
                              timing={"m6_turn": 0.3, "m6_interrupt": 0.2, "m6_poll": 0.1}))
        self.held(cases)

    def test_m6b(self):
        cases = self.common("M6B")
        resumes = [{}, None, {"sandbox": {"type": "workspaceWrite"}, "approvalPolicy": "on-request",
                              "approvalsReviewer": "user", "activePermissionProfile": "p"},
                   {"sandbox": {"type": "x"}, "approvalPolicy": {"granular": 1}, "approvalsReviewer": "auto",
                    "activePermissionProfile": None}, {"sandbox": "readOnly", "approvalPolicy": 5}]
        apps = [None, {"engine_version": "0.155.0"}, {"engine_version": "0.155.0", "app_identity": None},
                {"engine_version": "0.155.0", "app_identity": {"server": {"pid": 1}}},
                {"engine_version": "0.155.0", "app_identity": RAISES[4]}]
        for resumed, app in itertools.product(resumes, apps):
            for start, batch in (({"turn": {"id": "t-1"}}, [[completed(SAMPLE, "t-1", "completed")]]),
                                 ({"turn": {"id": "t-1"}}, []), ({}, [])):
                cases.append(run_case("M6B", {"replies": {"thread/resume": resumed, "turn/start": start},
                                              "events": batch, "declined": 1}, backend=app,
                                      timing={"m6_turn": 0.5, "m6_interrupt": 0.25, "m6_poll": 0.25}))
        self.held(cases)

    def test_mw(self):
        cases = [run_case("MW"), run_case("MW", launcher=[None]), run_case("MW", launcher=["x"]),
                 run_case("MW", launcher=[RAISES[0]]), run_case("MW", launcher=[RAISES[1]]),
                 run_case("MW", launcher=[RAISES[4]]), run_case("MW", {}, launcher=[{}])]
        keys = ("started", "in_job", "job_kills_on_close", "kill_on_close", "survived")
        for bits in itertools.product((True, False), repeat=4):
            facts = dict(zip(("started", "job_kills_on_close", "kill_on_close", "survived"), bits))
            cases.append(run_case("MW", launcher=[facts]))
        cases.append(run_case("MW", launcher=[{key: value for key, value in zip(keys, (1, "", [1], "x", 0.0))}]))
        self.held(cases)


def usage(used=40, reset=1_800_003_600, count=2, listed=True, weekly=None, allowed=None):
    """A usage reply as the tests' `usage()` builds one (test_advanced_measure.py)."""
    bucket = {"limitId": "codex", "planType": "pro",
              "primary": {"usedPercent": used, "windowDurationMins": 300, "resetsAt": reset}}
    if weekly is not None:
        bucket["secondary"] = {"usedPercent": weekly[0], "windowDurationMins": 10080, "resetsAt": weekly[1]}
    credits = [{"id": "credit-1", "grantedAt": 1_799_000_000, "expiresAt": 1_801_000_000, "status": "available"}]
    return {"rateLimitsByLimitId": {"codex": bucket},
            "ordinaryUsageAllowed": used < 100 if allowed is None else allowed,
            "rateLimitResetCredits": {"availableCount": count, "credits": credits[:min(count or 0, 1)] if listed else None}}


class MeasureUsageDiff(Compare):
    def test_panel(self):
        tool = {"name": "open_settings", "_meta": {"openai/outputTemplate": "ui://codex-auto-resume/settings",
                                                   "openai/ui": {"entrypoints": [{"type": "thread"}]}}}
        bare = {"name": "open_settings", "_meta": {"openai/outputTemplate": "ui://codex-auto-resume/settings"}}
        other = {"name": "open_settings", "_meta": {"openai/outputTemplate": "ui://else"}}
        answers = [{"data": [{"tools": {"open_settings": tool}}]}, {"data": [{"tools": [bare]}]},
                   {"data": [{"tools": [other, tool]}]}, {"data": [{"tools": [other]}]}, {"data": [{"tools": "x"}, 5]},
                   {"data": []}, {}, None, RAISES[1], RAISES[0], RAISES[4],
                   {"data": [{"tools": {}}], "nextCursor": "c1"}, {"data": [], "nextCursor": ""},
                   {"data": [{"tools": [{"name": "open_settings", "_meta": {"openai/ui": {"entrypoints": "x"}}}]}]}]
        cases = [run_case("MP2"), run_case("MP3"), run_case("MP1")]
        for first, wide in itertools.product(answers, answers[:9] + [answers[11]]):
            cases.append(run_case("MP1", {"replies": {"mcpServerStatus/list": [first, wide]}}))
        cases.append(run_case("MP1", {"replies": {"mcpServerStatus/list": [{"data": []}] + [
            {"data": [{"tools": {}}], "nextCursor": "c%d" % n} for n in range(12)]}}))
        self.held(cases)

    def test_usage(self):
        cases = self.common_usage()
        read = "account/rateLimits/read"
        running = usage()
        later = usage(reset=1_800_003_900)
        far = usage(reset=1_800_010_000)
        idle = usage(used=0)
        unlisted = usage(listed=False)
        nocount = usage(count=None)
        for replies in ([running, unlisted, unlisted, unlisted], [running, unlisted, later, far],
                        [idle, unlisted, unlisted], [running, running, running], [nocount, nocount],
                        [unlisted, unlisted], [{}, {}], [running, unlisted, {"x": 1}], [None], [RAISES[0]],
                        [running, RAISES[1]], [usage(used=50.5, reset=1_800_000_000.5), usage(listed=False)],
                        [usage(weekly=(20, 1_800_500_000)), usage(listed=False, weekly=(20, 1_800_500_100))]):
            cases.append(run_case("MU", {"replies": {read: replies}}, timing={"mu_spacing": 30.0}))
        self.held(cases)

    def test_spend(self):
        read, consume = "account/rateLimits/read", "account/rateLimitResetCredit/consume"
        cases = self.common_usage("MN") + self.common_usage("MR")
        zero = usage(count=0)
        outcomes = [{"outcome": "noCredit"}, {"outcome": "nothingToReset"}, {"outcome": "reset"},
                    {"outcome": "alreadyRedeemed"}, {"outcome": "x"}, {}, None, RAISES[1]]
        for reads, first, second in itertools.product(
                ([zero], [zero, usage(count=1)], [usage(count=2)], [usage(count=None)], [{}]), outcomes[:5],
                outcomes[:5] + outcomes[6:]):
            cases.append(run_case("MN", {"replies": {read: reads, consume: [first, second]}}))
        full = usage(used=100, count=2)
        for reads in ([full, usage(used=0, count=1, reset=1_800_020_000), usage(used=0, count=1)],
                      [full, usage(used=100, count=1), usage(used=100, count=1)],
                      [full, usage(count=2), usage(count=1)], [usage(used=99)], [usage(used=100, count=0)],
                      [usage(used=100, reset=None)], [usage(used=100, count=None)],
                      [usage(used=100, weekly=(100, 1_800_500_000)), usage(used=0, count=1, weekly=(50, 1_800_500_000))],
                      [None], [{"rateLimitsByLimitId": "x"}]):
            for first, second in ((outcomes[2], outcomes[3]), (outcomes[2], outcomes[2]), (outcomes[0], outcomes[3]),
                                  (outcomes[7], outcomes[3]), (outcomes[2], outcomes[7])):
                cases.append(run_case("MR", {"replies": {read: reads, consume: [first, second]}}, may_spend=True))
        self.held(cases)

    def common_usage(self, measurement="MU"):
        return [run_case(measurement, may_spend=True), run_case(measurement, {}, may_spend=True),
                run_case(measurement, {}), run_case(measurement, {"replies": {"account/rateLimits/read": RAISES[3]}},
                                                    may_spend=True)]


class MeasureLookDiff(Compare):
    def test_looks(self):
        cases = [run_case("MIPC"), run_case("MAWS"), run_case("MCLOUD")]
        for look in ({}, {"exists": True, "opened": True, "frame_read": False, "no_answer": 1}, {"exists": "x"},
                     [], None, "x", RAISES[0], RAISES[4], {"exists": [], "opened": 0.0, "frame_read": [1]}):
            cases.append(run_case("MIPC", ipc=look))
        helps = [None, 5, RAISES[4], "", "Usage: codex app-server\n  --ws CODEX_APP_SERVER_WS_URL",
                 "a Shared Backend switch", "SHARED LOCAL APP-SERVER", "codex_app_server_ws_url",
                 "line\r\nUsage: codex cloud [status]\u2028x", "  usage: codex cloud list\n",
                 "usage: codex cloud\nunknown command", "usage: codex cloudy", "Usage:codex cloud",
                 "usage: codex cloud\x0bstate", "\u0130 usage: codex cloud watch", "usage: codex  cloud"]
        for app, cloud, top in itertools.product(helps[:8], helps[3:], (None, "usage: codex cloud list", "x")):
            cli = {}
            if app is not None:
                cli["app-server --help"] = app
            if cloud is not None:
                cli["cloud --help"] = cloud
            if top is not None:
                cli["--help"] = top
            cases.append(run_case("MAWS", cli=cli))
            cases.append(run_case("MCLOUD", cli=cli))
        self.held(cases)


SAMPLE = "00000000-0000-7000-8000-000000000000"
METHODS = ("thread/loaded/list", "thread/queue/list", "thread/queue/add", "thread/goal/get", "thread/goal/set",
           "account/read", "thread/resume", "turn/start", "turn/interrupt", "thread/unsubscribe")


if __name__ == "__main__":
    unittest.main()

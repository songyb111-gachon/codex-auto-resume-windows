"""S3.2, car-codex's pure readers and file readers held to the reference tag, function by function (through
`leaves.batch`: the same cases to the tag's own functions and to car-codex's).

* the turn rows: `detect`, `normalize`, `judge`, `admissible`, `error_shape` over the usage-limit fixture
  (`tests/fixtures/usage-limit.json`) and generated rows of every shape Codex or a damaged file could hold;
* what a rate-limit snapshot says: `choose_reset` and `parse_usage`, the fixture's among them;
* the words: `_label` (every one of the 1,114,112 code points' `isprintable`, and the cut), `taken_thread_source`,
  `_turn_status`, `epoch`, `_json`;
* which conversations are taken up: `eligibility.*` over every kind and every originator;
* a user message or a queued item that is ours: `later_turn`, `marker_row`, `_item_is_ours`, `_queue_has_marker`;
* the file readers on files of every kind (a BOM, a line cut short, one a megabyte long, bytes that are no UTF-8, CRLF):
  `session_meta`, `reset_scan`, `superseded_in`, `turn_trigger`, `confined`, `continued_id`, `newest_generation`,
  `safe_path` and the git HEAD digest (`workspace.head_digest`).
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import unittest

from rustdiff.codexdiff import A, B, BASE, C
from rustdiff.leaves import Leaves

RECORD: list[str] = []
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "usage-limit.json"
UUIDS = ["0a1b2c3d-0001-7000-8000-%012x" % n for n in range(1, 6)]

SCRIPT = r'''
import json, sys
from pathlib import Path
from codex_auto_resume import failures
from codex_auto_resume.codex import eligibility, labels, payload, paths, rollout, usage, values, workspace

cases = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))


def osx(call):
    def wrapped(*args):
        try:
            return call(*args)
        except OSError:
            raise OSError("os")
    return wrapped


def text(value):
    return None if value is None else str(value)


def row_problem(row, kinds, widened, composed):
    return eligibility.row_problem(row, frozenset(kinds), frozenset(widened), composed)


ops = {
    "codex.detect": payload.detect, "codex.normalize": values.normalize, "codex.admissible": payload.admissible,
    "codex.error_shape": values.error_shape,
    "codex.judge": lambda row, needs, admissible, shapes: payload.judge(row, frozenset(needs), admissible, shapes),
    "codex.later_turn": payload.later_turn, "codex.marker_row": payload.marker_row, "codex.item_is_ours": payload._item_is_ours,
    "codex.queue_has_marker": payload._queue_has_marker, "codex.choose_reset": payload._choose_reset,
    "codex.parse_usage": usage.parse_usage, "codex.label": labels._label,
    "codex.taken_thread_source": lambda value, widened, composed: values.taken_thread_source(value, frozenset(widened), composed),
    "codex.turn_status": values._turn_status, "codex.epoch": values.epoch, "codex.json": values._json,
    "codex.printable": lambda start, stop: "".join("1" if chr(each).isprintable() else "0" for each in range(start, stop)),
    "eligibility.row_problem": row_problem,
    "eligibility.originator_taken": lambda source, first, kinds, widened: eligibility.originator_taken(source, first, frozenset(kinds), frozenset(widened)),
    "eligibility.kind_of": lambda source, payload_, kinds, widened: eligibility.kind_of(source, payload_, frozenset(kinds), frozenset(widened)),
    "eligibility.forked": eligibility.forked, "eligibility.source_taken": lambda source, kinds: eligibility.source_taken(source, frozenset(kinds)),
    "eligibility.widened_originator": lambda originator, widened: eligibility.widened_originator(originator, frozenset(widened)),
    "eligibility.newer_than_engine": eligibility.newer_than_engine,
    "workspace.head_digest": workspace.head_digest,
    "rollout.continued_id": rollout.continued_id,
    "rollout.placed": lambda row, owner, index: rollout.placed(row, owner, index),
    "rollout.taken": lambda chain, rows: rollout.taken(chain, [tuple(row) for row in rows]),
    "rollout.confined": lambda home, thread, raw: text(rollout.confined(home, thread, raw)),
    "rollout.session_meta": osx(lambda path: rollout.session_meta(Path(path))),
    "rollout.reset_scan": lambda path, end, turn, completed: rollout.reset_scan(Path(path), end, turn, completed),
    "rollout.superseded_in": lambda path, turn, limit: rollout.superseded_in(Path(path), turn, limit),
    "rollout.turn_trigger": osx(lambda path, turn: rollout.turn_trigger(Path(path), turn)),
    "paths.newest_generation": osx(lambda home, kind: text(paths.newest_generation(Path(home), kind))),
    "paths.safe_path": lambda path: str(paths._safe_path(Path(path))),
}
finish(cases, ops)
'''

ZOO = [None, True, False, 0, 1, -1, 5, 100, 2 ** 40, 2 ** 63, 2 ** 64, 2 ** 70, 0.0, 0.5, 1.5, 100.0, 1e308, "", "x", " ", "completed",
       "failed", "inProgress", "interrupted", "Failed", [], [1], {}, {"a": 1}, BASE, BASE - 100, BASE + 0.5, float(BASE), 946684800,
       946684799, 4102444800, 4102444801, 10 ** 12, "1788628000"] + UUIDS
ERRORS = [json.dumps({"codexErrorInfo": "usageLimitExceeded"}), json.dumps({"codexErrorInfo": "serverOverloaded"}),
          json.dumps({"codexErrorInfo": {"httpStatusCode": 503}}), json.dumps({"codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 502}}}),
          json.dumps({"codexErrorInfo": {"serverOverloaded": {"retryAfterSeconds": 42}}}), json.dumps({"codexErrorInfo": {"other": 1}, "message": "boom"}),
          json.dumps({"message": "stream disconnected before completion"}), json.dumps({"codexErrorInfo": "unauthorized"}),
          json.dumps({"codexErrorInfo": "badRequest", "message": "x" * 200}), json.dumps({"codexErrorInfo": None, "message": "connection reset by peer"}),
          json.dumps({"codexErrorInfo": 5}), json.dumps({"codexErrorInfo": ["a"]}), json.dumps({"codexErrorInfo": {"type": 5}}),
          json.dumps({"codexErrorInfo": "contextWindowExceeded"}), "[1]", '"x"', "5", "null", "not json", "", None, 7, 2.5, "{" * 3000, "[" * 10000,
          '{"codexErrorInfo":"usageLimitExceeded","n":' + "9" * 5000 + "}", '{"codexErrorInfo":"usageLimitExceeded"} trailing',
          '\ufeff{"codexErrorInfo":"usageLimitExceeded"}', json.dumps({"codexErrorInfo": {"httpStatusCode": 429, "retry_after": 30}}),
          json.dumps({"codexErrorInfo": "Usage_Limit_Exceeded"}), '{"codexErrorInfo":"serverOverloaded","message":"' + "m" * 1048000 + '"}',
          '{"codexErrorInfo": NaN}', '{"codexErrorInfo": "usageLimitExceeded", "codexErrorInfo": "serverOverloaded"}',
          json.dumps({"codexErrorInfo": {"serverOverloaded": {"retryAfterSeconds": 100000}}}),
          json.dumps({"codexErrorInfo": {"serverOverloaded": {"retryAfterSeconds": True}}}),
          json.dumps({"codexErrorInfo": {"responseTooManyFailedAttempts": {"httpStatusCode": 500}}}),
          json.dumps({"codexErrorInfo": "responseStreamDisconnected"}), json.dumps({"codexErrorInfo": "sandboxError"}),
          json.dumps({"codexErrorInfo": {"unauthorized": {}}}), json.dumps({"codexErrorInfo": {"httpStatusCode": "x"}})]


class PureDiff(Leaves):
    def pure(self, cases: list, label: str) -> int:
        path = self.scratch / ("cases-%s.json" % label.replace(" ", "-"))
        path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        done = self.family(SCRIPT, path, label=label, expect_ops=len(cases))
        errors = sum(1 for each in done["results"] if "error" in each)
        RECORD.append("pure %s: %d cases equal (%d answered by an exception, the same class)" % (label, len(cases), errors))
        return len(cases)

    # --------------------------------------------------------------------------------------------- turn rows
    def rows(self, count: int, seed: int) -> list:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))["database_failure"]
        rng = random.Random(seed)
        rows = [dict(fixture)]
        keys = ("thread_id", "turn_id", "status", "started_at", "completed_at", "rollout_ordinal", "error_json")
        for _ in range(count):
            row = dict(fixture)
            for key in rng.sample(keys, rng.randint(1, 4)):
                row[key] = rng.choice(ZOO + ERRORS if key == "error_json" else ZOO + [fixture[key]] * 8)
            if rng.random() < 0.2:
                row["ordinal"] = rng.choice(ZOO)
            if rng.random() < 0.15:
                row["category"] = rng.choice(["usage_limit", "server_5xx", "unknown", "x", None, [], "timeout", "terminal_auth"])
                row["retry_after"] = rng.choice([None, 5, 0, 86400, 86401, True, "5", 2.0])
                row.pop("error_json", None)
            if rng.random() < 0.15:
                row.pop("error_json", None)
                row["error_info"] = rng.choice([None, "usageLimitExceeded", {"httpStatusCode": 500}, "serverOverloaded", 5, []])
                row["message"] = rng.choice([None, "connection reset", 5, "x", "stream disconnected"])
            if rng.random() < 0.1:
                row.pop(rng.choice(keys), None)
            if rng.random() < 0.1:
                row["status"] = "failed"
                row["error_json"] = rng.choice(ERRORS)
            rows.append(row)
        for kind in (None, [], "x", 5, True):
            rows.append(kind)
        return rows

    def test_turn_rows(self):
        cases = []
        for row in self.rows(6000, 11):
            cases += [["codex.detect", row], ["codex.normalize", row], ["codex.admissible", row]]
            if isinstance(row, dict):
                cases += [["codex.error_shape", row], ["codex.judge", row, [], False, False], ["codex.judge", row, ["terminal_auth", "unknown"], True, True],
                          ["codex.judge", row, ["timeout"], False, True]]
        self.pure(cases, "turn rows")
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cases = [["codex.detect", fixture["database_failure"]], ["codex.normalize", fixture["database_failure"]],
                 ["codex.choose_reset", {each["limit_id"]: each for each in fixture["rate_limits"]}, fixture["database_failure"]["completed_at"]]]
        done = self.family(SCRIPT, self.write("fixture", cases), label="fixture", expect_ops=3)
        self.assertEqual(done["results"][0]["ok"]["category"], "usage_limit")
        RECORD.append("pure fixture usage-limit.json: detect, normalize and the reset hint equal (category %s, reset %s)" % (
            done["results"][0]["ok"]["category"], done["results"][2]["ok"]["reset_at"]))

    def write(self, label: str, cases: list) -> Path:
        path = self.scratch / ("cases-%s.json" % label)
        path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        return path

    def test_reset_and_usage(self):
        rng = random.Random(5)
        numbers = [0, 1, 5, 50, 89, 90, 99, 100, 100.0, 101, 100.5, -1, True, None, "x", float(BASE), BASE, BASE - 1, BASE + 1, 10 ** 400, 1.5e308, 2 ** 40]
        resets = [None, BASE, BASE + 3600, BASE - 3600, float(BASE + 5), "x", True, 10 ** 400, 946684799, 4102444801, 1788628000.5, 0, 1, [], 4102444800]
        durations = [None, 300, 10080, 0, -5, 1.5, True, "x", 60, 10 ** 30]
        cases = []
        for _ in range(4000):
            buckets = {}
            for name in rng.sample(["codex", "premium", "other", "x y", "legacy", 5 if False else "a-b_c"], rng.randint(0, 4)):
                limits = {}
                if rng.random() < 0.9:
                    limits["limit_id"] = name
                for slot in ("primary", "secondary"):
                    pick = rng.random()
                    if pick < 0.7:
                        limits[slot] = {"used_percent": rng.choice(numbers), "resets_at": rng.choice(resets)}
                    elif pick < 0.85:
                        limits[slot] = rng.choice([None, 5, [], "x"])
                buckets[name] = limits if rng.random() < 0.95 else rng.choice([[], None, 5, "x"])
            cases.append(["codex.choose_reset", buckets, rng.choice([BASE, BASE - 100, 5, None, "x", BASE + 0.5, 10 ** 30])])
            reply = {}
            if rng.random() < 0.9:
                reply["rateLimitsByLimitId"] = {name: self.bucket(rng, numbers, resets, durations) for name in rng.sample(["codex", "premium", "legacy", "zzz", "codex_other"], rng.randint(0, 3))}
            if rng.random() < 0.4:
                reply["rateLimits"] = self.bucket(rng, numbers, resets, durations)
            if rng.random() < 0.05:
                reply = rng.choice([None, [], "x", 5, {}, {"rateLimitsByLimitId": []}, {"rateLimitsByLimitId": {}}, {"rateLimits": 5}])
            cases.append(["codex.parse_usage", reply])
        self.pure(cases, "reset and usage")

    def bucket(self, rng, numbers, resets, durations):
        bucket = {}
        for slot in ("primary", "secondary"):
            pick = rng.random()
            if pick < 0.6:
                bucket[slot] = {"usedPercent": rng.choice(numbers), "windowDurationMins": rng.choice(durations), "resetsAt": rng.choice(resets)}
            elif pick < 0.8:
                bucket[slot] = None
            elif pick < 0.85:
                bucket[slot] = rng.choice([5, [], "x"])
        if rng.random() < 0.3:
            bucket["spendControlReached"] = rng.choice([True, False, None, 1, "true"])
        if rng.random() < 0.4:
            bucket["rateLimitReachedType"] = rng.choice(["rate_limit_reached", "workspace_owner_credits_depleted", "workspace_member_usage_limit_reached",
                                                          "other", None, 5, [], "workspace_owner_usage_limit_reached", "workspace_member_credits_depleted"])
        return bucket if rng.random() < 0.97 else rng.choice([None, [], "x"])

    # ----------------------------------------------------------------------------------------------- words
    def test_labels_and_words(self):
        cases = [["codex.printable", start, min(start + 0x10000, 0x110000)] for start in range(0, 0x110000, 0x10000)]
        rng = random.Random(3)
        pieces = ["a", "B", " ", "  ", "\t", "\n", "\r", "\x00", "\x1b", "\x7f", "\u00a0", "\u200b", "\u2028", "\u202e", "\ufeff", "\u00e9", "\u4e2d", "\U0001f600", "\ud800",
                  "\ue000", "\u0301", "\u3000", "\u180e", "\u0085", "x" * 30, "\u2026"]
        for _ in range(3000):
            cases.append(["codex.label", "".join(rng.choice(pieces) for _ in range(rng.randint(0, 12)))])
        for length in range(60, 90):
            for tail in ("", " ", "  ", "\u3000", "\u00a0", "\u200b"):
                cases.append(["codex.label", "y" * (length - 1) + tail + "z"])
                cases.append(["codex.label", "y" * length + tail])
                cases.append(["codex.label", "y" * 70 + " " * (length - 70) + "k" if length > 70 else "y" * length])
        cases += [["codex.label", each] for each in (None, 5, 1.5, True, [], {}, [1], "")]
        cases = [case for case in cases if "\ud800" not in json.dumps(case, ensure_ascii=False) or True]
        # lone surrogates cannot cross the pipe as text: drop them from the cases that carry them
        cases = [case for case in cases if not any(isinstance(each, str) and any(0xD800 <= ord(char) < 0xE000 for char in each) for each in case)]
        for value in ZOO + ["failed", "user", "chatgpt_handoff", "agent_created_thread", "subagent", "x" * 64, "x" * 65, "every_desktop", "guardian_review", "Subagent"]:
            for widened in ([], ["every_desktop"], ["other"]):
                for composed in (False, True):
                    cases.append(["codex.taken_thread_source", value, widened, composed])
            cases += [["codex.turn_status", value], ["codex.epoch", value], ["codex.json", value]]
        for text in ERRORS + ['{"a": 1}', "  [1, 2]  ", "\n5\n", "true", '{"a":1}\x00', "1e999", "-Infinity", "[NaN]", '{"a": 1, "a": 2}', '"\\ud800"', '"x' + "y" * 1048576 + '"',
                              '"' + "y" * 1048574 + '"', "\u00a0{}", "{}\u00a0", "\ufeff[]", "\t[]\r\n"]:
            if isinstance(text, str):
                try:
                    json.dumps(json.loads(text), ensure_ascii=False, allow_nan=False).encode("utf-8")
                except (ValueError, RecursionError):
                    try:
                        json.loads(text)
                    except (ValueError, RecursionError):
                        pass                     # not JSON at all: the answer is None, which both write
                    else:
                        continue                 # JSON the answer to which JSON cannot write (a NaN, a lone surrogate)
            cases.append(["codex.json", text])
        self.pure(cases, "labels and words")

    # ------------------------------------------------------------------------------------------ eligibility
    def test_eligibility_functions(self):
        sources = ["vscode", "cli", "exec", None, "x", 5, [], "Subagent"]
        originators = ["Codex Desktop", "codex_work_desktop", "codex-tui", "codex_vscode", "codex_exec", "x", None, 5, [], {}, "o" * 65, "o" * 64, ""]
        kinds = [[], ["cli"], ["ide"], ["cli", "ide"], ["bogus"]]
        cases = []
        rng = random.Random(9)
        for source in sources:
            for originator in originators:
                for first_source in ("vscode", "cli", "exec", None, 5):
                    payload = {"originator": originator, "source": first_source}
                    if rng.random() < 0.4:
                        payload["forked_from_id"] = rng.choice([A, "x", None, 5, A.upper()])
                    for chosen in kinds:
                        widened = rng.choice([[], ["every_desktop"]])
                        cases += [["eligibility.originator_taken", source, payload, chosen, widened], ["eligibility.kind_of", source, payload, chosen, widened]]
            cases += [["eligibility.source_taken", source, chosen] for chosen in kinds]
        cases += [["eligibility.originator_taken", "vscode", each, [], []] for each in (None, [], "x", 5, {})]
        cases += [["eligibility.kind_of", "vscode", each, [], ["every_desktop"]] for each in (None, [], "x", 5)]
        cases += [["eligibility.forked", each] for each in (None, [], {}, {"forked_from_id": A}, {"forked_from_id": "x"}, {"forked_from_id": 5}, {"forked_from_id": A.upper()}, "x")]
        cases += [["eligibility.widened_originator", originator, widened] for originator in originators for widened in ([], ["every_desktop"])]
        versions = ["0.164.0", "0.164.0-alpha.1", "1.0.0", "x", None, 5, "", "0.0.1", "99.99.99", "0.153.4 extra", " 0.2.0", "0.164.0-beta.2", "0.164", "0.164.0.1"]
        engines = ["codex-cli 0.164.0", "codex-cli 0.150.0", "0.164.0", None, 5, "x", "codex-cli 1.0.0-beta.1", "codex-cli 0.164.0-alpha.1", "codex 0.164.0", ""]
        cases += [["eligibility.newer_than_engine", version, engine] for version in versions for engine in engines]
        for source in ("vscode", "cli", None, 5, "x" * 40, "Subagent", "sub\x00agent", "a b"):
            for archived in (0, 1, None, "0", 0.0, 2.5):
                for thread_source in ("user", None, "subagent", "agent_created_thread", "x", "y" * 70, 5):
                    for history in ("paginated", None, "full", 5):
                        row = {"source": source, "archived": archived, "thread_source": thread_source, "history_mode": history}
                        for chosen, widened, composed in (([], [], False), (["cli"], ["every_desktop"], True), ([], ["every_desktop"], False)):
                            cases.append(["eligibility.row_problem", row, chosen, widened, composed])
        self.pure(cases, "eligibility functions")

    # ---------------------------------------------------------------------------------------- our messages
    def test_messages(self):
        rng = random.Random(21)
        marker = "[codex-auto-resume:" + "a" * 64 + "]"
        short = "[codex-auto-resume:" + "b" * 16 + "]"
        proofs = [marker, short, A, "x", "[codex-auto-resume:zz]", None, 5]
        texts = [marker, short, "go " + marker, "x" + short + "y", "no marker", "", 5, None, "\ud800" + marker]
        cases = []
        for _ in range(3000):
            content = rng.choice([[{"type": "text", "text": rng.choice(texts)}], [], [5, None, {"type": "text", "text": rng.choice(texts)}], "x", None, 5,
                                  [{"type": "image", "text": marker}], [{"type": "text"}], [{"text": marker}], [[]]])
            payload = rng.choice([{"type": "userMessage", "content": content, "clientId": rng.choice([None, A, "cid", 5, "bad id", "x" * 65])},
                                  {"type": "agentMessage", "content": content}, {"type": "userMessage"}, [1], None, "x", 5,
                                  {"UserInput": {"content": content, "client_id": rng.choice([None, A, "cid", 5])}},
                                  {"UserInput": {"content": content}, "extra": 1}, {"UserInput": rng.choice([5, [], None, "x"])}, {"Other": {}}])
            proof = rng.choice(proofs)
            if isinstance(proof, str) and not any(0xD800 <= ord(char) < 0xE000 for char in json.dumps(payload, ensure_ascii=False)):
                cases += [["codex.item_is_ours", payload, proof], ["codex.queue_has_marker", payload, proof]]
            row = {"thread_id": rng.choice(ZOO), "turn_id": rng.choice(ZOO), "item_id": "i", "rollout_ordinal": rng.choice(ZOO),
                   "status": rng.choice([each for each in ZOO if each != []]), "first_unset": rng.choice([0, 1, None, True]), "starts_turn": rng.choice([0, 1, None]),
                   "item_json": rng.choice([json.dumps(payload), "not json", None, 5, "x" * 20])}
            if isinstance(proof, str):
                cases.append(["codex.marker_row", row, proof])
            cases.append(["codex.later_turn", {"turn_id": rng.choice(ZOO), "rollout_ordinal": rng.choice(ZOO), "status": rng.choice([each for each in ZOO if each != []]),
                                               "has_first": rng.choice([0, 1, None, True]), "first_is_ours": rng.choice([0, 1, None, True])}])
        self.pure(cases, "our messages")

    def test_placed_taken_continued(self):
        cases = []
        for ordinal in (0, 5, -1, 1 << 40, (1 << 40) + 3, 1 << 62, 2.5, None, True, "5", [], 2 ** 70):
            for owner in (A, None, 5, ""):
                for index in (0, 1, 2, 63):
                    cases.append(["rollout.placed", {"thread_id": B, "turn_id": C, "rollout_ordinal": ordinal, "status": "failed"}, owner, index])
        for chain in ([A], [A, B], [A, B, C], []):
            for rows in ([], [[A, "x"]], [[B, None]], [[C, "path " + B]], [[5, "x"], [None, 5]], [[A, B + B], ["z", C]]):
                cases.append(["rollout.taken", chain, rows])
        names = []
        for owner in (A, B, A.upper(), "x"):
            for other in (B, C, A, B.upper(), "x", ""):
                for prefix in ("", "rollout-2026-10-14T12-00-00-", "-", "_", "x", "rollout-2026-", "\u00e9"):
                    for suffix in (".jsonl", ".JSONL", ".jsonl.bak", "jsonl", ".jsonl ", ".json"):
                        names.append((owner, prefix + owner + "_" + other + suffix))
        names += [(A, "short"), (A, ""), (None, "x"), (5, "x"), (A, 5), (A, None), (A, A + "_" + B + ".jsonl" + "\n")]
        for thread, name in names:
            cases.append(["rollout.continued_id", thread, name])
        self.pure(cases, "placed taken continued")

    # --------------------------------------------------------------------------------------------- files
    def test_file_readers(self):
        folder = self.scratch / "files"
        folder.mkdir()
        meta = {"type": "session_meta", "payload": {"id": A, "originator": "Codex Desktop", "source": "vscode", "thread_source": "user"}}
        line = json.dumps(meta).encode()
        big = lambda size: line[:-2] + b" " * (size - len(line)) + b"}"
        usage = {"used_percent": 100, "resets_at": BASE + 3600}
        token = json.dumps({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {"limit_id": "codex", "primary": usage}}}).encode()
        done = json.dumps({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": B, "error": {"codex_error_info": "usage_limit_exceeded"}}}).encode()
        started = json.dumps({"type": "event_msg", "payload": {"type": "task_started", "turn_id": B, "turn_attribution": {"turn_trigger": "composer"}}}).encode()
        person = json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "hi"}}).encode()
        ours = json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "x [codex-auto-resume:" + "a" * 16 + "]"}}).encode()
        bodies = {
            "plain": line + b"\n", "bom": b"\xef\xbb\xbf" + line + b"\n", "no-newline": line, "crlf": line + b"\r\n", "empty": b"", "newline": b"\n",
            "latin1": b'{"type":"session_meta","payload":{"id":"x","n":"caf\xe9"}}\n', "bad-utf8": b'\xff\xfe\n', "not-json": b"x\n", "list": b"[]\n",
            "limit": big(256 * 1024 - 1) + b"\n", "limit-plus": big(256 * 1024) + b"\n", "limit-no-newline": big(256 * 1024 + 1),
            "big": big(300000) + b"\n", "two-lines": line + b"\n" + line + b"\n", "second": b"\n" + line + b"\n", "deep": b'{"type":"session_meta","payload":' + b"[" * 4000 + b"]" * 4000 + b"}\n",
            "reset": line + b"\n" + token + b"\n" + done + b"\n", "reset-crlf": line + b"\r\n" + token + b"\r\n" + done + b"\r\n",
            "reset-cr": line + b"\r" + token + b"\r" + done + b"\r", "reset-bom": b"\xef\xbb\xbf" + line + b"\n" + token + b"\n" + done + b"\n",
            "reset-junk": line + b"\n" + b"junk\n\xff\n" + token + b"\n" + done + b"\n", "reset-long": line + b"\n" + b" " * 1100000 + b"\n" + token + b"\n" + done + b"\n",
            "reset-no-newline": line + b"\n" + token + b"\n" + done, "started": line + b"\n" + started + b"\n", "started-crlf": line + b"\n" + started + b"\r\n",
            "started-junk": line + b"\n" + b'"task_started"\n' + started + b"\n", "later": line + b"\n" + done + b"\n" + person + b"\n",
            "later-ours": line + b"\n" + done + b"\n" + ours + b"\n", "rollback": line + b"\n" + done + b"\n" + b'{"type":"event_msg","payload":{"type":"thread_rolled_back"}}\n' + person + b"\n",
            "later-bad": line + b"\n" + done + b"\n" + b'{"type":"event_msg"\n' + person + b"\n", "later-long": line + b"\n" + done + b"\n" + b'{"type":"event_msg","x":"' + b"a" * 1100000 + b'"}\n' + person + b"\n",
            "later-exact": line + b"\n" + done + b"\n" + b'{"type":"event_msg","payload":{"type":"user_message"}}' + b" " * (1024 * 1024 - 62) + b"\n",
            "later-exact-plus": line + b"\n" + done + b"\n" + b'{"type":"event_msg","payload":{"type":"user_message"}}' + b" " * (1024 * 1024 - 61) + b"\n" + person + b"\n",
            "later-exact-no-newline": line + b"\n" + done + b"\n" + b'{"type":"event_msg","payload":{"type":"user_message"}}' + b" " * (1024 * 1024 - 60) + b"\n",
            "crazy": b"\x00" * 100, "many": (b'{"type":"event_msg","payload":{"type":"noise"}}\n' * 100000) + done + b"\n" + person + b"\n",
            "tail-big": line + b"\n" + b" " * 40 + b"\n" + (b'{"x":1}\n' * 5) + started + b"\n",
        }
        paths = {}
        for name, body in bodies.items():
            path = folder / ("%s.jsonl" % name)
            path.write_bytes(body)
            paths[name] = str(path)
        paths["missing"] = str(folder / "missing.jsonl")
        paths["folder"] = str(folder)
        cases = []
        for name, path in paths.items():
            size = len(bodies.get(name, b""))
            cases += [["rollout.session_meta", path]]
            for end in (0, 1, 10, size, size - 1, size + 10, -1, None, 1.5, True, "x", 1 << 62, 1 << 70, size // 2):
                for completed in (BASE, None, "x", BASE - 10000):
                    if end is None or isinstance(end, (int, float, str)) or True:
                        cases.append(["rollout.reset_scan", path, end, B, completed])
            for turn in (B, A, "x", None):
                cases.append(["rollout.turn_trigger", path, turn])
            for limit in (None, 100, 1000000, 5 * 1024 * 1024, 40 * 1024 * 1024, 0):
                cases.append(["rollout.superseded_in", path, B, limit])
                cases.append(["rollout.superseded_in", path, A, limit])
        home = self.scratch / "confined-home"
        (home / "sessions" / "2026").mkdir(parents=True)
        for raw in (str(home / "sessions" / ("rollout-%s.jsonl" % A)), str(home / "sessions" / "2026" / ("rollout-%s.jsonl" % A)),
                    "\\\\?\\" + str(home / "sessions" / ("rollout-%s.jsonl" % A)), str(home / ("rollout-%s.jsonl" % A)),
                    str(home / "sessions" / ("rollout-%s.txt" % A)), str(home / "sessions" / ("rollout-%s.JSONL" % A)), str(home / "SESSIONS" / ("rollout-%s.jsonl" % A)),
                    str(home / "sessions" / "x" / ".." / ("rollout-%s.jsonl" % A)), "rollout.jsonl", "", ".", "\x00", str(home / "sessions") + "\x00", None, 5, [], B,
                    str(home / "sessions" / (".%s.jsonl" % A)), str(home / "sessions" / ("%s." % A)), str(home / "sessions" / ("%s.jsonl." % A)),
                    str(home / "sessions" / ("rollout-%s.jsonl" % B)), str(home / "sessions" / ("rollout-%s" % A))):
            for thread in (A, B, "x", None, 5):
                cases.append(["rollout.confined", str(home), thread, raw])
        # the folders `newest_generation` lists
        for number, names in enumerate((["state_5.sqlite"], ["state_5.sqlite", "state_6.sqlite", "state_4.sqlite"], ["state_05.sqlite", "state_5.sqlite"], ["state_5.sqlite", "state_05.sqlite"],
                                        ["state_\u0665.sqlite", "state_4.sqlite"], ["state_\u0665.sqlite", "state_\u0666.sqlite"], ["state_x.sqlite", "xstate_5.sqlite", "state_5.sqlite.bak"],
                                        ["STATE_9.sqlite"], [], ["state_99999999999999999999999.sqlite", "state_99999999999999999999998.sqlite"],
                                        ["thread_history_1.sqlite", "thread_history_10.sqlite", "thread_history_9.sqlite"], ["queue_1.sqlite", "queue_2.sqlite"],
                                        ["state_1.sqlite", "state_1.sqlite-wal"])):
            place = self.scratch / ("generation-%d" % number)
            place.mkdir()
            for name in names:
                (place / name).write_bytes(b"x")
            for kind in ("state", "history", "queue", "bogus"):
                cases.append(["paths.newest_generation", str(place), kind])
        folder_place = self.scratch / "generation-folder"
        (folder_place / "state_7.sqlite").mkdir(parents=True)
        (folder_place / "state_6.sqlite").write_bytes(b"x")
        cases.append(["paths.newest_generation", str(folder_place), "state"])
        cases.append(["paths.newest_generation", str(self.scratch / "nowhere"), "state"])
        cases.append(["paths.newest_generation", str(self.scratch / "generation-0" / "state_5.sqlite"), "state"])
        for raw in ("C:\\a\\b", "C:/a//b/./c/../d", "\\\\?\\C:\\a", str(self.scratch) + "\\a\x00b", "C:\\Users\\..\\Windows", str(self.scratch), str(self.scratch).upper(),
                    str(self.scratch / "generation-0" / ".." / "generation-1"), "\\\\server\\share\\x", "C:\\a\\"):
            cases.append(["paths.safe_path", raw])
        self.pure(cases, "file readers")

    def test_workspace_digests(self):
        base = self.scratch / "heads"
        base.mkdir()
        cwds = []
        for name, writer in {
            "branch": lambda folder: ((folder / ".git").mkdir(), (folder / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n")),
            "worktree": lambda folder: ((folder / "gitdir").mkdir(), (folder / "gitdir" / "HEAD").write_bytes(b"ref: x\n"), (folder / ".git").write_bytes(b"gitdir: gitdir\n")),
            "worktree-abs": lambda folder: ((folder / "gitdir").mkdir(), (folder / "gitdir" / "HEAD").write_bytes(b"ref: x\n"), (folder / ".git").write_bytes(("gitdir: %s\n" % (folder / "gitdir")).encode())),
            "plain": lambda folder: None, "empty-git-file": lambda folder: (folder / ".git").write_bytes(b""), "limit": lambda folder: ((folder / ".git").mkdir(), (folder / ".git" / "HEAD").write_bytes(b"y" * 4096)),
            "over": lambda folder: ((folder / ".git").mkdir(), (folder / ".git" / "HEAD").write_bytes(b"y" * 4097)),
        }.items():
            folder = base / name
            folder.mkdir()
            writer(folder)
            cwds.append(str(folder))
        for suffix in ("", "\\", "/", "\\.", "\\sub\\..", " ", "\n", "\x00"):
            for cwd in list(cwds[:3]):
                cwds.append(cwd + suffix)
        cwds += ["", " ", "x", "C:", "\\\\server\\share", "\\\\?\\UNC\\x\\y", "\\\\?\\" + cwds[0], "\\\\?\\" + cwds[0].replace("\\", "/"), cwds[0].replace("\\", "/"), None, 5, [],
                 "\\\\?\\unc\\x\\y", "relative", "/rooted", cwds[1].upper(), "\u00e9", "C:\\no\\such"]
        self.pure([["workspace.head_digest", each] for each in cwds], "workspace digests")


if __name__ == "__main__":
    unittest.main()

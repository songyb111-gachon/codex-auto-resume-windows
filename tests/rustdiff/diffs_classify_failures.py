"""S2.1, car-policy's classifier: `failures.py`, `reasons.py` and `domain/public.py`'s `self_check`, held to the tag.

* CorpusDiff - the done-check (PLAN 5.3, P2): every structured error the tag's own tests, codexsim and the fixtures
  carry (the codexsim error corpus; every rollout and turn-row fixture), read as `codex/values.normalize` reads a
  turn row, classifies alike: the same category, the same reason (`reasons.get(category)`: its label, whether it is
  recovered, its continuation keys), and the same public code - the error's shape (`failures.shape`: Codex's code, the
  status, the form), the code a self-check names (`unknown_code`) and what the edition's plug may take up of it
  (`takes`, `admits`, `readmits`).
* GeneratedDiff - the same functions over generated errors: every CODES variant in every form Codex writes one, every
  status, unknown tags, messages around each transport phrase with Unicode neighbours, and wrong types.
* ReasonsDiff, SelfCheckDiff - the presentation table and the self-check reader.

The corpus is read out of the reference tag's own tree (`git show TAG:tests/...`), so the final re-diff reads the
final's tests.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess

from rustdiff import core, reference
from rustdiff.leaves import Leaves

RECORD: list[str] = []
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KEYS = {"codexErrorInfo", "error_info", "codex_error_info", "error"}
CALLS = {"classify", "shape", "retry_after", "transient_error"}


def _git(*argv) -> bytes:
    return subprocess.run(["git", *argv], cwd=core.ROOT, capture_output=True, check=True,
                          creationflags=NO_WINDOW).stdout


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _NONE


_NONE = object()


def _json_object(text):
    try:
        found = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return found if isinstance(found, dict) else None


def corpus(tag: str) -> dict:
    """{"rows": [error_json texts], "infos": [[info, message]], "sources": {...}}: every structured error the tag's
    tests and fixtures carry. A row is read as values.normalize reads `error_json`; an info is classified as given."""
    rows, infos, sources = [], [], {"tests": 0, "fixtures": 0}
    names = _git("ls-tree", "-r", "--name-only", tag, "tests").decode("utf-8").split("\n")
    seen_rows, seen_infos = set(), set()

    def writable(value) -> bool:
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            return False
        return True

    def add_row(text):
        if isinstance(text, str) and text not in seen_rows and writable(text):
            seen_rows.add(text)
            rows.append(text)

    def add_info(info, message=None):
        if not writable([info, message]):
            return
        key = json.dumps([info, message], sort_keys=True, ensure_ascii=False)
        if key not in seen_infos:
            seen_infos.add(key)
            infos.append([info, message])

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "error_json" and isinstance(item, str):
                    add_row(item)
                elif key in KEYS:
                    add_info(item, value.get("message") if isinstance(value.get("message"), str) else None)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for name in names:
        if name.endswith(".py"):
            try:
                tree = ast.parse(_git("show", "%s:%s" % (tag, name)).decode("utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            sources["tests"] += 1
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    found = _json_object(node.value)
                    if found is not None and ("codexErrorInfo" in found or "message" in found):
                        add_row(node.value)
                    if found is not None:
                        walk(found)
                elif isinstance(node, (ast.Dict, ast.List, ast.Tuple)):
                    value = _literal(node)
                    if value is not _NONE:
                        try:
                            walk(json.loads(json.dumps(value, default=str)))
                        except (TypeError, ValueError, RecursionError):
                            pass
                elif isinstance(node, ast.Call):
                    callee = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                    arguments = [_literal(each) for each in node.args]
                    if callee in CALLS and arguments and arguments[0] is not _NONE:
                        message = arguments[1] if len(arguments) > 1 and isinstance(arguments[1], str) else None
                        try:
                            add_info(json.loads(json.dumps(arguments[0])), message)
                        except (TypeError, ValueError):
                            pass
                    for keyword in node.keywords:
                        if keyword.arg in ("code", "error_json"):
                            value = _literal(keyword.value)
                            if isinstance(value, str):
                                (add_row if keyword.arg == "error_json" else add_info)(value)
        elif name.endswith((".json", ".jsonl")):
            raw = _git("show", "%s:%s" % (tag, name)).decode("utf-8", "replace")
            sources["fixtures"] += 1
            documents = [raw] if name.endswith(".json") else raw.splitlines()
            for text in documents:
                try:
                    walk(json.loads(text))
                except (ValueError, RecursionError):
                    continue
    return {"rows": rows, "infos": infos, "sources": sources}


# Every case runs the same eleven questions a turn's error is asked across the product.
QUESTIONS = r'''
from codex_auto_resume import failures, reasons

from codex_auto_resume.domain.plug import TAKE_UP
ANSWERS = sorted(set(TAKE_UP) | {"hold", "verified_reset", "bogus"})
KINDS = ["network_transient", "timeout", "rate_limit_transient", "server_5xx", "stream_interrupted"]

def entry(category):
    found = reasons.get(category)
    return {"category": found.category, "recoverable": found.recoverable, "order": found.order,
            "has_reset_time": found.has_reset_time, "configurable": found.configurable, "label_key": found.label_key,
            "standard_key": found.standard_key, "detailed_key": found.detailed_key}

def questions(info, message, cases):
    category = failures.classify(info, message)
    facts = dict(failures.shape(info, message), category=category)
    cases.append(["failures.classify", info, message])
    cases.append(["failures.shape", info, message])
    cases.append(["failures.retry_after", info])
    cases.append(["failures.is_recoverable", category])
    cases.append(["reasons.entry", category])
    cases.append(["failures.unknown_code", {"category": category, "shape": failures.shape(info, message)}])
    cases.append(["failures.takes", facts, KINDS])
    cases.append(["failures.takes", facts, KINDS[:2]])
    for answer in ANSWERS:
        cases.append(["failures.admits", facts, answer])
        cases.append(["failures.readmits", category, answer])
    return category

def norm_facts(facts):
    return {key: (str(value) if key == "form" else value) for key, value in facts.items()}

ops = {
    "failures.classify": failures.classify,
    "failures.shape": lambda info, message: norm_facts(failures.shape(info, message)),
    "failures.retry_after": failures.retry_after,
    "failures.wait_seconds": failures.wait_seconds,
    "failures.is_recoverable": failures.is_recoverable,
    "failures.tag_shape": lambda code: bool(failures.TAG_SHAPE.fullmatch(code)),
    "failures.decision_tag": failures.decision_tag,
    "failures.unknown_code": failures.unknown_code,
    "failures.admits": failures.admits,
    "failures.takes": lambda facts, on: sorted(str(each) for each in failures.takes(facts, lambda kind: kind in on)),
    "failures.readmits": failures.readmits,
    "failures.reset_verified": failures.reset_verified,
    "failures.reset_carried": failures.reset_carried,
    "reasons.entry": entry,
    "reasons.is_recoverable": reasons.is_recoverable,
    "reasons.label_key": reasons.label_key,
    "reasons.has_reset_time": reasons.has_reset_time,
    "reasons.configurable": lambda: list(reasons.configurable()),
}
'''

CORPUS = QUESTIONS + r'''
import json as _json
data = _json.load(open(sys.argv[1], encoding="utf-8"))
cases, categories = [], {}

def parse(text):
    try:
        return _json.loads(text)
    except (ValueError, RecursionError):
        return None

for text in data["rows"]:
    # codex/values.normalize: error_json's object, its codexErrorInfo and its message.
    err = parse(text)
    info = err.get("codexErrorInfo") if isinstance(err, dict) else None
    message = err.get("message") if isinstance(err, dict) else None
    category = questions(info, message, cases)
    categories[category] = categories.get(category, 0) + 1
for info, message in data["infos"]:
    category = questions(info, message, cases)
    categories[category] = categories.get(category, 0) + 1
sys.stderr.write(_json.dumps(categories))
finish(cases, ops)
'''

GENERATED = QUESTIONS + r'''
rng = random.Random(26)
codes = list(failures.CODES) + ["brandNewVariant", "other", "policyRefused", "quotaGone", "x", "A" * 64, "A" * 65,
        "9lives", "user_cancelled", "with space", "", "httpStatusCode", "status", "type", "Ünicode", "contextual"]
statuses = [None, 100, 99, 200, 302, 400, 401, 403, 404, 408, 425, 429, 451, 499, 500, 503, 599, 600, -1, 0,
            True, 429.0, "429", 10 ** 30]
cases = []
for code in codes:
    for status in statuses:
        forms = [code, {"type": code}, {"kind": code, "httpStatusCode": status}, {"code": code, "status": status},
                 {code: status}, {code: {"httpStatusCode": status}}, {code: {"statusCode": status, "retryAfter": 30}},
                 {"variant": code, "status_code": status, "retryAfterSeconds": status},
                 {"tag": code, "http_status_code": status, "retry_after": 7}]
        for info in forms:
            questions(info, None, cases)
for info in [None, False, 0, 1, [], ["badRequest"], {}, {"one": 1, "two": 2}, {"type": 5}, {"type": ""},
             {"httpStatusCode": 503}, {"httpStatusCode": True}, {"retryAfterSeconds": 86400}, {"x": {"retry_after": 86401}},
             {"x": {"retryAfter": 0}}, {"x": [1]}, "", 3.5]:
    questions(info, "connection reset", cases)
phrases = ["deadline exceeded", "timed out", "timeout", "connection reset", "connection refused", "connection closed",
           "broken pipe", "name resolution", "dns error", "dns failure", "temporary failure in name resolution",
           "tls handshake", "handshake failed", "stream disconnected", "stream ended unexpectedly", "incomplete stream",
           "streamed", "timeouts", "dns  error", "connection"]
sides = ["", " ", "x", "_", "1", "é", "́", "ͅ", "Ⅳ", "٣", "-", ".", "\n", "İ", "K", "ǅ", "ß", "Σ", "ꙮ", "‍", "²"]
for phrase in phrases:
    for left in sides:
        for right in sides:
            questions(None, left + phrase + right, cases)
            questions(None, (left + phrase + right).upper(), cases)
for message in [None, "", " ", "x" * 4096 + " timeout", "timeout " + "x" * 4089, "timeout " + "x" * 4088, 5, ["timeout"],
                "Connection Reset by peer", "TLS HANDSHAKE", "ＴＩＭＥＯＵＴ", "timeİout"]:
    questions(None, message, cases)
for code in codes + ["PolicyX", "safetyNet", "AUTHx", "budgetLine", "sİgn"]:
    cases.append(["failures.decision_tag", code])
    if isinstance(code, str):
        cases.append(["failures.tag_shape", code])
for value in [None, 0, 1, 86400, 86401, -5, 2.0, True, "30", 10 ** 20]:
    cases.append(["failures.wait_seconds", value])
for category in sorted(failures.CATEGORIES) + ["bogus", None, 5, [1], {"a": 1}, True]:
    cases.append(["failures.is_recoverable", category])
    cases += [["reasons.entry", category], ["reasons.is_recoverable", category], ["reasons.label_key", category],
              ["reasons.has_reset_time", category]]
cases.append(["reasons.configurable"])
for entry_ in [None, 5, {}, {"category": "unknown"}, {"category": "unknown", "shape": {"form": "tagged", "code": "newThing"}},
               {"category": "unknown", "shape": {"form": "tagged", "code": "badRequest"}},
               {"category": "unknown", "shape": {"form": "tagged", "code": "bad thing"}},
               {"category": "unknown", "shape": {"form": "status_only", "code": "newThing"}},
               {"category": "timeout", "shape": {"form": "tagged", "code": "newThing"}},
               {"category": "unknown", "shape": {"form": "tagged", "code": 5}}, {"category": [1], "shape": {}}]:
    cases.append(["failures.unknown_code", entry_])
odd = [{"category": "unknown", "code": "newThing", "status": "x", "form": "tagged"},
       {"category": "terminal_failure", "code": "responseTooManyFailedAttempts", "status": "500", "form": "tagged"},
       {"category": "terminal_auth", "code": "unauthorized", "status": 401.0, "form": "tagged"},
       {"category": "terminal_auth", "code": "newAuthThing", "status": 401, "form": "tagged"},
       {"category": "terminal_auth", "code": "plainThing", "status": 401, "form": "tagged"},
       {"category": "terminal_invalid", "code": "contextWindowExceeded", "status": None, "form": "tagged"},
       {"category": "unknown", "code": "plainThing", "status": 450.5, "form": "tagged"}, [], None]
for facts in odd:
    for answer in ANSWERS + [None, ["admit"], {"a": 1}, 5]:
        cases.append(["failures.admits", facts, answer])
        cases.append(["failures.readmits", facts if isinstance(facts, str) else "unknown", answer])
for row in [None, {}, {"category": "usage_limit", "reset_at": 10}, {"category": "usage_limit", "reset_at": 10.5},
            {"category": "usage_limit", "reset_at": True}, {"category": "usage_limit", "reset_at": "5"},
            {"category": "usage_limit"}, {"category": "timeout", "reset_at": 1}, [1]]:
    for now in [0, 10, 10.5, 11, 2 ** 53 + 1, "x"]:
        cases.append(["failures.reset_verified", row, now])
for relaxed in ["reset", "capacity", None, 5]:
    for channel in [None, True, False, 0, 1, "", "x", []]:
        cases.append(["failures.reset_carried", relaxed, channel])
finish(cases, ops)
'''

SELF_CHECK = r'''
from codex_auto_resume.domain.public import self_check, SELF_CHECK_FORMAT, WORDS
cases = []
F = SELF_CHECK_FORMAT
for started in [100, 100.0, 100.5, True, "100", None, 10 ** 400, 2 ** 53 + 1]:
    for theirs in [100, 100.0, 100.5, True, "100", None, 2 ** 53 + 1, 9007199254740992.0]:
        for extra in [{}, {"blocked": WORDS[0]}, {"blocked": "nope"}, {"unknown_error": {"code": "newThing", "count": 3}},
                      {"unknown_error": {"code": "new thing", "count": 3}}, {"unknown_error": {"code": "A" * 65, "count": 1}},
                      {"unknown_error": {"code": "x", "count": 10 ** 6}}, {"unknown_error": {"code": "x", "count": 0}},
                      {"unknown_error": {"code": "x", "count": True}}, {"layout_untested": "26.930.1"},
                      {"layout_untested": "-1"}, {"updated_from": "0.6.25"}, {"updated_from": "a" * 33},
                      {"updated_from": "a" * 32}, {"layout_untested": 5}, {"updated_from": "1.2 beta"}]:
            cases.append(["public.self_check", dict({"format": F, "started_at": theirs}, **extra), started])
for value in [None, [], {}, {"format": "other", "started_at": 1, "blocked": WORDS[0]}, "x"]:
    cases.append(["public.self_check", value, 1])
finish(cases, {"public.self_check": self_check})
'''


class CorpusDiff(Leaves):
    def test_the_error_corpus_classifies_alike(self):
        found = corpus(reference.TAG)
        path = self.scratch / "corpus.json"
        path.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
        profile = self.profile("reference-corpus-count")
        counted = reference.run(PRELUDE_COUNT + CORPUS.replace("finish(cases, ops)", ""), path, profile=profile)
        self.assertEqual(counted.returncode, 0, counted.stderr[-3000:].decode("utf-8", "replace"))
        categories = json.loads(counted.stderr.decode("utf-8").strip().splitlines()[-1])
        done = self.family(CORPUS, path, label="corpus", expect_ops=50)
        inputs = len(found["rows"]) + len(found["infos"])
        RECORD.append("classify corpus: %d errors from %s's tests (%d files) and fixtures (%d files) - %d error_json "
                      "rows, %d structured infos - %d cases (category, shape, reason, unknown code, take-up) equal; "
                      "categories %s" % (inputs, reference.TAG, found["sources"]["tests"], found["sources"]["fixtures"],
                                         len(found["rows"]), len(found["infos"]), len(done["cases"]),
                                         json.dumps(categories, sort_keys=True)))


PRELUDE_COUNT = "import json, random, sys\n"


class GeneratedDiff(Leaves):
    def test_generated_errors(self):
        done = self.family(GENERATED, label="generated", expect_ops=1000)
        RECORD.append("classify generated: %d cases (classify, shape, retry_after, admits, takes, readmits, "
                      "decision_tag, unknown_code, reset_verified, reasons) equal" % len(done["cases"]))


class SelfCheckDiff(Leaves):
    def test_self_check(self):
        done = self.family(SELF_CHECK, label="selfcheck", expect_ops=100)
        RECORD.append("self_check: %d cases equal" % len(done["cases"]))

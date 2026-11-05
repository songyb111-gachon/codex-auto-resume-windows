# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The automatic compatibility check (v0.6.22): what a machine can tell of a new Codex with no measurement and no sitting.

Codex updates often, and a capability whose measurement passed on the build before it warns "not measured on this Codex"
until a person sits through that measurement again. Much of what a measurement asks only the app, a usage limit, a
sign-in, a real conversation or a person's eyes can answer. But Codex's own generated schema says, of any build and on a
scratch Codex home, which calls it still offers. So when the Codex in force changes, the watcher asks it - once, on a
thread of its own - and this module records what that showed, as a grade of its own (the owner, 2026-11-02; design in
plans/v0622-autocheck-design.md, which has the table of every measurement). It claims no more than it proved:

* WHOLE: what the measurement asks is what the check asks (MHK). A pass needs no person.
* PART: the route is this edition's own calls on its own server, each one the schema describes. A pass over a person's pass
  on an earlier Codex says "still offers every call"; the words say the check cannot see how Codex behaves. A pass with no
  person's pass ever carries nothing forward: nobody ever saw it work.
* FAILS_ONLY: the question is what the app, the queue or a turn does, so the call being there says nothing - but the call
  gone means the route is broken.
* NONE: no check. The row says why in the design.

An automatic grade is not a measurement. It is not in measured.MEASURED, docs/evidence or the compatibility data, and
neither `arming.verdict` (what narrows a route) nor `registry.offered` (what lets a hidden capability out) reads it. A
failed measurement stays failed. A person's pass on this exact Codex outranks an automatic fail. A fail warns at once and
follows the tripwire every warning follows (arming.TRIPPING, its `parts=False`).

What starts, all from `run_engine`, each with CREATE_NO_WINDOW and CODEX_HOME a new scratch folder removed after it: core's
engine check on that scratch home (official_engine, `--version`, `queue --help`), `app-server generate-json-schema`, and
`features list`. It asks Codex for its version, its own list of calls and its feature list, with no sign-in on that home, and
starts no app server, turn or sign-in. What those three commands do on the network has not been watched: MAUTO runs them on
the real engine, and nothing here says more than that. Only `tend` starts them, only from the watcher's tick, and only for the engine the watcher told the plug (codex/inuse.py), which no
other process is told. `results_for`, what every reader reads, starts nothing.

How often: once for an engine file and REVISION of this table. A run with no answer is tried again after RETRY_AFTER, at
most TRIES times. Any two runs are AT_MOST_EVERY apart, kept on disk, so a watcher restarting asks nothing more.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import threading
import time

from codex_auto_resume import config
from codex_auto_resume.compat.files import _signature, path_digest, write_json_atomic
from codex_auto_resume.compat.model import parse_version, safe_version
from codex_auto_resume.win.kernel import NO_WINDOW

from .codex.protocol import DECLINE_ANSWERS
from .vocabulary import AutoResult, CheckGrade, CheckReach, Measurement, Verdict

FORMAT = "codex-auto-resume-autocheck/1"
FILE = "autocheck.json"                        # in the advanced state folder (config.Paths.advanced_dir), whose files a purge takes
# A new value asks every engine again: raise it when CHECKS changes what a row asks.
REVISION = 1
LOOK_EVERY = 60                                # how often the tick looks whether a run is due, in seconds
AT_MOST_EVERY = 600                            # two runs at least this far apart, whatever else
RETRY_AFTER = 6 * 3600                         # a run with no answer waits this long
TRIES = 3                                      # and is tried this many times for one engine file
CHILD_SECONDS = 60                             # how long each child process has
MAX_BYTES = 64 * 1024                          # the record's own cap
SCHEMA_FILE = "codex_app_server_protocol.schemas.json"
SCHEMA_ARGUMENTS = ("app-server", "generate-json-schema", "--experimental", "--out")
SCHEMA_BYTES = 16 * 1024 * 1024
FEATURE_ARGUMENTS = ("features", "list")
# What a document must hold before any row can fail: one that lists less is not Codex's whole schema.
SANE_METHODS = frozenset({"initialize", "thread/resume", "turn/start"})
SANE_COUNT = 50
RECORD_KEYS = frozenset({"format", "revision", "key", "tries", "tried_at", "engine", "checked_at", "results", "gone"})


@dataclass(frozen=True)
class Row:
    """What one measurement's automatic check asks. Names are this table's own: a fail records these, never a word of
    what Codex wrote."""
    reach: CheckReach = CheckReach.NONE
    methods: tuple = ()                         # methods ClientRequest offers
    params: tuple = ()                          # (method, a field of that method's own params)
    requests: tuple = ()                        # methods ServerRequest may ask of a client
    fields: tuple = ()                          # (a named type, one of its fields)
    words: tuple = ()                           # (a named type, a word it may be)
    feature: str | None = None                  # a name `features list` lists


_QUEUE_ADD = Row(CheckReach.FAILS_ONLY, methods=("thread/queue/add",),
                 params=(("thread/queue/add", "threadId"), ("thread/queue/add", "input"),
                         ("thread/queue/add", "clientUserMessageId")))
_USAGE = "account/rateLimits/read"
_CONSUME = "account/rateLimitResetCredit/consume"
_OUTCOME = "ConsumeAccountRateLimitResetCreditOutcome"
_TURN_CALLS = ("thread/resume", "turn/start", "turn/interrupt", "thread/unsubscribe")
_TURN_PARAMS = (("thread/resume", "threadId"), ("turn/start", "threadId"), ("turn/start", "input"),
                ("turn/start", "clientUserMessageId"), ("turn/interrupt", "threadId"), ("turn/interrupt", "turnId"),
                ("thread/unsubscribe", "threadId"))
# Every word this edition's refusals are made of, in the types Codex takes them as (protocol.DECLINE_ANSWERS).
_REFUSALS = (("CommandExecutionApprovalDecision", "decline"), ("FileChangeApprovalDecision", "decline"),
             ("ReviewDecision", "denied"), ("McpServerElicitationAction", "decline"),
             ("TurnStatus", "completed"), ("TurnStatus", "interrupted"), ("TurnStatus", "failed"))

# Every measurement, once (advanced/tests/test_advanced_autocheck.py). A measurement missing here would be NONE anyway,
# but a new one has to be looked at, as every list of this edition's words has to be.
CHECKS = {
    Measurement.M1: Row(), Measurement.M2B: Row(), Measurement.M3: Row(), Measurement.M5: Row(),
    Measurement.MH: Row(), Measurement.MW: Row(), Measurement.MP1: Row(), Measurement.MP2: Row(),
    Measurement.MP3: Row(), Measurement.MQ: Row(), Measurement.ME: Row(), Measurement.MS: Row(),
    Measurement.MK: Row(), Measurement.MT: Row(), Measurement.MIPC: Row(), Measurement.MO: Row(),
    Measurement.MXA: Row(), Measurement.MB: Row(), Measurement.MC2: Row(), Measurement.MQO: Row(),
    Measurement.MQP: Row(), Measurement.MQG: Row(), Measurement.MTOK: Row(), Measurement.MOPEN: Row(),
    Measurement.MAL: Row(), Measurement.MWAKE: Row(), Measurement.MIMG: Row(), Measurement.MSTEER: Row(),
    Measurement.MSTEER2: Row(), Measurement.MGAVE: Row(),
    # This check's own proof on the real engine: nothing rests on it, and a check does not check itself.
    Measurement.MAUTO: Row(),
    # What the check could answer whole with `--help`, but no capability rests on it: nothing could show the answer.
    Measurement.MAWS: Row(), Measurement.MCLOUD: Row(),
    # The probe's own pass rule (measure._mhk): plugin hooks are a feature, and Stop is one of their events.
    Measurement.MHK: Row(CheckReach.WHOLE, words=(("HookEventName", "stop"),), feature="plugin_hooks"),
    # The route is our own session's calls, on our own server: the schema describes each.
    Measurement.M6: Row(CheckReach.PART, methods=_TURN_CALLS,
                        params=_TURN_PARAMS + (("turn/start", "approvalPolicy"), ("turn/start", "sandboxPolicy")),
                        requests=tuple(DECLINE_ANSWERS), words=_REFUSALS),
    Measurement.M6B: Row(CheckReach.PART, methods=_TURN_CALLS, params=_TURN_PARAMS, requests=tuple(DECLINE_ANSWERS),
                         fields=(("ThreadResumeResponse", "sandbox"), ("ThreadResumeResponse", "approvalPolicy"),
                                 ("ThreadResumeResponse", "approvalsReviewer")),
                         words=_REFUSALS + (("SandboxPolicy", "readOnly"), ("SandboxPolicy", "workspaceWrite"))),
    Measurement.MU: Row(CheckReach.PART, methods=(_USAGE,), params=((_USAGE, "excludeResetCreditDetails"),),
                        fields=(("GetAccountRateLimitsResponse", "rateLimits"),
                                ("GetAccountRateLimitsResponse", "rateLimitResetCredits"),
                                ("RateLimitResetCreditsSummary", "availableCount"),
                                ("RateLimitSnapshot", "primary"), ("RateLimitSnapshot", "secondary"),
                                ("RateLimitWindow", "usedPercent"), ("RateLimitWindow", "resetsAt"),
                                ("RateLimitWindow", "windowDurationMins"))),
    Measurement.MN: Row(CheckReach.PART, methods=(_CONSUME,), params=((_CONSUME, "idempotencyKey"),),
                        words=((_OUTCOME, "noCredit"), (_OUTCOME, "nothingToReset"))),
    Measurement.MR: Row(CheckReach.PART, methods=(_CONSUME,), params=((_CONSUME, "idempotencyKey"),),
                        words=((_OUTCOME, "reset"), (_OUTCOME, "nothingToReset"), (_OUTCOME, "noCredit"),
                               (_OUTCOME, "alreadyRedeemed"))),
    Measurement.MX: Row(CheckReach.PART, methods=("thread/resume", "thread/compact/start", "thread/unsubscribe"),
                        params=(("thread/compact/start", "threadId"),), words=(("ThreadItem", "contextCompaction"),)),
    Measurement.MF: Row(CheckReach.PART, methods=("thread/resume", "model/list", "turn/start", "turn/interrupt",
                                                  "thread/settings/update", "thread/unsubscribe"),
                        params=(("thread/resume", "threadId"), ("turn/start", "model"),
                                ("thread/settings/update", "threadId"), ("thread/settings/update", "model")),
                        fields=(("ModelListResponse", "data"), ("Model", "isDefault"), ("Model", "model"),
                                ("ThreadResumeResponse", "model"))),
    # The question is what is done with the call. Its being there proves nothing; its being gone proves the route broken.
    Measurement.M2: Row(CheckReach.FAILS_ONLY, methods=("thread/goal/set",),
                        params=(("thread/goal/set", "threadId"), ("thread/goal/set", "status"))),
    Measurement.M7: _QUEUE_ADD, Measurement.MC1: _QUEUE_ADD,
    Measurement.M3B: Row(CheckReach.FAILS_ONLY, methods=("turn/start",), params=(("turn/start", "input"),)),
    # v0.6.22 (v0.6.23 audit A-M6): nothing. hooks/list is a call only M4's and M4B's probes make - the capability's
    # route (its plugin declaration and the hook program) never does - so its going proves no route broken, and a FAIL
    # on it would turn a kept-on Continue inside the turn off as "a call its route makes". What the route does rest on,
    # the Stop event in the declaration's schema, is MHK's row, and MHK is among the capability's measurements.
    Measurement.M4: Row(CheckReach.NONE),
    Measurement.M4B: Row(CheckReach.NONE),
    Measurement.MA: Row(CheckReach.FAILS_ONLY, methods=("account/read",)),
    Measurement.MALR: Row(CheckReach.FAILS_ONLY, methods=("account/read",)),
    Measurement.MANCHOR: Row(CheckReach.FAILS_ONLY, methods=(_USAGE,)),
    Measurement.MB2: Row(CheckReach.FAILS_ONLY, methods=("config/read", "account/read")),
    Measurement.MPROFILE: Row(CheckReach.FAILS_ONLY, methods=("account/read", _USAGE)),
    Measurement.MSWAP: Row(CheckReach.FAILS_ONLY, methods=("account/read", _USAGE)),
}


# ---------------------------------------------------------------------------- judging a schema (pure)
def _definition(document, name):
    table = document.get("definitions") if isinstance(document, dict) else None
    if not isinstance(table, dict):
        return None
    found = table.get(name)
    if not isinstance(found, dict):
        nested = table.get("v2")
        found = nested.get(name) if isinstance(nested, dict) else None
    return found if isinstance(found, dict) else None


def _reference(document, schema):
    """`schema`, followed through a `$ref` to what it names, or None where that is not there."""
    target = schema.get("$ref") if isinstance(schema, dict) else None
    if not isinstance(target, str):
        return schema if isinstance(schema, dict) else None
    return _definition(document, target.rsplit("/", 1)[-1])


def _properties(document, schema, depth=0) -> set | None:
    """The field names `schema` has, through `$ref` and its alternatives (a params that may be null is an anyOf); None
    where it describes no object at all."""
    schema = _reference(document, schema)
    if schema is None or depth > 6:
        return None
    found = set(schema["properties"]) if isinstance(schema.get("properties"), dict) else None
    for keyword in ("anyOf", "oneOf", "allOf"):
        for item in schema.get(keyword) or ():
            inner = _properties(document, item, depth + 1)
            if inner is not None:
                found = (found or set()) | inner
    return found


def _variants(schema, depth=0) -> set:
    """The words `schema`'s value may be: its enum or const, the `type` word of an object alternative, and the one key of
    an object alternative named by it (ReviewDecision's `{"denied": ...}`). Words, never anything else of the schema."""
    words = set()
    if not isinstance(schema, dict) or depth > 6:
        return words
    for word in schema.get("enum") or ():
        if isinstance(word, str):
            words.add(word)
    if isinstance(schema.get("const"), str):
        words.add(schema["const"])
    for keyword in ("oneOf", "anyOf"):
        for item in schema.get(keyword) or ():
            words |= _variants(item, depth + 1)
            properties = item.get("properties") if isinstance(item, dict) else None
            if isinstance(properties, dict):
                words |= _variants(properties.get("type"), depth + 1)
                required = item.get("required")
                if isinstance(required, list) and len(required) == 1 and isinstance(required[0], str):
                    words.add(required[0])
    return words


def _offered(document, name) -> dict:
    """{method: its params' schema, or None} of the union `name` (ClientRequest, ServerRequest), from the methods' own
    one-word enums - or {} where there is no such union."""
    union = _definition(document, name)
    found = {}
    for item in (union or {}).get("oneOf") or ():
        properties = item.get("properties") if isinstance(item, dict) else None
        method = properties.get("method") if isinstance(properties, dict) else None
        words = method.get("enum") if isinstance(method, dict) else None
        if isinstance(words, list):
            for word in words:
                if isinstance(word, str):
                    found[word] = properties.get("params")
    return found


def _feature_listed(text, name) -> bool:
    """Whether `codex features list` printed a line for `name`, its first word (measure._feature reads it the same way)."""
    return any((line.replace("|", " ").split() or [""])[0] == name for line in text.splitlines())


def judge_row(row, document, client, server, features) -> tuple:
    """(AutoResult, the names of this row that are gone). A named type that is not there at all is UNKNOWN rather than
    gone: an alpha may rename a type and keep every word in it, and a fail turns a capability off."""
    gone, unknown = [], False
    gone += [method for method in row.methods if method not in client]
    for method, field in row.params:
        if method not in client:
            continue                                    # said once, as the method
        fields = _properties(document, client[method])
        if fields is None:
            unknown = True
        elif field not in fields:
            gone.append("%s.%s" % (method, field))
    gone += [method for method in row.requests if method not in server]
    for name, field in row.fields:
        fields = _properties(document, _definition(document, name))
        if fields is None:
            unknown = True
        elif field not in fields:
            gone.append("%s.%s" % (name, field))
    for name, word in row.words:
        schema = _definition(document, name)
        if schema is None:
            unknown = True
        elif word not in _variants(schema):
            gone.append("%s.%s" % (name, word))
    if row.feature is not None:
        if not isinstance(features, str):
            unknown = True
        elif not _feature_listed(features, row.feature):
            gone.append(row.feature)
    if gone:
        return AutoResult.FAIL, tuple(gone)
    return (AutoResult.UNKNOWN, ()) if unknown else (AutoResult.PASS, ())


def judge(document, features=None) -> dict:
    """{Measurement: (AutoResult, gone)} for every row that asks something, or {} for a document that is not Codex's whole
    schema - no answer at all, never a fail. Pure."""
    client = _offered(document, "ClientRequest")
    if len(client) < SANE_COUNT or not SANE_METHODS <= set(client):
        return {}
    server = _offered(document, "ServerRequest")
    return {measurement: judge_row(row, document, client, server, features)
            for measurement, row in CHECKS.items() if row.reach != CheckReach.NONE}


# ---------------------------------------------------------------------------- the grade (pure)
HERE, FAILED, GONE, STANDS_IN, UNSETTLED = "here", "failed", "gone", "stands_in", "unsettled"


def _hand(measurement, table):
    entry = table.get(measurement) if isinstance(table, dict) else None
    return entry if isinstance(entry, tuple) and len(entry) == 2 else (None, None)


def settled(measurement, version, table, results) -> str:
    """How one measurement stands for the Codex `version`, by the design's five rules, first that holds: failed by a
    person on any Codex; passed by a person on this one; gone by the automatic check; carried by the automatic check; or
    unsettled. `results` are this very engine's (`results_for`)."""
    verdict, measured_on = _hand(measurement, table)
    if verdict == Verdict.FAIL:
        return FAILED
    if verdict == Verdict.PASS and version is not None and measured_on == version:
        return HERE
    found = (results or {}).get(measurement)
    if found == AutoResult.FAIL:
        return GONE
    if found == AutoResult.PASS:
        reach = CHECKS.get(measurement, Row()).reach
        if reach == CheckReach.WHOLE or (reach == CheckReach.PART and verdict == Verdict.PASS):
            return STANDS_IN
    return UNSETTLED


def grade(measurements, version, table, results) -> tuple:
    """(CheckGrade, the oldest earlier Codex a person measured it on, or None) for a capability that rests on
    `measurements`. Pure."""
    if not measurements:
        return CheckGrade.NONE, None
    results = results or {}
    each = {measurement: settled(measurement, version, table, results) for measurement in measurements}
    words = set(each.values())
    if FAILED in words:
        if any(results.get(measurement) == AutoResult.FAIL for measurement in measurements):
            return CheckGrade.FAILED, None
        offered = any(word == FAILED and results.get(measurement) == AutoResult.PASS
                      for measurement, word in each.items())
        return (CheckGrade.FAILED_STILL_OFFERED if offered else CheckGrade.FAILED), None
    if GONE in words:
        return CheckGrade.CHECK_FAILED, None
    if UNSETTLED in words:
        offered = all(word != UNSETTLED or results.get(measurement) == AutoResult.PASS
                      for measurement, word in each.items())
        return (CheckGrade.OFFERED_ONLY if offered else CheckGrade.UNMEASURED), None
    if STANDS_IN not in words:
        return CheckGrade.MEASURED, None
    earlier = [_hand(measurement, table)[1] for measurement, word in each.items() if word == STANDS_IN]
    earlier = [found for found in earlier if isinstance(found, str)]
    return CheckGrade.AUTO_CHECKED, (min(earlier, key=_order) if earlier else None)


def _order(version) -> tuple:
    return tuple(parse_version(version) or ()), version


# ---------------------------------------------------------------------------- the record: one writer, read whole
def _path(paths) -> Path:
    return Path(paths.advanced_dir) / FILE


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _shaped(value) -> dict | None:
    """The record `value`, or None for one wrong in any part: a record is read whole or not at all."""
    if not isinstance(value, dict) or set(value) != RECORD_KEYS or value["format"] != FORMAT:
        return None
    if type(value["revision"]) is not int or type(value["tries"]) is not int or not _number(value["tried_at"]):
        return None
    if value["engine"] is not None and (safe_version(value["engine"]) is None or not _number(value["checked_at"])):
        return None
    results, gone = value["results"], value["gone"]
    if not isinstance(results, dict) or not isinstance(gone, dict):
        return None
    known = {str(measurement) for measurement in CHECKS}
    words = {str(word) for word in AutoResult}
    if not all(name in known and word in words for name, word in results.items()):
        return None
    if not all(name in known and isinstance(names, list) and all(isinstance(each, str) for each in names)
               for name, names in gone.items()):
        return None
    return value


def read_record(paths) -> dict | None:
    """The record as the watcher last wrote it, or None. Starts nothing."""
    try:
        path = _path(paths)
        if os.stat(path).st_size > MAX_BYTES:
            return None
        return _shaped(json.loads(path.read_bytes().decode("utf-8")))
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def results_for(paths, engine) -> dict:
    """{Measurement: AutoResult} for exactly the Codex `engine` and this REVISION of the table, or {} - what every reader
    reads. Starts nothing, and no other Codex's answer ever counts."""
    record = read_record(paths) if isinstance(engine, str) else None
    if record is None or record["engine"] != engine or record["revision"] != REVISION:
        return {}
    return {Measurement(name): AutoResult(word) for name, word in record["results"].items()}


def diagnostics(paths) -> dict | None:
    """What Diagnostics' export says of the last check: the engine, when, how many tries, each measurement's word and what
    was gone. Codes and this table's own names; no path. None where no check ever wrote."""
    record = read_record(paths)
    if record is None:
        return None
    return {"engine": record["engine"], "checked_at": record["checked_at"], "tries": record["tries"],
            "results": dict(record["results"]), "gone": dict(record["gone"])}


def _write(paths, record) -> None:
    """The record, whole, in config/advanced/, which is made and marked as ours first, as the state's own opening makes it
    (state/session.py): a run may be the first thing this edition ever writes, and a purge takes only a marked folder."""
    paths.ensure()
    folder = Path(paths.advanced_dir)
    if config.is_link(folder) or (folder.exists() and not paths.confined(folder)):
        raise OSError("the advanced state directory is a link or escapes the home")
    folder.mkdir(exist_ok=True)
    marker = folder / config.OWNER_MARKER
    if not marker.exists():
        marker.write_text(config.OWNER_TEXT, encoding="utf-8")
    write_json_atomic(_path(paths), record, "autocheck")


# ---------------------------------------------------------------------------- the one run
def _engine_key(exe) -> list | None:
    signature = _signature(exe)
    digest = path_digest(exe)
    return [digest] + list(signature) if signature and digest else None


def due(record, key, now) -> bool:
    """Whether a run is due for the engine file `key` at `now`. Pure."""
    if key is None:
        return False
    if record is None:
        return True
    since = now - record["tried_at"]
    since = math.inf if since < 0 else since            # a clock put back owes no wait
    if record["key"] == key and record["revision"] == REVISION:
        return record["engine"] is None and record["tries"] < TRIES and since >= RETRY_AFTER
    return since >= AT_MOST_EVERY


def _schema_of(folder) -> dict | None:
    path = Path(folder) / SCHEMA_FILE
    try:
        found = os.lstat(path)
        if not stat.S_ISREG(found.st_mode) or found.st_size > SCHEMA_BYTES:
            return None
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _child(backend, arguments, scratch):
    """What the engine printed to one set of arguments, with core's own options and environment, or None."""
    try:
        done = subprocess.run(backend._argv() + list(arguments), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                              timeout=CHILD_SECONDS, creationflags=NO_WINDOW, shell=False, cwd=str(scratch),
                              env=backend._environment())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return done.stdout if done.returncode == 0 else None


def ask_engine(exe, scratch) -> dict:
    """What the codex.exe `exe` answered, every child on a Codex home inside the new folder `scratch`: {"backend", "home",
    "out", "version", "schema_answered", "schema_written", "features_answered", "answer"}. The one way the check asks, the
    run's and MAUTO's. Raises as core's engine check does: official_engine, --version, queue --help."""
    from codex_auto_resume.codex.transport import Backend
    home, out = Path(scratch) / "codex-home", Path(scratch) / "schema"
    home.mkdir()
    out.mkdir()
    backend = Backend(home, exe)
    backend._compatible()
    asked = {"backend": backend, "home": home, "out": out, "version": safe_version(backend.engine_version),
             "schema_answered": False, "schema_written": False, "features_answered": False, "answer": {}}
    if asked["version"] is None:
        return asked
    asked["schema_answered"] = _child(backend, SCHEMA_ARGUMENTS + (str(out),), scratch) is not None
    document = _schema_of(out) if asked["schema_answered"] else None
    if document is None:
        return asked
    asked["schema_written"] = True
    features = _child(backend, FEATURE_ARGUMENTS, scratch)
    asked["features_answered"] = features is not None
    asked["answer"] = judge(document, features)
    return asked


def run_engine(exe, scratch) -> tuple | None:
    """(the version the engine names, judge's answer) for the codex.exe `exe`, or None for no answer: an engine
    official_engine does not accept, a child that failed, a schema not written or not whole. Never a fail, for any of
    those: it says nothing of a call."""
    asked = ask_engine(exe, scratch)
    return (asked["version"], asked["answer"]) if asked["version"] and asked["answer"] else None


def _bare_schema(backend, arguments, scratch) -> bool:
    """Whether one form of the schema's command, `arguments` and a new folder after them, runs at all: for MAUTO to say
    why the check's own form did not."""
    out = Path(scratch) / "schema-again"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    try:
        done = subprocess.run(list(arguments) + [str(out)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=CHILD_SECONDS, creationflags=NO_WINDOW, shell=False,
                              cwd=str(scratch), env=backend._environment())
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return done.returncode == 0


def probe_engine(exe) -> dict:
    """The check's own commands on the real engine, for MAUTO, on a scratch home removed after: whether each answered and
    what it found, and - only where the schema's command did not answer - which of `--experimental` and core's `-c` options
    it would not take. Booleans, counts and this table's own words: never a path or a word Codex wrote. Writes no record of
    the check's own: the watcher's stays the watcher's."""
    from codex_auto_resume.codex.pairing import official_engine
    found = {"official": official_engine(exe)[0] is True, "engine_accepted": False, "version": None,
             "schema_answered": False, "experimental_taken": False, "schema_written": False, "schema_whole": False,
             "features_answered": False, "options_without_flag": None, "flag_without_options": None,
             "scratch_home_files": None, "scratch_home_signed_in": None, "results": {}}
    scratch = tempfile.mkdtemp(prefix="car-mauto-")
    try:
        asked = ask_engine(exe, scratch)
        found.update(engine_accepted=True, version=asked["version"], schema_answered=asked["schema_answered"],
                     experimental_taken=asked["schema_answered"], schema_written=asked["schema_written"],
                     schema_whole=bool(asked["answer"]), features_answered=asked["features_answered"],
                     results={str(measurement): str(word) for measurement, (word, _gone) in asked["answer"].items()})
        backend = asked["backend"]
        if not asked["schema_answered"]:
            options = backend._argv()
            found["options_without_flag"] = _bare_schema(
                backend, options + [word for word in SCHEMA_ARGUMENTS if word != "--experimental"], scratch)
            found["flag_without_options"] = _bare_schema(backend, options[:1] + list(SCHEMA_ARGUMENTS), scratch)
        files = [path for path in asked["home"].rglob("*") if path.is_file()]
        found["scratch_home_files"] = len(files)
        # Whether the scratch home holds a sign-in file - by codex/authfile's name, the one module that names it.
        from .codex import authfile
        found["scratch_home_signed_in"] = (asked["home"] / authfile.NAME).exists()
    except Exception:
        pass
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return found


def _attempt(paths, key, tries, now) -> dict:
    return {"format": FORMAT, "revision": REVISION, "key": key, "tries": tries, "tried_at": now, "engine": None,
            "checked_at": None, "results": {}, "gone": {}}


def run_once(paths, exe, record, *, clock=time.time) -> None:
    """One run for `exe`, whose attempt `record` is already written: the answer written over it, and the scratch folder
    gone. Nothing raises out of it: a run with no answer leaves the attempt, which waits for its next try."""
    scratch = None
    try:
        scratch = tempfile.mkdtemp(prefix="car-autocheck-")
        found = run_engine(exe, scratch)
    except Exception:
        found = None
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
    if found is None:
        return
    version, answer = found
    done = dict(record, engine=version, checked_at=clock(),
                results={str(measurement): str(word) for measurement, (word, _gone) in answer.items()},
                gone={str(measurement): list(names) for measurement, (_word, names) in answer.items() if names})
    try:
        _write(paths, done)
    except OSError:
        pass


# {an installation's home: its run's thread}, and when its tick last looked.
_RUNNING = {}
_LOOKED = {}
_LOCK = threading.Lock()


def tend(paths, *, clock=time.time) -> bool:
    """Once a tick, from the watcher alone (runtime.Runtime.tick): start a run where one is due for the engine the
    watcher told the plug. Whether one started. Returns at once: the run has a thread of its own, so a slow engine never
    holds a tick. Where the watcher told nothing there is nothing to check, and nothing is read."""
    from .codex import inuse
    told = inuse.told(paths)
    if told is None:
        return False
    home, now = Path(paths.home), clock()
    with _LOCK:
        if 0 <= now - _LOOKED.get(home, -math.inf) < LOOK_EVERY:
            return False
        _LOOKED[home] = now
        running = _RUNNING.get(home)
        if running is not None and running.is_alive():
            return False
        exe = told[0]
        key, record = _engine_key(exe), read_record(paths)
        if not due(record, key, now):
            return False
        same = record is not None and record["key"] == key and record["revision"] == REVISION
        attempt = _attempt(paths, key, record["tries"] + 1 if same else 1, now)
        # Written before it starts, so that a check that hangs or a watcher that dies waits like one that answered.
        _write(paths, attempt)
        thread = threading.Thread(target=run_once, args=(paths, exe, attempt), kwargs={"clock": clock},
                                  name="codex-auto-resume-autocheck", daemon=True)
        _RUNNING[home] = thread
        thread.start()
    return True

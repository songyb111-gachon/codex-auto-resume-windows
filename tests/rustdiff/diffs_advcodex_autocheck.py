"""S7.2c: autocheck.py (the automatic compatibility check) held equal to the v0.6.26 final.

* the whole CHECKS table, row by row (the reach, every method, param, request, field, word and feature);
* `judge` over generated schemas: a whole one (every call and word each row asks, ClientRequest past SANE_COUNT), each
  name taken away one at a time, the types moved under `v2`, reached through `$ref` chains and `anyOf`/`oneOf`/`allOf`,
  nested past the depth of six, keywords of every JSON type (a truthy number is the TypeError Python's iteration
  raises), and `features list` texts in every line-break and bar form;
* the record: `read_record`, `results_for` and `diagnostics` over files right and wrong in every key and type (an int past
  a float's reach is the OverflowError, a nesting past the interpreter's reach the RecursionError the tag lets out);
  `due` over records, keys and clocks; `_write` over homes whose folders are right, missing, a file or marked;
* the run: `run_engine`, `probe_engine` and `tend` over fake engines (car-adv's `advfake`, signed by the world's stand-in
  signer or not) - an engine that answers whole, one whose schema lacks a call, one with no schema, a refused schema,
  a failed `features list`, an unofficial engine, one whose queue lacks a flag, one whose version is no safe word -
  with the record each leaves compared byte for byte (`tried_at` and `checked_at` on a pinned clock) and every child
  each side started compared argument by argument.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_autocheck`.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import random

from rustdiff.advcodex import AdvCodexDiff, Engine

RECORD: list = []
SIGNER = "OpenAI OpCo, LLC"
NOW = 1_790_000_000.0
DECLINES = ["item/commandExecution/requestApproval", "item/fileChange/requestApproval",
            "item/permissions/requestApproval", "execCommandApproval", "applyPatchApproval",
            "item/tool/requestUserInput", "mcpServer/elicitation/request"]
PARAMS = {
    "thread/resume": ["threadId"], "turn/start": ["threadId", "input", "clientUserMessageId", "approvalPolicy",
                                                  "sandboxPolicy", "model"],
    "turn/interrupt": ["threadId", "turnId"], "thread/unsubscribe": ["threadId"],
    "account/rateLimits/read": ["excludeResetCreditDetails"], "account/rateLimitResetCredit/consume": ["idempotencyKey"],
    "thread/compact/start": ["threadId"], "thread/settings/update": ["threadId", "model"],
    "thread/goal/set": ["threadId", "status"], "thread/queue/add": ["threadId", "input", "clientUserMessageId"],
    "model/list": [], "account/read": [], "config/read": [], "initialize": [],
}
TYPES = {
    "ThreadResumeResponse": ["sandbox", "approvalPolicy", "approvalsReviewer", "model"],
    "GetAccountRateLimitsResponse": ["rateLimits", "rateLimitResetCredits"],
    "RateLimitResetCreditsSummary": ["availableCount"], "RateLimitSnapshot": ["primary", "secondary"],
    "RateLimitWindow": ["usedPercent", "resetsAt", "windowDurationMins"], "ModelListResponse": ["data"],
    "Model": ["isDefault", "model"],
}
WORDS = {
    "CommandExecutionApprovalDecision": {"enum": ["accept", "decline", "cancel"]},
    "FileChangeApprovalDecision": {"enum": ["accept", "decline"]},
    "ReviewDecision": {"oneOf": [{"type": "string", "enum": ["approved"]},
                                 {"type": "object", "required": ["denied"], "properties": {"denied": {}}}]},
    "McpServerElicitationAction": {"const": "decline"},
    "TurnStatus": {"enum": ["completed", "interrupted", "failed", "inProgress"]},
    "SandboxPolicy": {"oneOf": [{"type": "object", "properties": {"type": {"const": "readOnly"}}},
                                {"type": "object", "properties": {"type": {"enum": ["workspaceWrite"]}}}]},
    "ConsumeAccountRateLimitResetCreditOutcome": {"enum": ["reset", "nothingToReset", "noCredit", "alreadyRedeemed"]},
    "ThreadItem": {"anyOf": [{"properties": {"type": {"enum": ["contextCompaction"]}}}]},
    "HookEventName": {"enum": ["stop", "start"]},
}
FEATURES = "Feature          Stage   Enabled\nplugin_hooks     stable  true\nother  beta  false\n"


def whole() -> dict:
    """A schema that holds every call, field and word the check asks, and enough methods to be Codex's whole one."""
    definitions = {}
    client = []
    methods = list(PARAMS) + ["extra/%d" % n for n in range(45)]
    for method in methods:
        name = "Params_" + method.replace("/", "_")
        definitions[name] = {"type": "object", "properties": {field: {} for field in PARAMS.get(method, ["x"])}}
        client.append({"type": "object", "properties": {"method": {"enum": [method]}, "params": {"$ref": "#/definitions/" + name}}})
    definitions["ClientRequest"] = {"oneOf": client}
    definitions["ServerRequest"] = {"oneOf": [{"properties": {"method": {"enum": [method]}, "params": {}}}
                                              for method in DECLINES]}
    for name, fields in TYPES.items():
        definitions[name] = {"type": "object", "properties": {field: {} for field in fields}}
    definitions.update(copy.deepcopy(WORDS))
    return {"definitions": definitions}


def schemas(rng) -> list:
    """(label, document, features) of every schema the judge is asked of."""
    base = whole()
    out = [("whole", base, FEATURES), ("whole, no features", base, None), ("whole, empty features", base, "")]
    for text in ("| plugin_hooks | stable | true |\r\n", "x\r\nplugin_hooks\r\n", "x\x0bplugin_hooks y", "x plugin_hooks",
                 "x\x85plugin_hooks", "plugin_hooks_x stable", " plugin_hooks", "\tplugin_hooks\t", "plugin_hooks　x",
                 "a|plugin_hooks", "PLUGIN_HOOKS", "x\rplugin_hooks", "x\x1cplugin_hooks", " plugin_hooks"):
        out.append(("features %r" % text, base, text))
    defs = base["definitions"]
    for index, item in enumerate(defs["ClientRequest"]["oneOf"]):
        made = copy.deepcopy(base)
        del made["definitions"]["ClientRequest"]["oneOf"][index]
        out.append(("no client %d" % index, made, FEATURES))
    for name in list(defs):
        if name in ("ClientRequest",):
            continue
        made = copy.deepcopy(base)
        del made["definitions"][name]
        out.append(("no %s" % name, made, FEATURES))
        if isinstance(defs[name].get("properties"), dict):
            for field in defs[name]["properties"]:
                made = copy.deepcopy(base)
                del made["definitions"][name]["properties"][field]
                out.append(("no %s.%s" % (name, field), made, FEATURES))
    for name, schema in WORDS.items():
        for word in json.dumps(schema).split('"'):
            if word.isalpha() and word not in ("type", "string", "object", "enum", "oneOf", "anyOf", "const", "required",
                                               "properties"):
                made = copy.deepcopy(base)
                made["definitions"][name] = json.loads(json.dumps(schema).replace('"%s"' % word, '"%sX"' % word))
                out.append(("word %s.%s" % (name, word), made, FEATURES))
    for index, item in enumerate(defs["ServerRequest"]["oneOf"]):
        made = copy.deepcopy(base)
        del made["definitions"]["ServerRequest"]["oneOf"][index]
        out.append(("no server %d" % index, made, FEATURES))
    nested = {"definitions": {"v2": copy.deepcopy(defs)}}
    out.append(("under v2", nested, FEATURES))
    half = copy.deepcopy(base)
    half["definitions"]["v2"] = {name: half["definitions"].pop(name) for name in list(TYPES)}
    out.append(("types under v2", half, FEATURES))
    shadow = copy.deepcopy(half)
    shadow["definitions"]["Model"] = "not a dict"
    out.append(("a type shadowed by a string", shadow, FEATURES))
    for keyword in ("anyOf", "oneOf", "allOf"):
        made = copy.deepcopy(base)
        name = "Params_turn_start"
        made["definitions"][name] = {keyword: [{"type": "null"}, {"$ref": "#/definitions/Inner"}]}
        made["definitions"]["Inner"] = {"properties": {field: {} for field in PARAMS["turn/start"]}}
        out.append(("params through %s" % keyword, made, FEATURES))
    for depth in (5, 6, 7, 8):
        made = copy.deepcopy(base)
        inner = {"properties": {field: {} for field in PARAMS["turn/start"]}}
        for _ in range(depth):
            inner = {"anyOf": [inner]}
        made["definitions"]["Params_turn_start"] = inner
        out.append(("params %d deep" % depth, made, FEATURES))
        words = {"enum": ["completed", "interrupted", "failed"]}
        for _ in range(depth):
            words = {"oneOf": [words]}
        made = copy.deepcopy(base)
        made["definitions"]["TurnStatus"] = words
        out.append(("words %d deep" % depth, made, FEATURES))
    chain = copy.deepcopy(base)
    chain["definitions"]["Params_thread_resume"] = {"$ref": "#/definitions/A"}
    chain["definitions"]["A"] = {"$ref": "B"}
    chain["definitions"]["B"] = {"properties": {"threadId": {}}}
    out.append(("a $ref chain", chain, FEATURES))
    for value in (5, True, 0, "", "abc", {"x": {}}, [5], None, 1.5, [], {}):
        for where in ("enum", "anyOf", "oneOf", "allOf", "properties", "required", "const", "$ref"):
            made = copy.deepcopy(base)
            made["definitions"]["TurnStatus"][where] = value
            out.append(("TurnStatus %s=%r" % (where, value), made, FEATURES))
            made = copy.deepcopy(base)
            made["definitions"]["Params_turn_start"][where] = value
            out.append(("Params_turn_start %s=%r" % (where, value), made, FEATURES))
        made = copy.deepcopy(base)
        made["definitions"]["ClientRequest"]["oneOf"] = value
        out.append(("ClientRequest oneOf=%r" % (value,), made, FEATURES))
        made = copy.deepcopy(base)
        made["definitions"]["ServerRequest"]["oneOf"] = value
        out.append(("ServerRequest oneOf=%r" % (value,), made, FEATURES))
    few = copy.deepcopy(base)
    few["definitions"]["ClientRequest"]["oneOf"] = few["definitions"]["ClientRequest"]["oneOf"][:49]
    out.append(("49 methods", few, FEATURES))
    for value in (None, [], "x", 5, {"definitions": 5}, {"definitions": []}, {}):
        out.append(("document %r" % (value,), value, FEATURES))
    twice = copy.deepcopy(base)
    twice["definitions"]["ClientRequest"]["oneOf"][0]["properties"]["method"]["enum"] = ["thread/resume", "thread/resume", 5]
    out.append(("a method named twice", twice, FEATURES))
    for _ in range(120):
        made = copy.deepcopy(base)
        for _ in range(rng.randint(1, 4)):
            name = rng.choice(list(made["definitions"]))
            target = made["definitions"][name]
            if isinstance(target, dict) and target:
                key = rng.choice(list(target))
                target[key] = rng.choice([None, 5, "x", [], {}, [{}], {"enum": ["stop"]}, target[key]])
        out.append(("random", made, rng.choice([FEATURES, None, "plugin_hooks"])))
    return out


def record(**changes) -> dict:
    made = {"format": "codex-auto-resume-autocheck/1", "revision": 1, "key": ["ab" * 32, 10, 20], "tries": 1,
            "tried_at": NOW, "engine": "codex-cli 0.170.0", "checked_at": NOW + 5,
            "results": {"mhk": "pass", "m6": "fail", "mu": "unknown"}, "gone": {"m6": ["turn/start.input"]}}
    made.update(changes)
    return made


def record_files() -> list:
    """(label, bytes) of record files right and wrong."""
    out = [("good", json.dumps(record()).encode())]
    for key in list(record()):
        made = record()
        del made[key]
        out.append(("no %s" % key, json.dumps(made).encode()))
    for key, values in {"format": ["x", 1, None], "revision": [True, 1.0, 2, "1", 10 ** 30, None],
                        "tries": [True, 1.5, -1, 10 ** 30], "tried_at": [True, "1", None, 10 ** 400, -1e308, 10 ** 300],
                        "engine": [None, "", "codex cli", "codex-cli 0.170.0 <x>", 5, "c" * 81, "codex-cli 0.165.0-alpha.9"],
                        "checked_at": [None, True, 10 ** 400, 1.5], "results": [[], {"mzz": "pass"}, {"mhk": "maybe"},
                                                                                 {"mhk": ["pass"]}, {"m1": "pass"}, {}],
                        "gone": [[], {"m6": "x"}, {"m6": [1]}, {"mzz": []}, {"m6": []}], "key": [None, "x", [1]]}.items():
        for value in values:
            out.append(("%s=%r" % (key, value), json.dumps(record(**{key: value})).encode()))
    out.append(("extra key", json.dumps(dict(record(), more=1)).encode()))
    out.append(("NaN tried_at", json.dumps(record(tried_at=float("nan"))).encode()))
    out.append(("inf checked_at", json.dumps(record(checked_at=float("inf"))).encode()))
    out.append(("deep", b'{"a":' * 4000 + b"1" + b"}" * 4000))
    out.append(("too big", json.dumps(record(engine="codex-cli 0.170.0")).encode() + b" " * 70000))
    out.append(("not utf-8", json.dumps(record()).encode().replace(b"0.170.0", b"0.170.\xff")))
    out.append(("bom", b"\xef\xbb\xbf" + json.dumps(record()).encode()))
    out.append(("not json", b"{"))
    out.append(("a list", b"[]"))
    out.append(("an int too long", b"1" * 5000))
    return out


def engine_script(kind: str) -> tuple:
    """(script, files) of a fake engine."""
    script = {"version": {"stdout": "codex-cli 0.170.0\n"}, "help": {"stdout": "Usage: codex queue --thread <T> --message <M> --remote\n"},
              "schema": {"file": "schema.json", "code": 0}, "features": {"stdout": FEATURES}}
    base = whole()
    files = {"schema.json": json.dumps(base)}
    if kind == "gone":
        made = copy.deepcopy(base)
        del made["definitions"]["Params_turn_start"]["properties"]["input"]
        del made["definitions"]["HookEventName"]
        files["schema.json"] = json.dumps(made)
    elif kind == "no schema":
        script["schema"] = {"code": 0}
    elif kind == "schema refused":
        script["schema"] = {"file": "schema.json", "code": 1, "bare_code": 0, "plain_code": 1}
    elif kind == "no features":
        script["features"] = {"stdout": "x", "code": 1}
    elif kind == "flag":
        script["help"] = {"stdout": "Usage: codex queue --thread <T>\n"}
    elif kind == "version":
        script["version"] = {"stdout": "codex-cli 0.170.0 <beta>\n"}
    elif kind == "not whole":
        made = copy.deepcopy(base)
        made["definitions"]["ClientRequest"]["oneOf"] = made["definitions"]["ClientRequest"]["oneOf"][:40]
        files["schema.json"] = json.dumps(made)
    elif kind == "not a dict":
        files["schema.json"] = "[1, 2]"
    elif kind == "deep":
        files["schema.json"] = "[" * 4000 + "]" * 4000
    elif kind == "home file":
        script["schema"] = {"file": "schema.json", "code": 1, "home": "auth.json"}
    return script, files


KINDS = ["whole", "gone", "no schema", "schema refused", "no features", "flag", "version", "not whole", "not a dict",
         "deep", "home file", "unsigned"]


class AutocheckDiff(AdvCodexDiff):
    def test_the_table_and_the_judge(self):
        rng = random.Random(7204)
        cases = [["ac.checks"]]
        found = schemas(rng)
        for _label, document, features in found:
            cases.append(["ac.judge", document, features])
        for text in (FEATURES, "", "a\nb", "plugin_hooks", "| plugin_hooks |", "x\r\n\r\nplugin_hooks a b\r\n"):
            for name in ("plugin_hooks", "x", "a", "|", ""):
                cases.append(["ac.feature_words", text, name])
        self.same("judge", cases)
        RECORD.append("autocheck: CHECKS row by row; judge over %d schemas" % len(found))

    def test_the_record(self):
        cases_run = 0
        for index, (label, data) in enumerate(record_files()):
            folder = self.root / ("record-%d" % index)

            def setup(folder=folder, data=data):
                folder.mkdir(parents=True)
                (folder / "autocheck.json").write_bytes(data)

            cases = [["ac.read_record", str(folder)], ["ac.diagnostics", str(folder)]]
            for engine in ("codex-cli 0.170.0", "codex-cli 0.165.0-alpha.9", None, 5, ""):
                cases.append(["ac.results_for", str(folder), engine])
            self.scene("record %s" % label, cases, setup, [folder])
            cases_run += len(cases)
        self.same("no record", [["ac.read_record", str(self.root / "none")], ["ac.results_for", str(self.root / "none"), "x"]])
        RECORD.append("autocheck: %d record files, %d reads" % (len(record_files()), cases_run))

    def test_due(self):
        rng = random.Random(7205)
        key = ["ab" * 32, 10, 20]
        cases = []
        for _ in range(600):
            made = record(key=rng.choice([key, ["ab" * 32, 10, 21], key + [1], [x for x in key]]),
                          engine=rng.choice([None, "codex-cli 0.170.0"]), tries=rng.choice([0, 1, 2, 3, 4]),
                          revision=rng.choice([1, 1, 2]), tried_at=rng.choice([NOW, NOW - 600, NOW - 599, NOW - 21600,
                                                                              NOW - 21599, NOW + 5, int(NOW), NOW - 1e9]))
            cases.append(["ac.due", rng.choice([made, None]), rng.choice([key, None, ["ab" * 32, 10.0, 20]]),
                          rng.choice([NOW, NOW + 0.5, NOW + 600, NOW + 21600])])
        for tries in (1, 2, 3):
            cases.append(["ac.attempt", key, tries, NOW])
        self.same("due", cases)

    def test_write(self):
        for label, prepare in (("fresh", lambda home: None),
                               ("marked", lambda home: ((home / "config" / "advanced").mkdir(parents=True),
                                                        (home / "config" / "advanced" / ".owned-by-codex-auto-resume").write_text("x", encoding="utf-8"))),
                               ("a file", lambda home: ((home / "config").mkdir(parents=True),
                                                        (home / "config" / "advanced").write_text("x", encoding="utf-8"))),
                               # config/ a file: Paths.ensure() raises FileExistsError at its mkdir and makes no logs/
                               # (car-config since Integration 8, as the reference's).
                               ("config is a file", lambda home: (home / "config").write_text("x", encoding="utf-8")),
                               ("over a record", lambda home: ((home / "config" / "advanced").mkdir(parents=True),
                                                               (home / "config" / "advanced" / "autocheck.json").write_text("{}", encoding="utf-8")))):
            home = self.root / ("write-%s" % label.replace(" ", "-"))

            def setup(home=home, prepare=prepare):
                home.mkdir(parents=True, exist_ok=True)
                prepare(home)

            cases = [["ac.write", str(home), record()], ["ac.write", str(home), record(engine=None, results={})],
                     ["ac.read_record", str(home / "config" / "advanced")]]
            self.scene("write %s" % label, cases, setup, [home])

    def engines(self):
        found = {}
        for kind in KINDS:
            script, files = engine_script("whole" if kind == "unsigned" else kind)
            found[kind] = Engine(self.root / ("engine-%s" % kind.replace(" ", "-")), script, files)
        world = {"signers": {engine.exe.lower(): SIGNER for kind, engine in found.items() if kind != "unsigned"}}
        return found, world

    def test_run_and_probe(self):
        found, world = self.engines()
        for kind, engine in found.items():
            cases = [["ac.engine_key", engine.exe], ["ac.run_engine", engine.exe], ["ac.probe_engine", engine.exe]]
            self.scene("run %s" % kind, cases, lambda: None, [], world=world, engines=[engine])
        RECORD.append("autocheck: run_engine and probe_engine over %d fake engines, every child equal" % len(found))

    def test_tend(self):
        found, world = self.engines()
        for kind in ("whole", "gone", "no schema", "unsigned", "version"):
            engine = found[kind]
            home = self.root / ("tend-%s" % kind.replace(" ", "-"))
            codex = self.root / ("tend-codex-%s" % kind.replace(" ", "-"))

            def setup(home=home, codex=codex):
                home.mkdir(parents=True)
                codex.mkdir(parents=True, exist_ok=True)

            cases = [["ac.reset"], ["iu.reset"], ["ac.tend", str(home), NOW], ["iu.tell", str(home), engine.exe, str(codex)],
                     ["ac.tend", str(home), NOW], ["ac.read_record", str(home / "config" / "advanced")],
                     ["ac.tend", str(home), NOW + 30], ["ac.tend", str(home), NOW + 61],
                     ["ac.tend", str(home), NOW + 700], ["ac.tend", str(home), NOW + 21700],
                     ["ac.read_record", str(home / "config" / "advanced")], ["ac.tend", str(home), NOW + 50000],
                     ["ac.tend", str(home), NOW + 80000], ["ac.tend", str(home), NOW + 110000],
                     ["ac.diagnostics", str(home / "config" / "advanced")],
                     ["ac.tend", str(home), NOW - 5], ["ac.tend", str(home), NOW + 200000]]
            self.scene("tend %s" % kind, cases, setup, [home], world=world, engines=[engine])
        RECORD.append("autocheck: tend over 5 engines and 17 ticks each, the record byte for byte")

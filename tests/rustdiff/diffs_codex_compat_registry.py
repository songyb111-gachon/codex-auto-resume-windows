"""S3.3: the Compatibility Registry's verdicts held to the reference (`compat/standing.py`, `compat/report.py`,
`compat/reported.py`).

Every data sequence in the checkout's history, the frozen fixture, the advanced data and the community fixtures, and
copies that break one rule each: every document's standing for each product, clock and baseline in either role; the
evidence for every capability and engine version from every pair of documents in force, trusted or not; `evaluate`
over local check results of every kind; `accepted_word`, `verified_versions`, `combine`, `resolve` and `aggregate`
over their whole input grids. The report: `validate_report` over a report and every one-key mutation of it (a key
gone, a value of another type, a number out of range or too large for a float, a time ahead), `build_report`,
`unusable_view`, `view_of` and `mcp_view`. Reported: `parse`, `read` and `lookup` over every report count file and
broken copies.
"""
from __future__ import annotations

import itertools
import json
import random

from rustdiff import compatdata
from rustdiff.appserverdiff import AppBase, op

RECORD: list[str] = []
CAPABILITIES = ["engine_present", "exact_thread_recovery", "usage_limit_detection", "usage_reset_hint", "usage_probe",
                "thread_eligibility", "loaded_state_detection", "recovery_turn_tracking", "queue_withdraw",
                "outcome_observation", "transient_classification", "projection_freshness", "empty_response_recovery",
                "not_loaded_recovery", "goal_continuation", "subagent_recovery"]
CHECKS = ["official_location", "version_runs", "single_candidate", "queue_flags", "state_schema", "history_schema",
          "queue_schema", "projection_table", "sessions_directory", "lock_directory", "restart_manager",
          "protocol_usage_method", "protocol_delete_method", "app_server_matched"]
RESULTS = ["PASS", "FAIL", "UNAVAILABLE", "NOT_APPLICABLE"]
STATES = ["VERIFIED", "CHECKED", "COMPATIBLE", "FAILED_HERE", "INCOMPATIBLE", "UNKNOWN"]
PRODUCTS = ["0.6.26", "0.6.5", "0.6.0", "0.6.27", "9.9.9", "unknown", "", "x"]
VERSIONS = ["codex-cli 0.171.0", "codex-cli 0.153.4", "codex-cli 0.154.0-alpha.6.2", "codex-cli 0.155.0-alpha.9.2",
            "codex-cli 0.150.0", "codex-cli 0.159.99", "codex-cli 0.160.0", "codex-cli 99.0.0", "0.171.0", "", None, 5]


def texts(found):
    return [(name, path.read_text(encoding="utf-8", errors="surrogateescape")) for name, path in found]


class RegistryDiff(AppBase):
    def setUp(self):
        super().setUp()
        self.documents = texts(compatdata.documents(self.scratch / "documents"))

    def test_standing(self):
        cases = []
        bundles = [None, self.documents[0][1], self.documents[-1][1]] + [text for name, text in self.documents
                                                                          if name.startswith("data at")][-3:]
        for name, text in self.documents:
            ops = [op("registry.verified", text)]
            for product, bundled, now, role in itertools.product(PRODUCTS, bundles, (0, 1.7e9, 1.79e9, 1.9e9, 4e9),
                                                                 ("bundled", "cache")):
                ops.append(op("registry.standing", text, product, bundled, now, role))
            cases.append({"world": {}, "ops": ops, "name": name})
        count, calls = self.script(cases, "document standing", chunk=20)
        RECORD.append("registry: %d documents (%d data sequences in history), standing and verified versions, %d "
                      "cases equal" % (count, sum(1 for n, _ in self.documents if n.startswith("data at")), calls))

    def test_evidence_and_evaluate(self):
        rng = random.Random(1405)
        usable = [text for name, text in self.documents if not name.startswith("bad")]
        cases = []
        for first in usable:
            ops = []
            for second, trusted in ((None, True), (rng.choice(usable), True), (rng.choice(usable), False)):
                sources = [["bundled", first, True], ["cache", second, trusted]]
                for version in VERSIONS:
                    for capability in CAPABILITIES + ["nonsense"]:
                        ops.append(op("registry.evidence", capability, version, sources))
                    for _ in range(6):
                        checks = {check: rng.choice(RESULTS + ["pass", None, 5]) for check in
                                  rng.sample(CHECKS, rng.randint(0, len(CHECKS)))}
                        ops.append(op("registry.evaluate", checks, version, sources))
                    ops.append(op("registry.accepted", version, sources))
            ops.append(op("registry.accepted", "codex-cli 0.171.0", [["bundled", None, True], ["cache", None, False]]))
            cases.append({"world": {}, "ops": ops})
        count, calls = self.script(cases, "evidence and evaluate", chunk=6)
        RECORD.append("registry: evidence, evaluate and accepted_word over %d document pairs, %d cases equal"
                      % (count * 3, calls))

    def test_grids(self):
        values = RESULTS + STATES + ["pass", "", None, 5, ["PASS"]]
        ops = [op("registry.combine", list(items)) for size in range(0, 4)
               for items in itertools.product(RESULTS + ["x", None], repeat=size)]
        ops += [op("registry.resolve", local, evidence) for local in values for evidence in values]
        rng = random.Random(9)
        for _ in range(3000):
            capabilities = {}
            for name in rng.sample(CAPABILITIES + ["x"], rng.randint(0, 5)):
                capabilities[name] = rng.choice([{"state": rng.choice(STATES + ["nope", None, [1]])}, {}, None, "x"])
            names = rng.choice([None, ["engine_present"], CAPABILITIES[:4], [], ["x"]])
            ops.append(op("registry.aggregate", rng.choice([capabilities, [], None]) if rng.random() < 0.05
                          else capabilities, names))
        count, calls = self.script([{"world": {}, "ops": ops}], "combine resolve aggregate")
        RECORD.append("registry: combine, resolve and aggregate, %d cases equal" % calls)

    def test_reports(self):
        rng = random.Random(4242)
        engine = {"found": True, "version": "codex-cli 0.171.0", "signature": [123, 456], "path_digest": "a" * 64,
                  "candidates": 1}
        data = {"bundled": "ok", "bundled_sequence": 14, "cache": "absent", "cache_sequence": None,
                "cache_origin": None, "fetched_at": None, "source": "bundled", "expired": False}
        checks = {name: "PASS" for name in CHECKS}
        capabilities = {name: {"state": "COMPATIBLE", "reason": "local_checks_passed", "source": "local",
                               "tier": "conservative"} for name in CAPABILITIES[:12]}
        capabilities["not_loaded_recovery"] = {"state": "INCOMPATIBLE", "reason": "registry_incompatible",
                                               "source": "bundled", "tier": "unsupported",
                                               "registry_reason": "queued_message_not_delivered_while_unloaded"}
        report = {"format": "codex-auto-resume-compat-report/1", "checked_at": 1.79e9, "product": "0.6.26",
                  "engine": engine, "data": data, "overall": "structurally_compatible", "checks": checks,
                  "capabilities": capabilities, "acting": "verified"}
        oddities = [None, True, 0, -1, 2 ** 31, 2 ** 31 - 1, 10 ** 400, 1.5, "", "x", [], {}, [1, 2], "ok", "PASS",
                    "VERIFIED", "a" * 64, "A" * 64, 1.79e9, 946684800, 4102444801, "main", "file"]
        ops = [op("registry.validate_report", report, None), op("registry.validate_report", report, 1.79e9),
               op("registry.validate_report", report, 1.79e9 - 301), op("registry.validate_report", report, 1.79e9 - 299)]
        paths = [[key] for key in report] + [["engine", key] for key in engine] + [["data", key] for key in data] \
            + [["checks", key] for key in CHECKS] + [["capabilities", "engine_present", key]
                                                     for key in ("state", "reason", "source", "tier", "registry_reason")] \
            + [["capabilities", "not_loaded_recovery", "registry_reason"], ["capabilities", "engine_present"]]
        for path in paths:
            for value in oddities + ["__gone__"]:
                mutated = json.loads(json.dumps(report))
                holder = mutated
                for key in path[:-1]:
                    holder = holder[key]
                if value == "__gone__":
                    holder.pop(path[-1], None)
                else:
                    holder[path[-1]] = value
                ops.append(op("registry.validate_report", mutated, rng.choice([None, 1.79e9])))
        for value in oddities:
            ops.append(op("registry.validate_report", value, None))
        # build_report: the inputs a writer hands it
        for _ in range(400):
            caps = json.loads(json.dumps(capabilities))
            if rng.random() < 0.3:
                caps[rng.choice(CAPABILITIES)] = rng.choice([{"state": "UNKNOWN", "reason": "local_check_unavailable",
                                                              "source": "local", "tier": "conservative"},
                                                             {"state": "VERIFIED", "reason": "registry_checked",
                                                              "source": "bundled", "tier": "conservative"}, "x"])
            ops.append(op("registry.build_report", rng.choice([1.79e9, 946684800, 1.0, 5e9]),
                          rng.choice(["0.6.26", "unknown", "x", ""]), dict(engine, found=rng.choice([True, False])),
                          dict(data, cache=rng.choice(["absent", "ok", "zz"])),
                          {k: rng.choice(RESULTS + ["zz"]) for k in rng.sample(CHECKS, 5)}, caps,
                          rng.choice([None, "verified", "zz"])))
        views = []
        for status in ("absent", "invalid", "stale", "engine_changed", "ok", "x"):
            for engine_value in (None, {}, {"found": True, "version": "codex-cli 0.171.0"}, {"found": 0}):
                ops.append(op("registry.unusable_view", status, rng.choice([None, data]), rng.choice([None, 1.79e9]),
                              engine_value))
                views.append({"status": status, "overall": "unknown", "acting": None, "checked_at": None,
                              "engine": engine_value, "data": data, "capabilities": {}})
        ops.append(op("registry.view_of", report))
        good_view = {"status": "ok", "overall": "verified", "acting": "checked", "checked_at": 1.79e9,
                     "engine": {"found": True, "version": "codex-cli 0.171.0"}, "data": data, "checks": checks,
                     "capabilities": capabilities}
        for key in list(good_view) + ["data.source", "data.cache", "data.cache_sequence", "data.bundled_sequence"]:
            for value in oddities + ["__gone__", "cache", "bundled", "none"]:
                view = json.loads(json.dumps(good_view))
                holder, name = (view["data"], key[5:]) if key.startswith("data.") else (view, key)
                if value == "__gone__":
                    holder.pop(name, None)
                else:
                    holder[name] = value
                views.append(view)
        views += [None, [], "x", {"capabilities": {"engine_present": "x"}},
                  {"capabilities": {"engine_present": {"state": "VERIFIED", "reason": ["x"]}}},
                  {"capabilities": {"nonsense": "x", "usage_probe": {"state": "UNKNOWN", "reason": "report_stale"}}}]
        ops += [op("registry.mcp_view", view) for view in views]
        ops += [op("registry.finite_number", value) for value in oddities]
        count, calls = self.script([{"world": {}, "ops": ops}], "reports and views")
        RECORD.append("registry: validate_report, build_report, unusable_view, view_of and mcp_view, %d cases equal"
                      % calls)

    def test_reported(self):
        found = compatdata.reported_files(self.scratch / "reported")
        ops = []
        for name, path in found:
            ops += [op("registry.reported_parse", str(path)), op("registry.reported_read", str(path)),
                    op("registry.reported_read", str(path))]
            for version in ("codex-cli 0.171.0", "0.171.0", " codex-cli 0.171.0 ", "codex-cli 0.1.0", "x", None, 5,
                            "codex-cli 0.0.0", "codex-cli  0.171.0", "codex-cli 0.155.0-alpha.9.2"):
                ops.append(op("registry.reported_lookup", version, str(path)))
        ops.append(op("registry.reported_lookup", "codex-cli 0.171.0", str(self.scratch / "absent.json")))
        count, calls = self.script([{"world": {}, "ops": ops}], "reported")
        RECORD.append("registry: reported parse, read and lookup over %d files, %d cases equal" % (len(found), calls))

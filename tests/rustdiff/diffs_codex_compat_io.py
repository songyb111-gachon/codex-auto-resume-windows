"""S3.3: the Compatibility Registry's io half held to the reference (`compat/files.py`, `cache.py`, `probes.py`,
`views.py`, `evaluator.py`, through the `compatio` front).

Files: the capped read (absent, a folder, at and past the cap), the stamp, the product version of every version
text, the bundled baseline of every data sequence (in force or refused), the verified versions, the atomic write's
bytes and the path digest. The cache: every data sequence wrapped in every envelope variant (format, origin, the
fetch time of every kind) read and judged again against every baseline and clock, and the one writer, `import_document`,
over every refusal (origin, suffix, document, standing, rollback, size, a write that fails) with the file it leaves.
The probes: the source checks over codexsim homes and every schema variant, the helper's protocol checks, the engine
parts, discovery's records, the candidates in a scratch LOCALAPPDATA and the app's served engines. The views: the
report read and validated, bound to the engine on disk (or the app's), stale, the settings' engine, assembled. The
evaluator over sequences of ticks (the cache appearing, changing, expiring; discovery changing; the clock passing the
recompute) with the report it writes and the lines it says; and the refresh with its runner stubbed (no PowerShell
is started, nothing is fetched).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import sqlite3

from rustdiff import compatdata
from rustdiff.appserverdiff import AppBase, Fake, facts, op
from rustdiff.codexdiff import Home

RECORD: list[str] = []
NOW = 1.79e9
REPORT_FORMAT = "codex-auto-resume-compat-report/1"


def envelope(document_text, **changes):
    try:
        document = json.loads(document_text)
    except ValueError:
        document = document_text
    value = {"format": "codex-auto-resume-compat-cache/1", "fetched_at": 1.78e9, "origin": "main",
             "document": document}
    value.update(changes)
    return value


class FilesDiff(AppBase):
    def setUp(self):
        super().setUp()
        self.facts = facts()
        self.documents = compatdata.documents(self.scratch / "documents")

    def test_files(self):
        folder = self.profile("files")
        small, exact, over = folder / "small.json", folder / "exact.json", folder / "over.json"
        small.write_bytes(b"{}")
        exact.write_bytes(b"x" * 100)
        over.write_bytes(b"x" * 101)
        ops = []
        still = folder / "static"
        still.mkdir()
        for path in (small, exact, over, still, folder / "absent.json", folder / "a\0b"):
            ops += [op("registry.read_capped", str(path), 100), op("registry.stamp", str(path)),
                    op("registry.path_digest", str(path))]
        # (a relative path resolves against the process's own working folder, which differs by side: not asked)
        ops += [op("registry.path_digest", text) for text in ("C:\\", str(folder).upper(), str(folder) + "\\.\\x",
                                                               "C:/Users/ExampleUser/x")]
        for text in ("0.6.26", "0.6.26-beta", "0.6.26-beta.2", "0.6.26-beta.1", "0.6.26-beta.10", "0.6.26-beta.999",
                     "0.6.26-beta.1000", "0.6.26-beta.02", "0.6.26-alpha.9", "0.6.26-rc.1", "0.6.26 ", " 0.6.26",
                     "0.6", "1234567.0.0", "123456.0.0", "0.6.26\n", "unknown", "", "\u0660.6.26", "0.6.26-beta."):
            ops.append(op("registry.product_version", text))
        for name, path in self.documents:
            for product in ("0.6.26", "0.6.4", "9.9.9", "unknown"):
                ops += [op("registry.load_bundled", str(path), product), op("registry.bundled_verified", str(path), product)]
        values = [{}, {"b": 1, "a": [1.5, None, True]}, {"é": "日本", "z": {"y": 1e-05, "x": 1e16}}, [1, 2], "x", 5,
                  {"deep": [[[[]]]]}, {"n": 10 ** 30}]
        files = []
        for index, value in enumerate(values):
            target = folder / "written" / ("value-%d.json" % index)
            files.append(str(target))
            ops += [op("registry.write_json", str(target), value, "compat-cache."), op("file", str(target))]
        count, calls = self.script([{"world": {}, "ops": ops}], "registry files", files=files)
        RECORD.append("compatio: files (capped reads, stamps, digests, %d product versions, %d documents as the "
                      "bundled baseline, atomic writes), %d cases equal" % (20, len(self.documents), calls))

    def test_cache(self):
        folder = self.profile("cache")
        usable = [(name, path) for name, path in self.documents if not name.startswith("bad")]
        bundles = [None] + [str(path) for name, path in usable if name.startswith("data at")][-2:] + [str(usable[0][1])]
        cases = []
        for number, (name, path) in enumerate(self.documents):
            text = path.read_text(encoding="utf-8", errors="replace")
            variants = [envelope(text), envelope(text, origin="file"), envelope(text, origin="other"),
                        envelope(text, format="x"), envelope(text, fetched_at=True), envelope(text, fetched_at="1"),
                        envelope(text, fetched_at=10 ** 400), envelope(text, fetched_at=1), envelope(text, fetched_at=4102444800),
                        envelope(text, fetched_at=4102444801), {"format": "codex-auto-resume-compat-cache/1"}, [],
                        envelope(text, extra={"a": 1})]
            ops = []
            for index, value in enumerate(variants):
                cache_path = folder / ("cache-%d-%d.json" % (number, index))
                cache_path.write_text(json.dumps(value), encoding="utf-8")
                for bundled in bundles:
                    for product in ("0.6.26", "0.6.0"):
                        ops += [op("registry.read_cache", str(cache_path), bundled, product, NOW),
                                op("registry.judge_cache", str(cache_path), bundled, product, 1.7e9, 1.9e9)]
            ops += [op("registry.read_cache", str(folder / "absent.json"), None, "0.6.26", NOW),
                    op("registry.engine_word", bundles[1], str(folder / ("cache-%d-0.json" % number)),
                       "codex-cli 0.153.4", "0.6.26", NOW),
                    op("registry.engine_word", bundles[1], str(folder / ("cache-%d-0.json" % number)),
                       "codex-cli 0.171.0", "0.6.26-beta.2", 1.9e9)]
            cases.append({"world": {}, "ops": ops})
        for bad in (b"{", b"", b" " * (260 * 1024 + 1), b"[1]"):
            cache_path = folder / ("bad-%d.json" % len(cases))
            cache_path.write_bytes(bad)
            cases.append({"world": {}, "ops": [op("registry.read_cache", str(cache_path), None, "0.6.26", NOW)]})
        count, calls = self.script(cases, "cache reads", chunk=10)
        RECORD.append("compatio: %d cache files (every document x 13 envelopes) read and judged, %d cases equal"
                      % (count * 13, calls))

    def test_import(self):
        folder = self.profile("import")
        bundled = str([path for name, path in self.documents if name.startswith("data at")][-1])
        cases, files = [], []
        for number, (name, path) in enumerate(self.documents):
            cache_path = folder / ("cache-%d.json" % number)
            files.append(str(cache_path))
            ops = []
            for origin in ("main", "file", "other", None):
                ops.append(op("registry.import", bundled, str(cache_path), str(path), origin, "0.6.26", NOW, True))
            for product, now in (("0.6.0", NOW), ("0.6.26", 1.9e9), ("0.6.26", 1.0e9)):
                ops.append(op("registry.import", bundled, str(cache_path), str(path), "file", product, now, True))
            ops.append(op("registry.import", bundled, str(cache_path), str(path), "file", "0.6.26", NOW, False))
            ops.append(op("file", str(cache_path)))
            cases.append({"world": {}, "ops": ops})
        odd = folder / "odd"
        odd.mkdir()
        source = self.documents[-1][1] if False else [p for n, p in self.documents if n.startswith("data at")][-1]
        names = ["doc.JSON", "doc.json.txt", "doc", ".json", "doc.", "doc..json"]
        ops = []
        for name in names:
            target = odd / name
            target.write_bytes(source.read_bytes())
            ops.append(op("registry.import", bundled, str(folder / "odd-cache.json"), str(target), "main", "0.6.26", NOW, True))
        ops += [op("registry.import", bundled, str(folder / "odd-cache.json"), None, "main", "0.6.26", NOW, True),
                op("registry.import", bundled, str(folder / "odd-cache.json"), str(odd / "absent.json"), "main",
                   "0.6.26", NOW, True), op("file", str(folder / "odd-cache.json"))]
        files.append(str(folder / "odd-cache.json"))
        cases.append({"world": {}, "ops": ops})
        # a rollback against a cache in force, and a newer one taken in
        sequence = [p for n, p in self.documents if n.startswith("newest")]
        roll = folder / "roll-cache.json"
        files.append(str(roll))
        cases.append({"world": {}, "ops": [op("registry.import", bundled, str(roll), str(each), "main", "0.6.26", NOW, True)
                                           for each in sequence + sequence[::-1]] + [op("file", str(roll))]})
        count, calls = self.script(cases, "imports", chunk=20, files=files)
        RECORD.append("compatio: import_document over %d documents and every refusal, the cache files equal, %d cases"
                      % (len(self.documents), calls))


def schema_variants(root: Path) -> list[Path]:
    """Codex homes whose databases are each missing something a check reads."""
    homes = []

    def home(name):
        made = Home(root / name / "codex-home")
        homes.append(made.root)
        return made

    base = home("codexsim")
    base.thread("0a1b2c3d-0001-7000-8000-00000000000a")
    (base.root / "sessions").mkdir(exist_ok=True)
    plain = home("no threads")
    del plain
    gone = home("no lock folder")
    gone.thread("0a1b2c3d-0001-7000-8000-00000000000b")
    import shutil
    shutil.rmtree(gone.root / "thread-writer-locks", ignore_errors=True)
    for name, statement, db in (("no rollout_path", "ALTER TABLE threads DROP COLUMN rollout_path", "state_5.sqlite"),
                                ("no projection", "DROP TABLE thread_history_projection_state", "thread_history_1.sqlite"),
                                ("no offset column", "ALTER TABLE thread_history_projection_state DROP COLUMN "
                                                     "next_rollout_byte_offset", "thread_history_1.sqlite"),
                                ("no queue payload", "ALTER TABLE queued_items DROP COLUMN payload_json", "queue_1.sqlite"),
                                ("no items table", "DROP TABLE thread_items", "thread_history_1.sqlite")):
        made = home(name)
        try:
            connection = sqlite3.connect(made.root / db)
            connection.execute(statement)
            connection.commit()
            connection.close()
        except sqlite3.Error:
            pass
    # Review 7 (REVIEW-int5b.md N1): a home whose state holds no conversation and that has no history database yet -
    # every new Codex home before its first conversation. The v0.6.26 final reads its history checks NOT_APPLICABLE
    # (compat/probes.py source_checks), beta.2 UNAVAILABLE; with a conversation both UNAVAILABLE. No other home here
    # lacks the history file, so `rediff_appserver.py --reference v0.6.26` passed without these two.
    fresh = home("no threads, no history yet")
    (fresh.root / "thread_history_1.sqlite").unlink(missing_ok=True)
    lost = home("a thread, no history")
    lost.thread("0a1b2c3d-0001-7000-8000-00000000000c")
    (lost.root / "thread_history_1.sqlite").unlink(missing_ok=True)
    # The final-port seat (FINAL-DELTA #5): no history beside a state whose conversations are not known - a state of a
    # schema the check fails (never asked), one that is no database, none at all, an empty threads table in a newer
    # generation beside an older one that holds a conversation: "unknown" stays UNAVAILABLE, only "none" is "not yet".
    for name, damage in (("no rollout_path, no history", "schema"), ("state not sqlite, no history", "damaged"),
                         ("no state, no history", "gone"), ("newer empty state, no history", "newer")):
        made = home(name)
        if damage == "newer":
            made.thread("0a1b2c3d-0001-7000-8000-00000000000d")
        (made.root / "thread_history_1.sqlite").unlink(missing_ok=True)
        if damage == "schema":
            try:
                connection = sqlite3.connect(made.root / "state_5.sqlite")
                connection.execute("ALTER TABLE threads DROP COLUMN rollout_path")
                connection.commit()
                connection.close()
            except sqlite3.Error:
                pass
        elif damage == "damaged":
            (made.root / "state_5.sqlite").write_bytes(b"not a database at all" * 10)
        elif damage == "gone":
            (made.root / "state_5.sqlite").unlink(missing_ok=True)
        else:
            import shutil as _shutil
            _shutil.copyfile(made.root / "state_5.sqlite", made.root / "state_6.sqlite")
            connection = sqlite3.connect(made.root / "state_6.sqlite")
            connection.execute("DELETE FROM threads")
            connection.commit()
            connection.close()
    for name, db, data in (("state not sqlite", "state_5.sqlite", b"not a database at all" * 10),
                           ("history empty", "thread_history_1.sqlite", b""),
                           ("newer queue", "queue_2.sqlite", b"")):
        made = home(name)
        (made.root / db).write_bytes(data)
    missing = root / "absent" / "codex-home"
    homes.append(missing)
    afile = root / "a-file"
    afile.write_bytes(b"x")
    homes.append(afile)
    return homes


class ProbesDiff(AppBase):
    def test_source_and_api_checks(self):
        homes = schema_variants(self.scratch / "homes")
        ops = [op("registry.source_checks", str(home)) for home in homes]
        codes = ["ok", "protocol_home_mismatch", "protocol_method_unknown", "protocol_request_refused",
                 "protocol_reply_unknown", "protocol_unavailable"]
        rng = random.Random(58)
        for _ in range(200):
            seeded = {method: [rng.choice(codes), rng.randint(1, 5)] for method in
                      rng.sample(["initialize", "account/rateLimits/read", "thread/queue/delete"], rng.randint(0, 3))}
            ops += [op("registry.seed", seeded), op("registry.api_checks"),
                    op("registry.protocol_check", rng.choice(["thread/start", "initialize", "account/rateLimits/read"]))]
        raws = [None, {}, [], {"official_location": "PASS", "version_runs": "FAIL", "queue_flags": "zz"},
                {"official_location": 1}]
        ops += [op("registry.engine_part", raw) for raw in raws]
        records = [[], [["C:\\a\\codex.exe", None]],
                   [["C:\\a\\codex.exe", {"official_location": "PASS", "version_runs": "PASS", "queue_flags": "PASS",
                                          "version": "codex-cli 0.171.0", "signature": [1, 2]}]],
                   [["C:\\a\\codex.exe", {"official_location": "PASS", "version": "x" * 90, "signature": (1, 2)}]],
                   [["C:\\a\\codex.exe", {"official_location": "PASS", "version_runs": "PASS", "version": "codex-cli 1.0.0"}],
                    ["C:\\b\\codex.exe", {"official_location": "PASS", "version_runs": "FAIL", "version": "codex-cli 1.0.0"}]],
                   [["C:\\a\\codex.exe", {"official_location": "FAIL"}], ["C:\\b\\codex.exe", {"official_location": "FAIL"}]],
                   [["C:\\a\\codex.exe", {"version": "codex-cli 1.0.0"}], ["C:\\b\\codex.exe", {"version": "codex-cli 2.0.0"}]],
                   [["C:\\a\\codex.exe", {"version": [1]}], ["C:\\b\\codex.exe", {"version": "codex-cli 2.0.0"}]],
                   [["C:\\a\\codex.exe", "x"], ["C:\\b\\codex.exe", 5], ["C:\\c\\codex.exe", None]]]
        for record in records:
            for candidates in (None, 0, 3):
                ops.append(op("registry.engine_from_discovery", record, candidates))
        local = self.scratch / "local"
        for name in ("aaaa", "bbbb", "ABCD", "xyz", "12"):
            (local / "OpenAI/Codex/bin" / name).mkdir(parents=True)
        for name in ("aaaa", "bbbb", "ABCD", "xyz"):
            (local / "OpenAI/Codex/bin" / name / "codex.exe").write_bytes(b"e")
        (local / "OpenAI/Codex/bin/file").write_bytes(b"")
        rows = [{"pid": 10, "parent": 1, "path": r"C:\Program Files\WindowsApps\OpenAI.Codex_1.0.0.0_x64__2p2nqsd0c76g0"
                 r"\app\ChatGPT.exe", "created": 100, "family": "OpenAI.Codex_2p2nqsd0c76g0"},
                {"pid": 20, "parent": 10, "path": str(local / "OpenAI/Codex/bin/aaaa/codex.exe"), "created": 200},
                {"pid": 21, "parent": 10, "path": r"C:\elsewhere\codex.exe", "created": 210}]
        world = {"env": {"LOCALAPPDATA": str(local), "ProgramW6432": r"C:\Program Files"}, "processes": rows,
                 "signers": {r"c:\elsewhere\codex.exe": "OpenAI OpCo, LLC"}}
        later = [op("registry.candidate_paths", None), op("registry.candidate_paths", str(local / "OpenAI/Codex/bin/xyz/codex.exe")),
                 op("registry.candidate_paths", "~\\x\\codex.exe"), op("registry.candidate_paths", ""),
                 op("registry.served_engines")]
        cases = [{"world": {}, "ops": ops}, {"world": world, "ops": later},
                 {"world": {"env": {}}, "ops": later}, {"world": dict(world, processes={"raise": "OSError"}), "ops": later}]
        count, calls = self.script(cases, "probes")
        RECORD.append("compatio: source checks over %d homes, api checks, engine parts, %d discovery records, "
                      "candidates and served engines, %d cases equal" % (len(homes), len(records) * 3, calls))


def report_value(**changes):
    capabilities = {name: {"state": "COMPATIBLE", "reason": "local_checks_passed", "source": "local",
                           "tier": "conservative"} for name in
                    ("engine_present", "exact_thread_recovery", "usage_probe")}
    value = {"format": REPORT_FORMAT, "checked_at": NOW, "product": "0.6.26",
             "engine": {"found": False, "version": None, "signature": None, "path_digest": None, "candidates": 0},
             "data": {"bundled": "ok", "bundled_sequence": 14, "cache": "absent", "cache_sequence": None,
                      "cache_origin": None, "fetched_at": None, "source": "bundled", "expired": False},
             "overall": "structurally_compatible", "checks": {"app_server_matched": "FAIL"},
             "capabilities": capabilities, "acting": "structurally_compatible"}
    value.update(changes)
    return value


class ViewsDiff(AppBase):
    def test_views(self):
        known = facts()
        folder = self.profile("views")
        local = folder / "local"
        engine = local / "OpenAI/Codex/bin/aaaa/codex.exe"
        engine.parent.mkdir(parents=True)
        engine.write_bytes(b"engine")
        stat = engine.stat()
        digest = hashlib.sha256(str(engine.resolve()).lower().encode("utf-8")).hexdigest()
        found_engine = {"found": True, "version": "codex-cli 0.171.0", "signature": [stat.st_size, stat.st_mtime_ns],
                        "path_digest": digest, "candidates": 1}
        reports = [report_value(), report_value(engine=found_engine),
                   report_value(engine=dict(found_engine, signature=[1, 2])),
                   report_value(engine=dict(found_engine, path_digest="b" * 64)),
                   report_value(engine=dict(found_engine, candidates=1, found=False)),
                   report_value(checked_at=NOW - 4501), report_value(checked_at=NOW + 301), report_value(checked_at=NOW - 4499),
                   report_value(format="x"), "not json", report_value(acting="zz"),
                   report_value(checked_at=10 ** 400), report_value(data=dict(report_value()["data"], fetched_at=10 ** 400))]
        spec = {"bundled": known["bundled"], "reported": known["reported"], "cache_file": str(folder / "cache.json"),
                "version": known["version"]}
        ops = []
        for index, value in enumerate(reports + [None]):
            path = folder / ("report-%d.json" % index)
            if value is not None:
                path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
            spec_here = dict(spec, report_file=str(path))
            for now in (NOW, NOW + 4600):
                ops += [op("registry.read_report", str(path), now), op("registry.watchers_server_check", str(path), now),
                        op("registry.read_view", spec_here, now, None),
                        op("registry.read_view", spec_here, now, str(engine)),
                        op("registry.reader_view", spec_here, now, {"codex_exe": str(engine)}),
                        op("registry.reader_view", spec_here, now, None),
                        op("registry.reader_view", spec_here, now, "settings")]
            if isinstance(value, dict):
                ops.append(op("registry.binding", spec_here, value, None))
        for view in ({"status": "ok", "engine": {"found": True, "version": "codex-cli 0.153.4"}},
                     {"status": "ok", "engine": {"found": False, "version": "codex-cli 0.153.4"}},
                     {"status": "stale", "engine": {"found": True, "version": "codex-cli 0.153.4"}},
                     {"status": "ok", "engine": "x"}, {}):
            ops.append(op("registry.reported_for", spec, view))
        bundles = [path for name, path in compatdata.documents(folder / "documents") if name.startswith("data at")]
        checks = {"official_location": "PASS", "version_runs": "PASS", "queue_flags": "FAIL", "single_candidate": "PASS"}
        for bundled in bundles[-2:]:
            for cache in (str(folder / "absent-cache.json"),):
                for engine_value in ({"found": True, "version": "codex-cli 0.153.4"}, {}, {"version": 5}):
                    ops.append(op("registry.assemble", checks, engine_value, {"state_schema": "PASS"}, str(bundled),
                                  cache, "0.6.26", NOW, None))
                    ops.append(op("registry.assemble", checks, engine_value, {}, str(bundled), cache, "x", NOW, "verified"))
        rows = [{"pid": 10, "parent": 1, "path": r"C:\Program Files\WindowsApps\OpenAI.Codex_1.0.0.0_x64__2p2nqsd0c76g0"
                 r"\app\ChatGPT.exe", "created": 100, "family": "OpenAI.Codex_2p2nqsd0c76g0"},
                {"pid": 20, "parent": 10, "path": str(engine), "created": 200}]
        world = {"env": {"LOCALAPPDATA": str(local), "ProgramW6432": r"C:\Program Files"}, "processes": rows,
                 "restart_manager": True}
        home = folder / "codex-home"
        home.mkdir()
        lives = [op("registry.live_report", dict(spec, report_file=str(folder / "report-1.json")), str(home), record,
                    None, NOW, False) for record in ([], [[str(engine), {"official_location": "PASS"}]])]
        lives += [op("registry.live_view", dict(spec, report_file=str(folder / "report-0.json")), str(home), [], None,
                     NOW, False)]
        cases = [{"world": world, "ops": ops + lives},
                 {"world": {"env": {"LOCALAPPDATA": str(local)}, "processes": {"raise": "OSError"}}, "ops": ops[:40]}]
        count, calls = self.script(cases, "views", chunk=2)
        RECORD.append("compatio: read_report, read_view, reader_view, binding, reported_for, assemble and live reports "
                      "over %d report files, %d cases equal" % (len(reports) + 1, calls))

    def test_live_report_discovers(self):
        """live_report with no backend and no record: discovery runs the fake engines found in the scratch bin."""
        known = facts()
        made, fakes = [], []
        for number, scripts in enumerate(([{}], [{}, {}], [{"version": {"stdout": "", "code": 1}}], [])):
            root = (self.scratch / ("discover-%d" % number))
            root.mkdir()
            root = root.resolve()
            local, home = root / "local", root / "codex-home"
            home.mkdir()
            base = {"version": {"stdout": "codex-cli 0.171.0\n", "code": 0},
                    "help": {"stdout": "  --thread X\n  --message Y\n", "code": 0}}
            case_fakes = [Fake(local, dict(base, **extra), hexname="%x" % (0xa0 + index))
                          for index, extra in enumerate(scripts)]
            spec = {"bundled": known["bundled"], "reported": known["reported"], "cache_file": str(root / "cache.json"),
                    "report_file": str(root / "report.json"), "version": known["version"]}
            world = {"env": {"LOCALAPPDATA": str(local), "ProgramW6432": r"C:\Program Files"}, "processes": []}
            made.append({"world": world, "ops": [op("registry.live_report", spec, str(home), None, None, NOW, False),
                                                 op("registry.live_view", spec, str(home), None, None, NOW, False)]})
            fakes.append(case_fakes[0] if case_fakes else None)
        count, calls = self.script(made, "live report discovery", fakes=fakes)
        RECORD.append("compatio: live_report's discovery over %d scratch bins of fake engines, %d calls equal"
                      % (count, calls))


class EvaluatorDiff(AppBase):
    def test_ticks(self):
        known = facts()
        rng = random.Random(600)
        documents = [path for name, path in compatdata.documents(self.scratch / "documents")
                     if not name.startswith("bad")]
        cases, files = [], []
        for number in range(40):
            root = self.profile("evaluator-%d" % number)
            cache_file, report_file = root / "compat-cache.json", root / "compatibility.json"
            files += [str(cache_file), str(report_file)]
            spec = {"bundled": known["bundled"], "reported": known["reported"], "cache_file": str(cache_file),
                    "report_file": str(report_file), "version": known["version"]}
            home = root / "codex-home"
            Home(home)
            ops = [op("registry.evaluator.new", spec, str(home), None, rng.choice([None, "0.6.26", "0.6.0"]),
                      rng.choice([None, 600, 10]))]
            record = []
            for _ in range(rng.randint(3, 12)):
                pick = rng.random()
                if pick < 0.2:
                    document = rng.choice(documents)
                    text = document.read_text(encoding="utf-8", errors="replace")
                    ops.append(op("registry.write_json", str(cache_file), envelope(text, fetched_at=rng.choice([1.78e9, 1.79e9])),
                                  "compat-cache."))
                elif pick < 0.35:
                    ops.append(op("advance", rng.choice([5, 300, 601, 86400 * 100, 86400 * 400])))
                elif pick < 0.5:
                    record = rng.choice([[], [["C:\\a\\codex.exe", {"official_location": "PASS", "version_runs": "PASS",
                                                                    "queue_flags": "PASS", "version": "codex-cli 0.153.4",
                                                                    "signature": [1, 2]}]],
                                         [["C:\\a\\codex.exe", {"official_location": "FAIL"}]],
                                         [["C:\\a\\codex.exe", {"official_location": "PASS"}],
                                          ["C:\\b\\codex.exe", {"official_location": "PASS"}]]])
                ops.append(op("registry.evaluator.tick", record, False))
            ops += [op("registry.evaluator.state"), op("file", str(report_file))]
            cases.append({"world": {"clock": NOW}, "ops": ops})
        count, calls = self.script(cases, "evaluator", chunk=10, files=files)
        RECORD.append("compatio: the evaluator over %d tick sequences (the report files and log lines equal), %d calls"
                      % (count, calls))

    def test_refresh(self):
        root = self.profile("refresh")
        project = root / "project"
        (project / "scripts").mkdir(parents=True)
        (project / "scripts" / "bootstrap.ps1").write_text("# stand-in, never run\n", encoding="utf-8")
        other = root / "other.ps1"
        other.write_text("# stand-in\n", encoding="utf-8")
        stubs = [{"raise": "timeout"}, {"raise": "os"}, {"stdout": None, "code": 0}, {"stdout": "", "code": 0}]
        lines = ["compatibility: refreshed 15", "compatibility: refreshed", "compatibility: refreshed x",
                 "compatibility: refreshed \u0661\u0665", "compatibility: refreshed \u00b2",
                 "compatibility: refused rollback", "compatibility: refused nonsense", "compatibility: unavailable",
                 "compatibility: refreshed 15 more", "  compatibility:  refreshed   16  ", "compatibility:refreshed 1",
                 "compatibility: ", "compatibility: incomplete", "compatibility: failed",
                 "noise\ncompatibility: refreshed 3\ncompatibility: refused too_large",
                 "compatibility: refreshed 3\r\nnoise\x0bcompatibility: unavailable"]
        for line in lines:
            for code in (0, 12, 13, 1):
                stubs.append({"stdout": line + "\n", "code": code})
        ops = []
        for stub in stubs:
            ops.append(op("registry.run_refresh", str(root / "home"), None, str(project), None, stub))
        ops += [op("registry.run_refresh", str(root / "home"), str(other), str(project), 5, {"stdout": "", "code": 0}),
                op("registry.run_refresh", str(root / "home"), str(root / "absent.ps1"), str(project), None, {}),
                op("registry.run_refresh", str(root / "home"), None, str(root / "nowhere"), None, {})]
        count, calls = self.script([{"world": {}, "ops": ops}], "refresh")
        RECORD.append("compatio: run_refresh over %d stubbed answers (no PowerShell started), %d cases equal"
                      % (len(stubs), calls))

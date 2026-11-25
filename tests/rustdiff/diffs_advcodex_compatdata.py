"""S7.2c: compatdata.py (the advanced compatibility data) held equal to the v0.6.26 final, over every advanced data
sequence the repository holds and documents made from them that break one rule each.

The documents: `advanced/compat/codex_compat_advanced.json` at every commit that changed it, the shapes
advanced/tests/test_advanced_compat_data.py builds (`ValidationTests`, `TrustTests`, `InForceTests`), and mutants of each
(every top key, the sequence's bounds and types, times in every form `strptime` and the patterns judge - Unicode digits, a
lower-case T, February 30, year 0, second 61 -, the product's bounds, engines and measurements past their caps, every
version, id, entry, verdict and evidence rule, the edition line, bytes that are no JSON, too many and too deep). Each is
validated for five products, read from a file, summarised and laid over tables (the build's own MEASURED and generated
ones, the exact engine, another and none); and the adoption is run over homes holding a download, an adopted file and a
bundled one in every order of sequence and freshness, the files left compared byte for byte.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_compatdata`.
"""
from __future__ import annotations

import calendar
import copy
import json
from pathlib import Path
import random
import time

from rustdiff import compatdata as history_of
from rustdiff.advcodex import AdvCodexDiff

RECORD: list = []
FORMAT = "codex-auto-resume-compat-advanced/1"
MARK = "ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's."
ENGINE = "codex-cli 0.165.0-alpha.9"
OLD = "codex-cli 0.162.0-alpha.17.2"
NOW = 1_790_000_000.0
PRODUCTS = [None, [0, 6, 20], [0, 6, 19], [9, 9, 9], "none"]
MEASUREMENTS = ["m1", "m2", "m2b", "m3", "m4", "m6", "mopen", "mimg", "mx", "mu", "mn", "mr", "mf", "mhk", "mauto"]


def iso(seconds) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def evidence(version, name):
    return "docs/evidence/advanced/%s/measurement-%s.json" % (version.replace(" ", "-"), name)


def entry(version, name, verdict="pass", recorded=None):
    return {"verdict": verdict, "recorded_at": recorded or time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(NOW - 7200)),
            "evidence": evidence(version, name)}


def document(engines=None, *, sequence=2, published=None, expires=None, minimum="0.6.20", **changes):
    published = NOW - 3600 if published is None else published
    made = {"format": FORMAT, "sequence": sequence, "published_at": iso(published),
            "expires_at": iso(published + 90 * 86400 if expires is None else expires), "min_product": minimum,
            "engines": [{"version": version, "measurements": dict(found)} for version, found in (engines or {}).items()]}
    made.update(changes)
    return made


def raw(made) -> bytes:
    return made if isinstance(made, bytes) else json.dumps(made).encode("utf-8")


def mutants(base: dict) -> list:
    """Copies of `base` that each break (or bend) one rule."""
    out = []

    def put(**changes):
        made = copy.deepcopy(base)
        made.update(changes)
        out.append(made)

    for key in list(base):
        made = copy.deepcopy(base)
        del made[key]
        out.append(made)
    for value in (0, 1, 2 ** 31 - 1, 2 ** 31, -1, True, 1.0, "1", None, 10 ** 30):
        put(sequence=value)
    for value in ("2026-10-30T00:00:00Z", "2026-10-30t00:00:00Z", "2026-10-30T00:00:00z", "2026-02-30T00:00:00Z",
                  "0000-01-01T00:00:00Z", "2026-12-31T23:59:61Z", "2026-12-31T23:59:62Z", "2026-12-31T24:00:00Z",
                  "2026-13-01T00:00:00Z", "２０２６-10-30T00:00:00Z", "2026-1-30T00:00:00Z", "2026-10-30T00:00Z",
                  "2026-10-30 00:00:00Z", "", 5, None, "2028-02-29T00:00:00Z", "2100-02-29T00:00:00Z", "9999-12-31T23:59:59Z"):
        put(published_at=value)
        put(expires_at=value)
    put(expires_at=base.get("published_at"))
    for value in ("0.6.20", "0.6.26", "0.6.27", "0.6.26-alpha", "１.6.0", "0.6", "1.2.3.4", "1234567.0.0", "123456.0.0",
                  " 0.6.20", "0.6.20 ", 5, None, "", "0.6.0"):
        put(min_product=value)
    put(format="codex-auto-resume-compat-advanced/2")
    put(format=1)
    put(_edition=MARK)
    put(_edition="something else")
    put(_edition=None)
    put(advisories=[])
    for value in ({}, "x", None, [None], [[]], [{"version": ENGINE}], [{"version": ENGINE, "measurements": {}, "x": 1}]):
        put(engines=value)
    put(engines=[{"version": "codex-cli 0.%d.0" % n, "measurements": {}} for n in range(64)])
    put(engines=[{"version": "codex-cli 0.%d.0" % n, "measurements": {}} for n in range(65)])
    for version in ("0.165.0", "codex-cli 0.165.0 ", " codex-cli 0.165.0", "codex-cli 0.165.0-alpha.9.1",
                    "codex-cli 0.165.0-beta.1", "codex-cli " + "1" * 52 + ".0.0", "codex-cli 1." + "0" * 60 + ".0",
                    "codex-cli 0.165", 5, None, "CODEX-CLI 0.165.0", "codex-cli 0.165.0\ud800"):
        put(engines=[{"version": version, "measurements": {}}])
    twice = [{"version": ENGINE, "measurements": {}}, {"version": ENGINE, "measurements": {}}]
    put(engines=twice)
    for name in ("M1", "m", "m" + "a" * 15, "m" + "a" * 16, "mzzz", "mopen", "m_x", "mé", "x1"):
        put(engines=[{"version": ENGINE, "measurements": {name: entry(ENGINE, name)}}])
    for broken in ({"verdict": "pass"}, dict(entry(ENGINE, "mopen"), note=1), dict(entry(ENGINE, "mopen"), verdict="blocked"),
                   dict(entry(ENGINE, "mopen"), verdict="PASS"), dict(entry(ENGINE, "mopen"), verdict=1),
                   dict(entry(ENGINE, "mopen"), verdict="fail"), dict(entry(ENGINE, "mopen"), evidence="docs/x.json"),
                   dict(entry(ENGINE, "mopen"), evidence=None),
                   dict(entry(ENGINE, "mopen"), recorded_at="2026-10-30T00:00:00Z"),
                   dict(entry(ENGINE, "mopen"), recorded_at=time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(NOW + 86400))),
                   dict(entry(ENGINE, "mopen"), recorded_at="2026-02-30T00:00Z"), "x", None, []):
        put(engines=[{"version": ENGINE, "measurements": {"mopen": broken}}])
    put(engines=[{"version": ENGINE, "measurements": {"m%d" % n: entry(ENGINE, "m%d" % n) for n in range(128)}}])
    put(engines=[{"version": ENGINE, "measurements": {"m%d" % n: entry(ENGINE, "m%d" % n) for n in range(129)}}])
    put(engines=[{"version": ENGINE, "measurements": []}])
    published = base.get("published_at")
    if isinstance(published, str) and len(published) == 20:
        # A record made the very minute of publication (allowed), and one a minute after (refused).
        same = published[:16] + "Z"
        later = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(calendar.timegm(time.strptime(same, "%Y-%m-%dT%H:%MZ")) + 60))
        for recorded in (same, later):
            put(engines=[{"version": ENGINE, "measurements": {"mopen": entry(ENGINE, "mopen", recorded=recorded)}}])
    return out


def byte_cases() -> list:
    """Bytes a document may be that are no document at all."""
    good = raw(document({ENGINE: {"mopen": entry(ENGINE, "mopen")}}))
    return [b"", b"{", b"[]", b"null", b"\xef\xbb\xbf" + good, b"\xff\xfe" + good, good + b" ", b"  " + good,
            b" " * (256 * 1024 + 1), good + b" " * (256 * 1024), b"[" * 3000 + b"]" * 3000, b'{"a":' * 2000 + b"1" + b"}" * 2000,
            good.replace(b'"sequence": 2', b'"sequence": 2, "sequence": 3'), good.replace(b'"sequence": 2', b'"sequence": NaN'),
            "{\"format\": \"\\ud800\"}".encode("utf-8"), good.replace(b"0.6.20", b"0.6.\xc3\xa9")]


def documents() -> list:
    """(label, bytes) of every document the diff reads."""
    found = []
    for commit, data in history_of.history("advanced/compat/codex_compat_advanced.json"):
        found.append(("history %s" % commit, data))
        try:
            parsed = json.loads(data.decode("utf-8"))
        except ValueError:
            continue
        for index, made in enumerate(mutants(parsed)):
            found.append(("history %s mutant %d" % (commit, index), raw(made)))
    good = document({ENGINE: {"mopen": entry(ENGINE, "mopen"), "mimg": entry(ENGINE, "mimg", "fail"),
                              "mzzz": entry(ENGINE, "mzzz")},
                     OLD: {"m2": entry(OLD, "m2", "fail"), "mopen": entry(OLD, "mopen")}})
    found.append(("good", raw(good)))
    for index, made in enumerate(mutants(good)):
        found.append(("good mutant %d" % index, raw(made)))
    for index, data in enumerate(byte_cases()):
        found.append(("bytes %d" % index, data))
    return found


def tables(rng) -> list:
    out = [[], None]
    verdicts = ["pass", "fail", "blocked"]
    engines = [ENGINE, OLD, "codex-cli 0.170.0"]
    for _ in range(40):
        picked = rng.sample(MEASUREMENTS, rng.randint(0, len(MEASUREMENTS)))
        out.append([[m, rng.choice(verdicts), rng.choice(engines)] for m in picked])
    return out


class CompatDataDiff(AdvCodexDiff):
    def test_validate_read_and_summary(self):
        cases = []
        for label, data in documents():
            for product in PRODUCTS:
                cases.append(["cd.validate", data.hex(), product])
            cases.append(["cd.summary", data.hex(), None])
        self.same("validate", cases)
        RECORD.append("compatdata: %d validate and summary cases over %d documents" % (len(cases), len(documents())))

    def test_the_pure_helpers(self):
        cases = []
        for text in ("codex-cli 0.165.0", "codex-cli  0.1", "x", "", "a b c"):
            cases.append(["cd.slug", text])
            cases.append(["cd.evidence_path", text, "mopen"])
        for text in ("0.6.26", "0.6.27-alpha", "0.6.26.1", "1234567.1.1", "１.２.３", "0.6", "", "v0.6.26", "0.6.2a"):
            cases.append(["cd.product", text])
        for value in (document({ENGINE: {"mopen": entry(ENGINE, "mopen")}}), {"a": float("nan"), "b": [float("inf")]},
                      {"é": "\u2603", "list": [1, 2.5, None, True]}, []):
            cases.append(["cd.dumps", value])
        self.same("pure", cases)

    def test_overlay_and_table_for(self):
        rng = random.Random(7202)
        made = [raw(document({ENGINE: {"mopen": entry(ENGINE, "mopen"), "mimg": entry(ENGINE, "mimg", "fail"),
                                       "m2": entry(ENGINE, "m2"), "mx": entry(ENGINE, "mx", "fail")}})),
                raw(document({OLD: {"mopen": entry(OLD, "mopen", "fail")}})), b"{", None]
        for _ in range(20):
            engines = {}
            for version in rng.sample([ENGINE, OLD, "codex-cli 0.170.0"], rng.randint(1, 3)):
                engines[version] = {m: entry(version, m, rng.choice(["pass", "fail"]))
                                    for m in rng.sample(MEASUREMENTS, rng.randint(0, 6))}
            made.append(raw(document(engines)))
        cases = []
        for table in tables(rng):
            if table is None:
                continue
            for data in made:
                for engine in (ENGINE, OLD, "codex-cli 0.170.0", None, 5):
                    cases.append(["cd.overlay", table, None if data is None else data.hex(), [0, 6, 20], engine])
        self.same("overlay", cases)
        RECORD.append("compatdata: %d overlay cases" % len(cases))

    def scenarios(self, rng):
        """(download, adopted, bundled) documents in every order of sequence and freshness."""
        fresh = lambda sequence, **kw: raw(document({ENGINE: {"mopen": entry(ENGINE, "mopen")}}, sequence=sequence, **kw))
        expired = lambda sequence: raw(document({}, sequence=sequence, published=NOW - 100 * 86400, expires=NOW - 86400))
        future = lambda sequence: raw(document({}, sequence=sequence, published=NOW + 2 * 86400))
        soon = lambda sequence: raw(document({}, sequence=sequence, published=NOW + 3600))
        kinds = [None, b"{", b"not json", fresh(1), fresh(3), fresh(4), fresh(9), expired(5), future(6), soon(7),
                 fresh(9, minimum="9.0.0"), raw(document({ENGINE: {"mopen": entry(ENGINE, "mopen", "maybe")}}, sequence=9))]
        out = []
        for _ in range(160):
            out.append((rng.choice(kinds), rng.choice(kinds), rng.choice(kinds)))
        return out

    def test_adoption_and_in_force(self):
        rng = random.Random(7203)
        cases_run = 0
        for index, (download, adopted, bundled) in enumerate(self.scenarios(rng)):
            home = self.root / ("adopt-%d" % index)
            state = home / "config"
            bundle = home / "bundled.json"

            def setup(download=download, adopted=adopted, bundled=bundled, state=state, bundle=bundle):
                state.mkdir(parents=True)
                if download is not None:
                    (state / "compat-advanced.download.json").write_bytes(download)
                if adopted is not None:
                    (state / "compat-advanced.json").write_bytes(adopted)
                if bundled is not None:
                    bundle.write_bytes(bundled)

            now = rng.choice([NOW, NOW + 30 * 86400, NOW + 200 * 86400, NOW - 86400 * 2])
            product = rng.choice([[0, 6, 20], None, "none"])
            cases = [["cd.in_force", str(state), str(bundle) if bundled is not None else None, now, product],
                     ["cd.in_force", str(state), None, now, product],
                     ["cd.table_for", str(state), ENGINE, None, now],
                     ["cd.table_for", str(state), OLD, [["mopen", "pass", OLD], ["m2", "fail", ENGINE]], now],
                     ["cd.read", str(state / "compat-advanced.json"), product]]
            if rng.random() < 0.3:
                cases.insert(0, ["cd.adopt", str(state), str(bundle) if bundled is not None else None, now, product])
            self.scene("adopt %d" % index, cases, setup, [home])
            cases_run += len(cases)
        self.same("no state", [["cd.in_force", None, None, NOW, None], ["cd.table_for", None, ENGINE, None, NOW]])
        RECORD.append("compatdata: 160 homes, %d adoption and in-force cases, the files left equal" % cases_run)

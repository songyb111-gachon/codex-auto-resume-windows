"""S7.1b, the words: vocabulary, standards, the measurement table, the administrator's policy, the registry and the statements.

Each family runs a script under the reference tag's advanced edition (`advref.run`) and the same cases through car-adv's probe
(`advprobe`, an example of the crate); every answer must be the reference's, byte for byte (`advdiff.AdvDiff`).

| Class | Holds equal to the tag |
|---|---|
| VocabularyDiff | all 53 enums (members' values in order), `Enum(text)` for each value and for strangers, TRIPWIRES, KEPT_NOTICES, NOTE_FOR_PASS/FAIL; the standards' lists; the build-time table of measurements |
| PolicyDiff | `policy.read` over thousands of generated registry contents (every kind, wrong kinds, lists, hives, a reader that raises), `admits`, `as_json`, and the real reader's mapping through a registry stand-in on both sides |
| RegistryDiff | the shipped definitions, WAITING and INSTALLED_ONLY as data, `problems()` over every definition and about 45 mutations of each, `Option.takes`, `code`, shapes, a registry made of definitions (requires, required_by, at, shown, every refusal), `offered` and the registry for each combination of the hidden capabilities' measurements |
| StatementDiff | every catalog of the tag, `words`, `text` with fields, the badge, `missing` and `complete_in`, and `statement()` for every definition in every language, on the tag's own directory and on damaged copies of it |
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import shutil

from rustdiff import advref
from rustdiff.advdiff import AdvDiff

RECORD: list[str] = []

VOCAB = r'''
import enum
from codex_auto_resume_advanced import vocabulary, standards, measured
enums = {name: cls for name, cls in vars(vocabulary).items()
         if isinstance(cls, type) and issubclass(cls, enum.Enum) and cls.__module__ == vocabulary.__name__}
cases = [["vocab.enums"], ["vocab.constants"], ["standards.lists"], ["measured.table"]]
strangers = ["", "x", " ", "unknown", "OTHER", "Off", "m1 ", "M1", "pass ", "advanced-list ", "é", "0", "none"]
for name, cls in enums.items():
    for member in cls:
        cases.append(["vocab.parse", name, member.value])
        cases.append(["vocab.parse", name, member.value.upper()])
        cases.append(["vocab.parse", name, member.value + " "])
    for word in strangers:
        cases.append(["vocab.parse", name, word])
cases.append(["vocab.parse", "NoSuchEnum", "x"])
ops = {
    "vocab.enums": lambda: {name: [member.value for member in cls] for name, cls in enums.items()},
    "vocab.parse": lambda name, text: enums[name](text).value,
    "vocab.constants": lambda: {"TRIPWIRES": [str(each) for each in vocabulary.OffReason if each in vocabulary.TRIPWIRES],
                                "KEPT_NOTICES": [str(each) for each in vocabulary.KEPT_NOTICES],
                                "NOTE_FOR_PASS": [str(each) for each in vocabulary.NoteCode if each in vocabulary.NOTE_FOR_PASS],
                                "NOTE_FOR_FAIL": [str(each) for each in vocabulary.NoteCode if each in vocabulary.NOTE_FOR_FAIL]},
    "standards.lists": lambda: {"STANDARDS": list(standards.STANDARDS), "DEPARTABLE": list(standards.DEPARTABLE),
                                "DECLARABLE": list(standards.DECLARABLE), "BINDING": list(standards.BINDING),
                                "BASIS": standards.BASIS, "FAMILIES": [list(each) for each in standards.FAMILIES]},
    "measured.table": lambda: [[str(key), str(verdict), engine] for key, (verdict, engine) in measured.MEASURED.items()],
}
finish(cases, ops)
'''

POLICY = r'''
import random
from codex_auto_resume_advanced import policy
rng = random.Random(20261125)
HIVES = policy.HIVES
NAMES = policy.VALUES
VARIANTS = [None, (0, "dword"), (1, "dword"), (2, "dword"), (-1, "dword"), (4294967295, "dword"), ("1", "text"), ("0", "text"),
            ("", "text"), (None, "other"), ("a,b c;d", "text"), (" a ,, b;;c\t\nd ", "text"), ("A;a", "text"),
            (" x y　z", "text"), ("x\u001cy\u001dz", "text"), (["a", "b c"], "list"), ([], "list"), ([""], "list"),
            (["a,b", "c;d e"], "list"), (["only"], "list"), (7, "list"), ("x", "list"), (["x"], "text"), (5, "text"),
            ("x", "dword"), (None, "dword"), (0, "text"), (0, "list"), (1, "other"), (["a"], "other"), ("z", "other"),
            (["été", "b"], "list"), ("c,b,a", "text"), (["b", "c", "a"], "list"), (["b"], "list"), (["a", "b"], "list"),
            (["b", "c"], "list"), ("start_with_codex goal_continuation", "text"), (["start_with_codex"], "list")]
def entries(table):
    return [[hive, name, found[1], found[0]] for (hive, name), found in table.items()]
def reader(table, raises):
    def read(hive, name):
        if (hive, name) in raises:
            raise policy.Unreadable("denied")
        return table.get((hive, name))
    return read
def one(table, raises):
    return policy.read(reader(table, raises)).as_json()
cases, ops = [], {}
def add(table, raises=()):
    cases.append(["policy.read", entries(table), [list(each) for each in raises]])
for hive in HIVES:
    for name in NAMES:
        for found in VARIANTS:
            add({(hive, name): found} if found is not None else {})
        add({}, [(hive, name)])
add({})
for _ in range(2500):
    table = {}
    for hive in HIVES:
        for name in NAMES:
            if rng.random() < 0.6:
                found = rng.choice(VARIANTS)
                if found is not None:
                    table[(hive, name)] = found
    raises = [(rng.choice(HIVES), rng.choice(NAMES))] if rng.random() < 0.05 else []
    add(table, raises)
ops["policy.read"] = lambda entries_, raises: one({(h, n): (v, k) for h, n, k, v in entries_}, [tuple(r) for r in raises])
# admits and as_json of what was read
ids = ["start_with_codex", "a", "b", "c", "d", "goal_continuation", "", "A", "été", "x y"]
shapes = [{"forbid": f, "force_shadow": s, "allowed": a} for f in (False, True) for s in (False, True)
          for a in (None, [], ["a"], ["a", "b"], ["start_with_codex", "goal_continuation"], ["été", "b"])]
for shape in shapes:
    for capability in ids:
        cases.append(["policy.admits", shape, capability])
ops["policy.admits"] = lambda shape, capability: policy.Policy(
    forbid=shape["forbid"], force_shadow=shape["force_shadow"],
    allowed=None if shape["allowed"] is None else frozenset(shape["allowed"])).admits(capability)
# the real reader, over a stand-in for winreg (and os.name nt), as the tag's own test does it
import sys
from unittest.mock import patch
class FakeWinreg:
    HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER, KEY_READ = "HKLM", "HKCU", 0x20019
    REG_SZ, REG_EXPAND_SZ, REG_DWORD, REG_MULTI_SZ = 1, 2, 4, 7
    def __init__(self, seeds, denied_keys, denied_values):
        self.seeds, self.denied_keys, self.denied_values = seeds, denied_keys, denied_values
    def OpenKey(self, root, key, reserved, access):
        if key != policy.KEY or access != 0x20019:
            raise AssertionError("opened %r with %r" % (key, access))
        if root in self.denied_keys:
            raise PermissionError(5, "denied")
        if not any(hive == root for hive, *_ in self.seeds):
            raise FileNotFoundError(2, "no key")
        outer = self
        class Key:
            def __enter__(self_inner): return (root, outer)
            def __exit__(self_inner, *exc): return False
        return Key()
    def QueryValueEx(self, key, name):
        root, owner = key
        if [root, name] in [list(each) for each in self.denied_values]:
            raise PermissionError(5, "denied")
        found = None
        for hive, seeded, kind, payload in self.seeds:
            if hive == root and seeded == name:
                found = (payload, kind)
        if found is None:
            raise FileNotFoundError(2, "no value")
        return found
def winreg_read(seeds, denied_keys, denied_values):
    fake = FakeWinreg(seeds, denied_keys, denied_values)
    with patch.dict(sys.modules, {"winreg": fake}), patch.object(policy.os, "name", "nt"):
        return policy.read().as_json()
KINDS = [(1, "x"), (1, "a,b c"), (1, "1"), (1, ""), (2, "%X%"), (2, "p;q"), (4, 0), (4, 1), (4, 2), (4, 4294967295),
         (7, []), (7, ["a", "b c"]), (7, ["start_with_codex"]), (7, ["d,e", "f"]), (11, 1), (11, 0), (3, None)]
scenarios = [[[], [], []], [[], ["HKLM"], []], [[], ["HKCU"], []], [[], [], [["HKLM", "ForbidAdvanced"]]]]
for hive in HIVES:
    for name in NAMES:
        for kind, payload in KINDS:
            scenarios.append([[[hive, name, kind, payload]], [], []])
        scenarios.append([[["HKCU" if hive == "HKLM" else "HKLM", name, 4, 1]], [hive], []])
        scenarios.append([[[hive, "ForceShadow", 4, 1]], [], [[hive, name]]])
for _ in range(400):
    seeds = [[rng.choice(HIVES), rng.choice(NAMES), *rng.choice(KINDS)] for _ in range(rng.randint(0, 6))]
    scenarios.append([seeds, [h for h in HIVES if rng.random() < 0.1], [[rng.choice(HIVES), rng.choice(NAMES)]] if rng.random() < 0.1 else []])
for each in scenarios:
    cases.append(["policy.winreg", *each])
def fake_payload(kind, payload):
    return bytes.fromhex("010203") if kind == 3 else payload
ops["policy.winreg"] = lambda seeds, denied_keys, denied_values: winreg_read(
    [(h, n, k, fake_payload(k, p)) for h, n, k, p in seeds], denied_keys, denied_values)
finish(cases, ops)
'''

REGISTRY = r'''
import copy, itertools, random
from codex_auto_resume.domain.plug import Point
from codex_auto_resume_advanced import measured, registry, vocabulary
from codex_auto_resume_advanced.vocabulary import Measurement, Verdict, OptionKey
rng = random.Random(20261125)
shipped = [dump_def(each) for each in registry.DEFINITIONS]
waiting = [[dump_def(each), [str(m) for m in (need if isinstance(need, tuple) else (need,))]] for each, need in registry.WAITING]
installed = [dump_def(each) for each in registry.INSTALLED_ONLY]
every = shipped + [each[0] for each in waiting] + installed
cases, ops = [], {}

def refused(make):
    try:
        return make()
    except registry.RegistryError as error:
        return {"refused": str(error)}

def table_of(rows):
    return {Measurement(m): (Verdict(v), engine) for m, v, engine in rows}

def made(definitions):
    built = registry.Registry([build_def(each) for each in definitions])
    names = list(built.ids) + ["no_such_capability"]
    return {"ids": list(built.ids), "len": len(built),
            "requires": [{"id": name, "requires": list(built.requires(name))} for name in names],
            "required_by": [{"id": name, "required_by": list(built.required_by(name))} for name in names],
            "at": [{"point": str(point), "at": [each.id for each in built.at(point)]} for point in Point],
            "shown": [each.id for each in registry.shown(built)], "get_missing": built.get("no_such_capability") is None}

def shipped_for(rows, install):
    table = table_of(rows)
    built = registry.Registry(registry.DEFINITIONS + registry.offered(table) + (registry.INSTALLED_ONLY if install else ()))
    return {"ids": list(built.ids), "shown": [each.id for each in registry.shown(built)], "definitions": [dump_def(each) for each in built]}

cases.append(["registry.constants"]); cases.append(["registry.definitions"]); cases.append(["registry.waiting"]); cases.append(["registry.installed_only"])
ops["registry.constants"] = lambda: {"GLOBAL_HOURLY": registry.GLOBAL_HOURLY, "CORE_DAILY_CAP": registry.CORE_DAILY_CAP,
                                     "CORE_COOLDOWN_SECONDS": registry.CORE_COOLDOWN_SECONDS, "SHOWN_ORDER": list(registry.SHOWN_ORDER),
                                     "CAPABILITY_POINTS": sorted(str(point) for point in registry.CAPABILITY_POINTS)}
ops["registry.definitions"] = lambda: [dump_def(each) for each in registry.DEFINITIONS]
ops["registry.waiting"] = lambda: waiting
ops["registry.installed_only"] = lambda: installed

# shapes
for text in ["abc", "ab", "a", "", "a" * 47, "a" * 48, "a" * 49, "A", "aB", "a_b", "_ab", "1ab", "a-b", "abc\n", "abcdefgh", "abcdefghi", "ab1",
             "a1", "a" * 31, "a" * 32, "a" * 33, "ééé", "a b", "abc ", "z9_", "zz"]:
    cases.append(["registry.shapes", text])
ops["registry.shapes"] = lambda text: {"id": bool(registry.ID_SHAPE.fullmatch(text)), "prefix": bool(registry.PREFIX_SHAPE.fullmatch(text)),
                                       "code": bool(registry.CODE_SHAPE.fullmatch(text))}

# problems: each definition and its mutants
ALL_POINTS = [str(point) for point in Point]
def mutants(d):
    def m(**changes):
        e = copy.deepcopy(d)
        e.update(changes)
        return e
    out = [d,
           m(id="Bad-Id"), m(id="ab"), m(id=""), m(id="x" * 49),
           m(kind="action"), m(kind="route"),
           m(points=[]), m(points=ALL_POINTS), m(points=["claim_ledger"]), m(points=["surfaces", "tick"]), m(points=["moved"]),
           m(points=["tick", "resident"]), m(points=["resident"]), m(points=["tick", "tick"]), m(points=["records", "resident"]),
           m(revision=0), m(revision=-1), m(revision=2),
           m(departs_from=[]), m(departs_from=["K1"]), m(departs_from=["A2", "A2"]), m(departs_from=["Z9"]), m(departs_from=["A99"]),
           m(departs_from=["0.1", "A20", "F6"]), m(departs_from=d["departs_from"] + ["K5"]),
           m(compat=None), m(compat="Bad"), m(compat="ab"), m(compat="engine_present"),
           m(ceilings=None), m(ceilings=[0, 0]), m(ceilings=[1, 2]), m(ceilings=[48, 6]), m(ceilings=[48, 5]), m(ceilings=[576, 5]),
           m(ceilings=[577, 5]), m(ceilings=[10, 6], departs_from=d["departs_from"] + ["A20"]), m(ceilings=[3, 3]),
           m(journal_prefix=""), m(journal_prefix="a"), m(journal_prefix="abcdefghi"), m(journal_prefix="ab1"), m(journal_prefix="ABC"),
           m(codes=["held", "held"]), m(codes=["Bad"]), m(codes=["a" * 33]), m(codes=["ok_1", "ok_2"]), m(codes=[""]),
           m(measurements=["m1", "m1"]), m(measurements=["m1", "m2"]), m(narrowed_by=["m1"]), m(narrowed_by=["m3", "m3"]),
           m(measurements=[], narrowed_by=["m1"]),
           m(options=[{"key": "days", "choices": [3, 5, 7], "default": 3, "custom": None}]),
           m(options=[{"key": "days", "choices": [7, 5], "default": 5, "custom": None}]),
           m(options=[{"key": "days", "choices": [3, 3], "default": 3, "custom": None}]),
           m(options=[{"key": "days", "choices": [], "default": 3, "custom": None}]),
           m(options=[{"key": "days", "choices": [0, 1], "default": 1, "custom": None}]),
           m(options=[{"key": "days", "choices": [3, 5], "default": 4, "custom": None}]),
           m(options=[{"key": "days", "choices": [3, 5], "default": 0, "custom": None}]),
           m(options=[{"key": "days", "choices": [3, 5], "default": 3, "custom": [1, 10]}]),
           m(options=[{"key": "days", "choices": [3, 5], "default": 3, "custom": [4, 10]}]),
           m(options=[{"key": "days", "choices": [3, 5], "default": 3, "custom": [1, 4]}]),
           m(options=[{"key": "days", "choices": [3, 5], "default": 3, "custom": [0, 9]}]),
           m(options=[{"key": "days", "choices": [3, 5], "default": 3, "custom": [3, 5]}]),
           m(options=[{"key": "days", "choices": [3], "default": 3, "custom": None}, {"key": "days", "choices": [4], "default": 4, "custom": None}]),
           m(options=[{"key": "days", "choices": [3], "default": 3, "custom": None}, {"key": "workers", "choices": [4], "default": 4, "custom": None}]),
           m(resends=True), m(resends=True, points=d["points"] + ["schedule"]), m(resends=False),
           m(requires=[d["id"]]), m(requires=["a_b", "a_b"]), m(requires=["no_such"]), m(requires=[]),
           m(rules_editor=True, samples=True), m(sends=True), m(sends=False)]
    return out
for each in every:
    for variant in mutants(each):
        cases.append(["registry.problems", variant])
ops["registry.problems"] = lambda d: registry.problems(build_def(d))

# options and codes
for each in every:
    for option in each["options"]:
        values = {-1, 0, 1, 2, option["default"], option["default"] + 1, 10**6}
        for choice in option["choices"]:
            values |= {choice - 1, choice, choice + 1}
        if option["custom"]:
            values |= {option["custom"][0] - 1, option["custom"][0], option["custom"][1], option["custom"][1] + 1}
        for value in sorted(values):
            cases.append(["registry.option", each, option["key"], value])
    cases.append(["registry.option", each, "poll_minutes", 5])
    for word in list(each["codes"][:3]) + ["nothing", ""]:
        cases.append(["registry.code", each, word])
ops["registry.option"] = lambda d, key, value: (lambda built: None if built.option(OptionKey(key)) is None else built.option(OptionKey(key)).takes(value))(build_def(d))
ops["registry.code"] = lambda d, word: build_def(d).code(word)

# registries made of definitions
def plain(i, **changes):
    d = copy.deepcopy(shipped[i % len(shipped)])
    d.update(changes)
    return d
lone = lambda i, **c: plain(i, **c)
sets = [shipped, shipped[:10], shipped[:1], [], shipped + [e[0] for e in waiting], shipped + installed,
        [lone(0, id="alpha_cap", journal_prefix="alp", requires=[]), lone(1, id="beta_cap", journal_prefix="bet", requires=["alpha_cap"]),
         lone(2, id="gamma_cap", journal_prefix="gam", requires=["beta_cap", "alpha_cap"]), lone(3, id="delta_cap", journal_prefix="del", requires=["gamma_cap"])],
        [lone(0, id="alpha_cap", journal_prefix="alp", requires=["beta_cap"]), lone(1, id="beta_cap", journal_prefix="bet", requires=["alpha_cap"])],
        [lone(0, id="alpha_cap", journal_prefix="alp", requires=["alpha_cap"])],
        [lone(0, id="alpha_cap", journal_prefix="alp", requires=["ghost_cap"])],
        [lone(0, id="alpha_cap", journal_prefix="alp"), lone(1, id="alpha_cap", journal_prefix="bet")],
        [lone(0, id="alpha_cap", journal_prefix="alp"), lone(1, id="beta_cap", journal_prefix="alp")],
        [lone(0, id="alpha_cap", journal_prefix="alp", revision=0)],
        [lone(0, id="alpha_cap", journal_prefix="alp", requires=["beta_cap"]), lone(1, id="beta_cap", journal_prefix="bet", requires=["gamma_cap"]),
         lone(2, id="gamma_cap", journal_prefix="gam", requires=["alpha_cap"]), lone(3, id="delta_cap", journal_prefix="del")],
        [lone(0, id="zeta_cap", journal_prefix="zet"), lone(1, id="start_with_codex", journal_prefix="swc"), lone(2, id="crash_restart", journal_prefix="crash")]]
for definitions in sets:
    cases.append(["registry.make", definitions])
ops["registry.make"] = lambda definitions: refused(lambda: made(definitions))

# which hidden capabilities a table lets out, and the registry for it
needs = sorted({m for each in waiting for m in each[1]}) + ["m1"]
verdicts = [None, "pass", "fail", "blocked"]
rows_list = [[[str(k), str(v), e] for k, (v, e) in measured.MEASURED.items()], []]
for _ in range(300):
    rows = []
    for name in needs:
        verdict = rng.choice(verdicts)
        if verdict is not None:
            rows.append([name, verdict, rng.choice(["codex-cli 0.167.0-alpha.3.2", "codex-cli 0.1.0", ""])])
    rows_list.append(rows)
for name in needs:
    rows_list.append([[name, "pass", "x"]])
rows_list.append([[name, "pass", "x"] for name in needs])
for rows in rows_list:
    cases.append(["registry.offered", rows])
    cases.append(["registry.shipped", rows, False])
    cases.append(["registry.shipped", rows, True])
ops["registry.offered"] = lambda rows: [each.id for each in registry.offered(table_of(rows))]
ops["registry.shipped"] = lambda rows, install: refused(lambda: shipped_for(rows, install))
finish(cases, ops)
'''

STATEMENT = r'''
import copy, json, os, random, shutil, sys
from pathlib import Path
from codex_auto_resume import l10n
from codex_auto_resume_advanced import registry, statement
from codex_auto_resume_advanced.vocabulary import ArmingWarning
real, scratch = Path(sys.argv[1]), Path(sys.argv[2])
rng = random.Random(20261125)
shipped = [dump_def(each) for each in registry.DEFINITIONS]
cases, ops = [], {}

def current(language):
    os.environ[l10n.ENV_LANG] = language
    l10n._preference = l10n.SYSTEM
    return language

def catalogs(directory, language):
    current(language)
    return statement.Catalogs(directory)

def dumped(table):
    return [[key, value] for key, value in table.items()]

# damaged copies of the tag's own catalogs
def copy_of(name, change):
    target = scratch / name
    shutil.copytree(real, target)
    change(target)
    return str(target)
def write(directory, locale, content):
    (directory / ("%s.json" % locale)).write_text(content, encoding="utf-8")
def edit(directory, locale, function):
    table = json.loads((directory / ("%s.json" % locale)).read_text(encoding="utf-8"))
    function(table)
    write(directory, locale, json.dumps(table, ensure_ascii=False, indent=2))
cap = shipped[0]["id"]
def add_all(directory):
    for locale in l10n.LOCALES:
        edit(directory, locale, lambda table: table.update({statement.key("test_cap", field): "t %s %s" % (locale, field) for field in statement.FIELDS}))
def drop(directory):
    add_all(directory)
    edit(directory, "ko", lambda table: [table.pop(statement.key("test_cap", field), None) for field in list(statement.FIELDS)[1:3]])
    edit(directory, "ja", lambda table: table.update({statement.key("test_cap", "does"): "   "}))
    edit(directory, "de", lambda table: table.update({statement.key("test_cap", "stop"): ""}))
def missing_file(directory):
    add_all(directory)
    (directory / "fr.json").unlink()
def broken_en(directory):
    write(directory, "en", "{ not json")
def broken_layer(directory):
    write(directory, "es", '{"a": 1}')
def duplicate_key(directory):
    write(directory, "it", '{"name.x": "a", "name.x": "b"}')
def not_object(directory):
    write(directory, "pl", '["a"]')
def bom(directory):
    (directory / "tr.json").write_bytes(b"\xef\xbb\xbf" + (directory / "tr.json").read_bytes())
def undecodable_en(directory):
    (directory / "en.json").write_bytes(b'{"page.one": "caf\xe9"}')
def undecodable_layer(directory):
    (directory / "ko.json").write_bytes(b'{"page.one": "\xff\xfe"}')
def undecodable_late(directory):
    (directory / "hu.json").write_bytes(b"\x80")
def tiny(directory):
    write(directory, "en", json.dumps({"page.one": "1 {n}", "name.x": "X", "state.on": "on", "continue.keep_going": "k", "other": "o",
                                       "edition.summary": "{n} on {n}", "edition.not_loaded": "none", "warning.title": "T", "warning.note": "N",
                                       "field.does": "Does", "statement.test_cap.does": "does {x}"}))
    for locale in l10n.LOCALES:
        if locale != "en":
            (directory / ("%s.json" % locale)).unlink()
    write(directory, "ko", json.dumps({"page.one": "한 {n}", "extra": "e"}, ensure_ascii=False))
variants = {"real": str(real), "drop": copy_of("drop", drop), "missing_file": copy_of("missing_file", missing_file),
            "broken_en": copy_of("broken_en", broken_en), "broken_layer": copy_of("broken_layer", broken_layer),
            "duplicate_key": copy_of("duplicate_key", duplicate_key), "not_object": copy_of("not_object", not_object),
            "bom": copy_of("bom", bom), "tiny": copy_of("tiny", tiny), "undecodable_en": copy_of("undecodable_en", undecodable_en),
            "undecodable_layer": copy_of("undecodable_layer", undecodable_layer), "undecodable_late": copy_of("undecodable_late", undecodable_late), "absent": str(scratch / "nowhere")}
LANGS = list(l10n.LOCALES) + ["xx", "KO"]
locales = LANGS + [None]

cases.append(["statement.keys", cap])
ops["statement.keys"] = lambda capability: {
    "fields": [{"key": statement.key(capability, field), "title": statement.title_key(field)} for field in statement.FIELDS],
    "warnings": [statement.warning_key(word) for word in ArmingWarning], "name": statement.name_key(capability),
    "PAGE_KEYS": list(statement.PAGE_KEYS), "CONTINUATION_KEYS": list(statement.CONTINUATION_KEYS),
    "EDITION_KEYS": list(statement.EDITION_KEYS), "WARNING_KEYS": list(statement.WARNING_KEYS)}

for name, directory in variants.items():
    for locale in locales:
        cases.append(["statement.catalog", directory, "en" if locale is None else locale, locale])
        if locale is None:
            cases.append(["statement.catalog", directory, "ko", None])
ops["statement.catalog"] = lambda directory, language, locale: (lambda found: {
    "catalog": dumped(found.catalog(current(language) if locale is None else locale)),
    "words": dumped(found.words(locale))})(catalogs(directory, language))

keys = ["page.one", "name.x", "state.on", "edition.summary", "edition.badge", "edition.not_loaded", "warning.title", "nothing.here",
        "statement.test_cap.does", "field.does", "page.nav", "name." + cap, "continue.keep_going"]
for directory in (variants["real"], variants["tiny"], variants["broken_en"], variants["absent"], variants["undecodable_en"], variants["undecodable_layer"]):
    for key in keys:
        for locale in ("en", "ko", "xx", None):
            cases.append(["statement.text", directory, "ja", key, locale, [["n", "7"], ["x", "{n}"]]])
            cases.append(["statement.text", directory, "ko", key, locale, []])
ops["statement.text"] = lambda directory, language, name, locale, fields: catalogs(directory, language).text(
    name, locale, **{key: value for key, value in fields})

for directory in (variants["real"], variants["tiny"], variants["broken_en"], variants["absent"], variants["missing_file"]):
    for on in (0, 1, 12, -3):
        for locale in ("en", "ko", "ar", "xx", None):
            for loaded in (True, False):
                cases.append(["statement.badge", directory, "he", on, locale, loaded])
ops["statement.badge"] = lambda directory, language, on, locale, loaded: catalogs(directory, language).badge(on, locale, loaded=loaded)

test_cap = copy.deepcopy(shipped[0]); test_cap["id"] = "test_cap"
for name in ("drop", "missing_file", "broken_en", "broken_layer", "tiny", "absent", "undecodable_en", "undecodable_layer", "undecodable_late"):
    for definition in (test_cap, shipped[0]):
        cases.append(["statement.missing", variants[name], "en", definition])
for definition in shipped:
    cases.append(["statement.missing", variants["real"], "en", definition])
ops["statement.missing"] = lambda directory, language, d: (lambda found, definition: {
    "missing": [list(each) for each in found.missing(definition)],
    "complete_in": [[locale, found.complete_in(definition, locale)] for locale in list(l10n.LOCALES) + ["xx"]]})(
        catalogs(directory, language), build_def(d))

warning_sets = [[], [w.value for w in ArmingWarning][:1], [w.value for w in ArmingWarning], [w.value for w in ArmingWarning][::2]]
for definition in shipped:
    for locale in ["en", "ko", "ja", "ar", "xx", None]:
        cases.append(["statement.statement", variants["real"], "de", definition, locale, rng.choice(warning_sets)])
for definition in (test_cap, shipped[0], shipped[5]):
    for name in ("drop", "tiny", "broken_en", "absent", "missing_file", "undecodable_en", "undecodable_layer", "undecodable_late"):
        for locale in ("en", "ko", "ja", None):
            for warnings in warning_sets:
                cases.append(["statement.statement", variants[name], "fr", definition, locale, warnings])
ops["statement.statement"] = lambda directory, language, d, locale, warnings: catalogs(directory, language).statement(
    build_def(d), locale, warnings=[ArmingWarning(each) for each in warnings])
finish(cases, ops)
'''


class VocabularyDiff(AdvDiff):
    def test_words_standards_measured(self):
        done = self.family(VOCAB, label="vocab", expect_ops=700)
        enums = done["results"][0]["ok"]
        RECORD.append("advpolicy vocabulary: %d enums, %d members, %d cases equal (Enum(text) for each value, its upper-case and padded "
                      "forms and 13 strangers); TRIPWIRES, KEPT_NOTICES, NOTE_FOR_*; %d standards in 12 families; %d measurements"
                      % (len(enums), sum(len(each) for each in enums.values()), len(done["cases"]),
                         len(done["results"][2]["ok"]["STANDARDS"]), len(done["results"][3]["ok"])))


class PolicyDiff(AdvDiff):
    def test_policy(self):
        done = self.family(POLICY, label="policy", expect_ops=3000)
        reads = sum(1 for case in done["cases"] if case[0] == "policy.read")
        winreg = sum(1 for case in done["cases"] if case[0] == "policy.winreg")
        refused = sum(1 for case, result in zip(done["cases"], done["results"]) if case[0] == "policy.read"
                      and result["ok"] == {"forbid": True, "force_shadow": True, "allowed": []})
        RECORD.append("advpolicy policy: %d reads (%d the strictest) + %d through the registry reader + %d admits equal"
                      % (reads, refused, winreg, len(done["cases"]) - reads - winreg))


class RegistryDiff(AdvDiff):
    def test_registry(self):
        done = self.family(REGISTRY, label="registry", expect_ops=3000)
        problems = [result for case, result in zip(done["cases"], done["results"]) if case[0] == "registry.problems"]
        made = [result for case, result in zip(done["cases"], done["results"]) if case[0] == "registry.make"]
        shipped = done["results"][1]["ok"]
        RECORD.append("advpolicy registry: %d shipped definitions + %d waiting + %d installed-only; %d problems() cases (%d with a finding), "
                      "%d registries made (%d refused alike), %d cases in all equal"
                      % (len(shipped), len(done["results"][2]["ok"]), len(done["results"][3]["ok"]), len(problems),
                         sum(1 for each in problems if each["ok"]), len(made), sum(1 for each in made if "refused" in each["ok"]),
                         len(done["cases"])))


class StatementDiff(AdvDiff):
    def test_statement(self):
        scratch = Path(self.reference_scratch) / "catalogs"
        scratch.mkdir()
        done = self.family(STATEMENT, str(advref.locales()), str(scratch), label="statement", expect_ops=1400)
        statements = sum(1 for case in done["cases"] if case[0] == "statement.statement")
        RECORD.append("advpolicy statement: %d cases equal over the tag's own catalogs (22 languages) and 12 damaged copies (3 of them not UTF-8); "
                      "%d statements, every definition in six languages" % (len(done["cases"]), statements))
        shutil.rmtree(scratch, ignore_errors=True)

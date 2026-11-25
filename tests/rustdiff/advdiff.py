"""What the S7.1b diffs (diffs_advpolicy_*.py) share: a family of cases run through the advanced reference and car-adv's probe.

A family is a script that runs under the reference tag's advanced edition (`advref.run`) and prints
`{"cases": [[op, arg, ...], ...], "results": [{"ok": value} | {"error": "ClassName"}, ...]}`: the cases it made and what the
tag answered. The same cases go to `advprobe` (car-adv's example, built in the advanced workspace on demand) in one request,
and every answer must equal the reference's, written as the wire writes it (`diffs.encode`). The first case that differs is
named with both answers.

`PRELUDE` is what every script starts with: the case runner, the normaliser that turns tuples and sets into the lists and
sorted lists a JSON answer has, the dump of a capability definition (`dump_def`) and the builder of one from that dump
(`build_def`, `make` being a stand-in: the factory is the plug's, not this seat's).
"""
from __future__ import annotations

import json
import tempfile
import unittest

from rustdiff import advref, diffs

PRELUDE = r'''
import json, os, random, sys

def norm(value):
    if isinstance(value, (set, frozenset)):
        return sorted(norm(each) for each in value)
    if isinstance(value, (tuple, list)):
        return [norm(each) for each in value]
    if isinstance(value, dict):
        return {key: norm(each) for key, each in value.items()}
    return value

def run(cases, ops):
    results = []
    for case in cases:
        try:
            results.append({"ok": norm(ops[case[0]](*case[1:]))})
        except Exception as error:
            results.append({"error": type(error).__name__})
    return results

def finish(cases, ops):
    sys.stdout.write(json.dumps({"cases": cases, "results": run(cases, ops)}, ensure_ascii=False, allow_nan=False))

def dump_def(item):
    return {"id": item.id, "kind": str(item.kind), "points": sorted(str(point) for point in item.points),
            "revision": item.revision, "departs_from": list(item.departs_from), "compat": item.compat,
            "ceilings": None if item.ceilings is None else [item.ceilings.per_day, item.ceilings.per_conversation],
            "journal_prefix": item.journal_prefix, "codes": list(item.codes),
            "measurements": [str(each) for each in item.measurements],
            "options": [{"key": str(each.key), "choices": list(each.choices), "default": each.default,
                         "custom": None if each.custom is None else list(each.custom)} for each in item.options],
            "rules_editor": item.rules_editor, "samples": item.samples, "resends": item.resends,
            "requires": list(item.requires), "wordings": [str(each) for each in item.wordings],
            "narrowed_by": [str(each) for each in item.narrowed_by], "sends": item.sends}

def build_def(d):
    from codex_auto_resume.domain.plug import Point
    from codex_auto_resume_advanced import registry
    from codex_auto_resume_advanced.vocabulary import CapabilityKind, Measurement, OptionKey, WordingKey
    return registry.CapabilityDef(
        id=d["id"], kind=CapabilityKind(d["kind"]), points=frozenset(Point(each) for each in d["points"]),
        revision=d["revision"], departs_from=tuple(d["departs_from"]), compat=d["compat"],
        ceilings=None if d["ceilings"] is None else registry.Ceilings(*d["ceilings"]),
        journal_prefix=d["journal_prefix"], make=lambda paths: None, codes=tuple(d["codes"]),
        measurements=tuple(Measurement(each) for each in d["measurements"]),
        options=tuple(registry.Option(OptionKey(each["key"]), tuple(each["choices"]), each["default"],
                                      None if each["custom"] is None else tuple(each["custom"])) for each in d["options"]),
        rules_editor=d["rules_editor"], samples=d["samples"], resends=d["resends"], requires=tuple(d["requires"]),
        wordings=tuple(WordingKey(each) for each in d["wordings"]),
        narrowed_by=tuple(Measurement(each) for each in d["narrowed_by"]), sends=d["sends"])
'''


class AdvDiff(unittest.TestCase):
    """A diff of car-adv: `family(script)` runs the script in the advanced reference and the same cases in the probe."""

    @classmethod
    def setUpClass(cls):
        advref.ensure()
        cls.reference_scratch = tempfile.mkdtemp(prefix="advdiff-")
        cls.addClassCleanup(__import__("shutil").rmtree, cls.reference_scratch, True)

    def family(self, script: str, *arguments, label: str, expect_ops: int = 1, chunk: int = 6000,
               show=None) -> dict:
        from pathlib import Path
        profile = Path(tempfile.mkdtemp(prefix="advdiff-%s-" % label, dir=self.reference_scratch))
        made = advref.run(PRELUDE + script, *arguments, profile=profile)
        self.assertEqual(made.returncode, 0, made.stderr[-3000:].decode("utf-8", "replace"))
        done = json.loads(made.stdout.decode("utf-8"))
        cases, expected = done["cases"], done["results"]
        self.assertGreaterEqual(len(cases), expect_ops, label)
        actual = []
        for start in range(0, len(cases), chunk):
            answer = advref.ask({"cases": cases[start:start + chunk]})
            actual += answer["results"]
        self.assertEqual(len(actual), len(expected))
        for index, (want, got) in enumerate(zip(expected, actual)):
            if diffs.encode(want) != diffs.encode(got):
                self.fail("%s: case %d differs\n  case      %s\n  reference %s\n  rust      %s" % (
                    label, index, json.dumps(cases[index], ensure_ascii=False)[:600],
                    json.dumps(want, ensure_ascii=False)[:1200], json.dumps(got, ensure_ascii=False)[:1200]))
        return {"cases": cases, "results": expected}

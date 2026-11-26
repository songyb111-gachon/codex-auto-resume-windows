"""What the S1.1 diffs (diffs_leaves_*.py) share: a family of cases run through the reference and through Rust.

A family is a script that runs under the reference tag's own Python (`reference.run`) and prints
`{"cases": [[op, arg, ...], ...], "results": [{"ok": value} | {"error": "ExceptionName"}, ...]}`: the cases it
made and what the tag answered, each answer or each exception's class name. The same cases go to
`car-harness serve` as one `leaves.batch` call, and the reply must be the same bytes the reference's
answers write as (`encode`, the wire's `json.dumps(ensure_ascii=False, allow_nan=False)`). The first
case that differs is named with both answers. A NaN or an infinity, in a case or an answer, crosses as its
`{"$float": ...}` tag (`diffs.TAGGING`): `finish` tags both, and car-harness reads and writes the same tags.

`PRELUDE` is what every family script starts with: the case runner and the normaliser that turns the
reference's tuples and sets into the lists and sorted lists a JSON answer has.
"""
from __future__ import annotations

import json

from rustdiff import core, diffs, reference

PRELUDE = r'''
import json, random, sys

def norm(value):
    if isinstance(value, (set, frozenset)):
        return sorted(norm(each) for each in value)
    if isinstance(value, (tuple, list)):
        return [norm(each) for each in value]
    if isinstance(value, dict):
        return {key: norm(each) for key, each in value.items()}
    return value

KEEP = 64

def nesting(value):
    best, stack = 0, [(value, 0)]
    while stack:
        node, level = stack.pop()
        if isinstance(node, dict):
            best = max(best, level + 1)
            stack.extend((each, level + 1) for each in node.values())
        elif isinstance(node, (list, tuple, set, frozenset)):
            best = max(best, level + 1)
            stack.extend((each, level + 1) for each in node)
    return best

def shallow(value):
    # The runner's own `json.loads` may be 3.13's (2,998 levels): a value nested past KEEP levels is answered as the one-key
    # object "$nested" and its depth, as car-harness's `shallow` does.
    depth = nesting(value)
    return {"$nested": depth} if depth > KEEP else value

def run(cases, ops):
    results = []
    for case in cases:
        try:
            results.append({"ok": norm(shallow(ops[case[0]](*case[1:])))})
        except Exception as error:
            results.append({"error": type(error).__name__})
    return results

def finish(cases, ops):
    results = run(cases, ops)
    sys.stdout.write(json.dumps({"cases": tagged(cases), "results": tagged(results)}, ensure_ascii=False,
                                allow_nan=False))
''' + diffs.TAGGING


class Leaves(diffs.Base):
    """A diff of the leaf crates: `family(script)` runs the script in the reference and the same cases in Rust."""

    def family(self, script: str, *arguments, label: str, expect_ops: int = 1, chunk: int = 4000) -> dict:
        profile = self.profile("reference-%s" % label)
        made = reference.run(PRELUDE + script, *arguments, profile=profile)
        self.assertEqual(made.returncode, 0, made.stderr[-3000:].decode("utf-8", "replace"))
        done = json.loads(made.stdout.decode("utf-8"))
        cases, expected = done["cases"], done["results"]
        self.assertGreaterEqual(len(cases), expect_ops, label)
        actual = []
        with core.Harness(reference.scratch_environment(self.profile("rust-%s" % label))) as harness:
            for start in range(0, len(cases), chunk):
                number, line = harness.call("leaves.batch", cases=cases[start:start + chunk])
                reply = json.loads(line.decode("utf-8"))
                self.assertEqual(reply.get("id"), number, line[:300])
                self.assertTrue(reply["reply"].get("ok"), line[:600])
                actual += reply["reply"]["value"]
        self.assertEqual(len(actual), len(expected))
        for index, (want, got) in enumerate(zip(expected, actual)):
            if diffs.encode(want) != diffs.encode(got):
                self.fail("%s: case %d differs\n  case      %s\n  reference %s\n  rust      %s" % (
                    label, index, json.dumps(cases[index], ensure_ascii=False)[:600],
                    json.dumps(want, ensure_ascii=False)[:600], json.dumps(got, ensure_ascii=False)[:600]))
        return {"cases": cases, "results": expected}

    def rust(self, call: str, **fields):
        """One call to car-harness: the parsed reply's `reply`."""
        with core.Harness(reference.scratch_environment(self.profile("rust-%s" % call.replace(".", "-")))) as harness:
            _number, line = harness.call(call, **fields)
        return json.loads(line.decode("utf-8"))["reply"]

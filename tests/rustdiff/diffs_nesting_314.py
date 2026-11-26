"""How deep `json.loads` and `json.dumps` let a document nest: the bundled Python 3.14.10's, as car-machine follows it.

3.13 stopped `json.loads` at a fixed 2,998 levels. 3.14.10 checks the C stack pointer, so the limit is a stack budget that a
list's level and an object's level spend differently (lists about 16,917, objects 14,314, alternating 15,507; the C
encoder's `json.dumps` lists 15,506, dicts 9,304); it moves by about 20 between processes and with the thread's stack
(REFERENCE-314.md finding A, `rust/crates/car-machine/src/json/depth.rs`). The owner decided on 2026-11-26 that Rust follows
the main-thread numbers per container kind, with an iterative reader and writer.

A live Python cannot be asked about a level exactly (the boundary drifts), so this file holds two things:

* NestingDiff - every case equal to the reference's answer where it is safe from the drift: patterns `L`, `O`, `LO`, `OL`,
  `LLO`, `LOO` (a container kind per level, cycled) with a leaf `0` or an empty innermost container, at 100 and 48 levels
  inside the limit (both accept) and 48 and 100 past it (both refuse), and far from it (1 to 40,000 levels), through
  `json.loads`, `json.raw_decode`, `compat.model.decode` (its hooks) and `json.dumps` with four sets of options; floats and
  constants at the deepest point of `decode`; and the small depths of an indented dump (a depth-dependent output).
* BoundaryDiff - the largest depth each kind takes is found in the reference (bisection, in-process) and in Rust, and they
  must be within 40 levels (the drift is about 20), for `loads` of `L`, `O`, `LO`, `OL`, `dumps` of `L`, `O`, `LO`, and the
  room `decode`'s three hooks need; then Rust alone is held at limit-1, limit and limit+1 for every constant.

Under `--reference-python system` (3.13.15) the whole file differs BY DESIGN: its limits are 2,998 and 2,997 for every kind.
"""
from __future__ import annotations

import json
import unittest

from rustdiff import core, reference, refpython
from rustdiff.leaves import Leaves, PRELUDE

RECORD: list[str] = []

# Runs under the reference: the shapes are built from (pattern, n, leaf) exactly as car-harness's leaves/nesting.rs builds them.
SCRIPT = r'''
import hashlib, json, sys
from codex_auto_resume.compat import model

def kinds(pattern, n):
    return [pattern[index % len(pattern)] == "L" for index in range(n)]

def text_of(shape, leaf):
    out = []
    for index, listed in enumerate(shape):
        if leaf == "empty" and index == len(shape) - 1:
            out.append("[]" if listed else "{}")
            break
        out.append("[" if listed else '{"a":')
    if leaf != "empty":
        out.append(leaf)
    closed = len(shape) - 1 if leaf == "empty" else len(shape)
    out.extend("]" if listed else "}" for listed in reversed(shape[:closed]))
    return "".join(out)

def value_of(shape, leaf):
    value = 0
    for index in range(len(shape) - 1, -1, -1):
        held = None if (leaf == "empty" and index == len(shape) - 1) else value
        if shape[index]:
            value = [] if held is None else [held]
        else:
            value = {} if held is None else {"a": held}
    return value

OPTIONS = {"plain": {}, "indent0": {"indent": 0}, "indent2": {"indent": 2}, "sort": {"sort_keys": True},
           "sep": {"separators": (",", ":")}}

def loads(pattern, n, leaf):
    json.loads(text_of(kinds(pattern, n), leaf))
    return "ok"

def decode(pattern, n, leaf):
    try:
        model.decode(text_of(kinds(pattern, n), leaf).encode("utf-8"), 10 ** 12)
    except model.DocumentError as error:
        return error.code
    return "ok"

def raw_decode(pattern, n, leaf):
    return ["ok", json.JSONDecoder().raw_decode(text_of(kinds(pattern, n), leaf), 0)[1]]

def dumps(pattern, n, leaf, options):
    text = json.dumps(value_of(kinds(pattern, n), leaf), allow_nan=False, **OPTIONS[options])
    return ["ok", len(text), hashlib.sha256(text.encode("utf-8")).hexdigest()]

LOADS_L, LOADS_O, DUMPS_L, DUMPS_O = [int(each) for each in sys.argv[1:5]]

def star(pattern, lists, objects):
    """The largest n whose levels fit: a list costs `objects` units, an object `lists`, the whole is lists * objects."""
    used, count = 0, 0
    while True:
        cost = objects if pattern[count % len(pattern)] == "L" else lists
        if used + cost > lists * objects:
            return count
        used += cost
        count += 1

HOOK_LEVELS = {"1.5": 16, "1e999": 16, "NaN": 33, "-Infinity": 33}  # list levels a parse_float / parse_constant call needs

def star_decode(pattern, leaf):
    """The largest n `compat.decode` takes: the levels fit, an object's `object_pairs_hook` (13 object levels) fits at the
    deepest object, and a float or constant leaf has its hook's room (list levels). Same units as `star`."""
    whole = LOADS_L * LOADS_O
    used, count, last_object = 0, 0, 0
    best = 0
    while True:
        listed = pattern[count % len(pattern)] == "L"
        cost = LOADS_O if listed else LOADS_L
        if used + cost > whole:
            return best
        used += cost
        count += 1
        if not listed:
            last_object = used
        needs = HOOK_LEVELS.get(leaf, 0) * LOADS_O
        room = (not last_object) or last_object + 13 * LOADS_L <= whole
        if room and used + needs <= whole:
            best = count

cases = []
FAR = [1, 2, 3, 10, 100, 1000, 3000, 4000, 9000, 14000, 20000, 40000]
for pattern in ("L", "O", "LO", "OL", "LLO", "LOO"):
    for leaf in ("0", "empty"):
        for op in ("json.loads", "json.decode", "json.raw_decode"):
            n_star = star_decode(pattern, leaf) if op == "json.decode" else star(pattern, LOADS_L, LOADS_O)
            for n in FAR + [n_star - 100, n_star - 48, n_star + 48, n_star + 100]:
                cases.append([op, pattern, n, leaf])
# the constants and the hooks' room at the deepest point of decode: a float, a NaN, an infinite
for leaf in ("1.5", "NaN", "1e999", "-Infinity"):
    for pattern in ("L", "O", "LO"):
        for op in ("json.loads", "json.decode"):
            n_star = star_decode(pattern, leaf) if op == "json.decode" else star(pattern, LOADS_L, LOADS_O)
            for n in (1, 10, 5000, n_star - 100, n_star - 48, n_star + 48, n_star + 100):
                cases.append([op, pattern, n, leaf])
for pattern in ("L", "O", "LO", "LLO"):
    n_star = star(pattern, DUMPS_L, DUMPS_O)
    near = [n_star - 100, n_star - 48, n_star + 48, n_star + 100]
    for leaf in ("0", "empty"):
        for options in ("plain", "indent0", "sort", "sep"):
            for n in FAR + near:
                cases.append(["json.dumps", pattern, n, leaf, options])
        for pattern_small in (pattern,):
            for n in range(1, 31):
                for options in ("indent2", "indent0", "plain", "sep"):
                    cases.append(["json.dumps", pattern_small, n, leaf, options])

ops = {"json.loads": loads, "json.decode": decode, "json.raw_decode": raw_decode, "json.dumps": dumps}
finish(cases, ops)
'''

# What the reference finds for itself, in-process: the largest n each kind takes (the same bisection as Rust's `json.bisect`).
BISECT = r'''
import json, sys
from codex_auto_resume.compat import model

def kinds(pattern, n):
    return [pattern[index % len(pattern)] == "L" for index in range(n)]

def text_of(shape, leaf):
    return "".join("[" if listed else '{"a":' for listed in shape) + leaf + "".join("]" if listed else "}" for listed in reversed(shape))

def nested(shape):
    value = [] if shape[-1] else {}
    for listed in reversed(shape[:-1]):
        value = [value] if listed else {"a": value}
    return value

def loads_ok(pattern):
    def accepts(n):
        try:
            json.loads(text_of(kinds(pattern, n), "0"))
            return True
        except RecursionError:
            return False
    return accepts

def dumps_ok(pattern):
    def accepts(n):
        try:
            json.dumps(nested(kinds(pattern, n)), allow_nan=False)
            return True
        except RecursionError:
            return False
    return accepts

def hook_ok(pattern, leaf):
    def accepts(n):
        try:
            model.decode(text_of(kinds(pattern, n), leaf).encode(), 10 ** 12)
        except model.DocumentError as error:
            return error.code != "too_deep"
        return True
    return accepts

def largest(accepts):
    low, high = 1, 1000
    while accepts(high):
        low, high = high, high * 2
    while high - low > 1:
        middle = (low + high) // 2
        if accepts(middle):
            low = middle
        else:
            high = middle
    return low

found = {"loads:L": largest(loads_ok("L")), "loads:O": largest(loads_ok("O")), "loads:LO": largest(loads_ok("LO")),
         "loads:OL": largest(loads_ok("OL")), "dumps:L": largest(dumps_ok("L")), "dumps:O": largest(dumps_ok("O")),
         "dumps:LO": largest(dumps_ok("LO")), "hook:O": largest(hook_ok("O", "0")),
         "hook:float": largest(hook_ok("L", "1.5")), "hook:nan": largest(hook_ok("L", "NaN"))}
sys.stdout.write(json.dumps({"version": sys.version.split()[0], "found": found}))
'''

BAND = 40  # the drift between processes is about 20 levels; the reference's own run-to-run spread


class Nesting(Leaves):
    def ask(self, label: str, cases: list) -> dict:
        """One `leaves.batch` call to car-harness, on a scratch profile of its own."""
        with core.Harness(reference.scratch_environment(self.profile("rust-nesting-" + label))) as harness:
            _number, line = harness.call("leaves.batch", cases=cases)
        return json.loads(line.decode("utf-8"))["reply"]

    def limits(self) -> list:
        reply = self.ask("limits", [["json.limits"]])
        self.assertTrue(reply.get("ok"), reply)
        return reply["value"][0]["ok"]

    def check_reference(self) -> None:
        version = refpython.version()
        if not version.startswith("3.14."):
            self.fail("this file holds Rust to Python 3.14's nesting limits; the reference runs on %s, whose limits differ "
                      "BY DESIGN (3.13: 2,998 for every kind)" % version)


class NestingDiff(Nesting):
    def test_every_shape_far_from_a_limit_or_well_inside_the_band(self):
        self.check_reference()
        limits = self.limits()
        done = self.family(SCRIPT, *limits, label="nesting-cases", chunk=60)
        results = done["results"]
        ok = sum(1 for each in results if "ok" in each)
        deep = sum(1 for each in results if each.get("error") == "RecursionError" or each.get("ok") == "too_deep")
        self.assertGreater(ok, 500, ok)
        self.assertGreater(deep, 300, deep)
        RECORD.append("nesting (follow 3.14): %d cases (%d taken, %d refused for depth) of json.loads, raw_decode, decode and "
                      "dumps (plain, indent 0 and 2, sort_keys, compact) on six container patterns and four leaf kinds, 48 and "
                      "100 levels each side of every limit and far from it, equal to the reference on %s"
                      % (len(results), ok, deep, refpython.version()))


class BoundaryDiff(Nesting):
    def test_each_kinds_largest_depth_is_the_references_within_the_drift(self):
        self.check_reference()
        made = reference.run(BISECT, profile=self.profile("reference-nesting-bisect"))
        self.assertEqual(made.returncode, 0, made.stderr[-3000:].decode("utf-8", "replace"))
        measured = json.loads(made.stdout.decode("utf-8"))
        names = list(measured["found"])
        reply = self.ask("bisect", [["json.bisect", name] for name in names])
        self.assertTrue(reply.get("ok"), reply)
        ours = {name: each["ok"] for name, each in zip(names, reply["value"])}
        lines = []
        for name in names:
            gap = ours[name] - measured["found"][name]
            lines.append("%s %d (Python %d)" % (name, ours[name], measured["found"][name]))
            self.assertLessEqual(abs(gap), BAND, "%s: Rust takes %d levels, Python %s takes %d (more than %d apart): %s"
                                 % (name, ours[name], measured["version"], measured["found"][name], BAND, lines))
        RECORD.append("nesting boundaries on Python %s: %s; each within %d levels" % (measured["version"], "; ".join(lines), BAND))

    def test_rust_alone_at_limit_minus_one_limit_and_limit_plus_one(self):
        limits = self.limits()
        lists, objects, dump_lists, dump_objects = limits
        # the owner's numbers (2026-11-26): the middle of the runs `json/depth.rs` records
        self.assertEqual(limits, [16917, 14314, 15506, 9304])
        cases = []
        for op, pattern, edge, extra in (("json.loads", "L", lists, ["0"]), ("json.loads", "O", objects, ["0"]),
                                          ("json.raw_decode", "L", lists, ["0"]), ("json.raw_decode", "O", objects, ["0"]),
                                          ("json.dumps", "L", dump_lists, ["0", "plain"]), ("json.dumps", "O", dump_objects, ["0", "sort"]),
                                          ("json.dumps", "L", dump_lists, ["empty", "plain"]),
                                          ("json.dumps", "O", dump_objects, ["empty", "plain"])):
            for n in (edge - 1, edge, edge + 1):
                cases.append([op, pattern, n] + extra)
        # `compat.decode`'s hooks: an object closing takes 13 object levels, a float 16 list levels, a constant 33
        cases += [["json.decode", "O", objects - 14, "0"], ["json.decode", "O", objects - 13, "0"], ["json.decode", "O", objects - 12, "0"],
                  ["json.decode", "L", lists - 17, "1.5"], ["json.decode", "L", lists - 16, "1.5"], ["json.decode", "L", lists - 15, "1.5"],
                  ["json.decode", "L", lists - 34, "NaN"], ["json.decode", "L", lists - 33, "NaN"], ["json.decode", "L", lists - 32, "NaN"]]
        reply = self.ask("edges", cases)
        self.assertTrue(reply.get("ok"), reply)
        answers = [each.get("ok", each.get("error")) for each in reply["value"]]
        answers = [each if isinstance(each, str) else each[0] for each in answers]
        refused = "RecursionError"
        # every edge: limit-1 and limit taken, limit+1 refused; then the hook cases, three each: inside the room, at its
        # edge, one past it (a float or a constant is refused for what it is where it fits)
        expected = ["ok", "ok", refused] * 8
        expected += ["ok", "ok", "too_deep", "ok", "ok", "too_deep", "not_finite", "not_finite", "too_deep"]
        self.assertEqual(answers, expected, cases)
        RECORD.append("nesting limits held by Rust alone (the reference cannot say limit +-1: it drifts by 20): limit-1, limit "
                      "and limit+1 for loads of lists (%d) and objects (%d), raw_decode, dumps of lists (%d) and dicts (%d), "
                      "and the edges of decode's three hooks" % tuple(limits))


if __name__ == "__main__":
    unittest.main()

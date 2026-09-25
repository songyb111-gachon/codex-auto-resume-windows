"""The typed contracts in `control/wire.py`, held to what the wire actually carries.

A type that says more than the reply is a promise a Rust port would build and nobody would keep,
and a reply that carries more than the type is a field a port would drop. So each contract is
checked against every golden answer that holds its shape (`tests/golden/`), both ways:

  * every key a reply carries is declared, and every declared key is carried by some reply;
  * a key the contract requires is in every reply, not only in some;
  * every value seen fits the declared type - `float` takes a JSON integer, `bool` is not an
    `int`, and None only where the type says `| None`.

`tests/test_consumer_fields.py` holds the other side: every field the window or the panel reads
is a key of the contract its receiver is typed with (its TYPED table).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import types
import typing
import unittest

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from codex_auto_resume.control import wire  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"

ROW = [("bridge:pending", "pending[]"), ("bridge:pending-all", "pending[]"),
       ("bridge:history", "history[]"), ("bridge:dashboard", "pending[]"),
       ("bridge:dashboard", "history[]")]
COMPAT = [("bridge:compatibility", "compatibility"), ("bridge:compat-refresh", "result.compatibility")]

# Every contract, and where on the wire its shape is found. The base RecordView has no place
# of its own: it is PendingRow without the four keys the listings add, which is checked below.
WHERE = {
    wire.PendingRow: ROW,
    wire.TimelineEvent: [("bridge:timeline", "result.events[]")],
    wire.WatcherView: [("bridge:status", "status.watcher"), ("bridge:dashboard", "status.watcher")],
    wire.StatusSnapshot: [("bridge:status", "status"), ("bridge:dashboard", "status")],
    wire.Statistics: [("bridge:statistics", "result"), ("bridge:dashboard", "week")],
    wire.Outcomes: [("bridge:statistics", "result.outcomes"), ("bridge:dashboard", "week.outcomes")],
    wire.CompatView: COMPAT,
    wire.CompatEngine: [(source, path + ".engine") for source, path in COMPAT],
    wire.CompatData: [(source, path + ".data") for source, path in COMPAT],
    wire.CompatCapability: [(source, path + ".capabilities.*") for source, path in COMPAT],
    # v0.6.10: what others report, beside the version. On the bridge only - the MCP summary
    # never carries it (tests/test_compat_surfaces.py).
    wire.CompatReported: [(source, path + ".reported") for source, path in COMPAT],
    wire.SchemaField: [("bridge:describe", "schema[]")],
}


def golden(source):
    kind, name = source.split(":", 1)
    path = GOLDEN / kind / ("%s.json" % name)
    return json.loads(path.read_text(encoding="utf-8"))


def replies(document):
    for case in document.get("cases", []):
        if "reply" in case:
            yield case["reply"]


def walk(value, parts):
    if not parts:
        yield value
        return
    head, rest = parts[0], parts[1:]
    if isinstance(value, list):
        for item in value:
            yield from walk(item, parts)
        return
    if not isinstance(value, dict):
        return
    many = head.endswith("[]")
    key = head[:-2] if many else head
    if key == "*":
        for item in value.values():
            yield from walk(item, rest)
    elif key in value:
        child = value[key]
        if many and isinstance(child, list):
            for item in child:           # `pending[]`: each row, not the list of them
                yield from walk(item, rest)
        else:
            yield from walk(child, rest)


def found(contract):
    """Every dict on the wire where this contract's shape is."""
    seen = []
    for source, path in WHERE[contract]:
        for reply in replies(golden(source)):
            seen += [value for value in walk(reply, [p for p in path.split(".") if p])
                     if value is not None]
    return seen


def fits(value, hint) -> bool:
    """Whether a JSON value is one the type hint allows."""
    if hint is typing.Any or hint is object:
        return True
    if hint is type(None):
        return value is None
    origin = typing.get_origin(hint)
    if origin in (typing.Union, types.UnionType):
        return any(fits(value, arm) for arm in typing.get_args(hint))
    if hint is bool:
        return isinstance(value, bool)
    if hint is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if hint is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if hint is str:
        return isinstance(value, str)
    if hint is list or origin is list:
        arms = typing.get_args(hint)
        return isinstance(value, list) and (not arms or all(fits(item, arms[0]) for item in value))
    if hint is dict or origin is dict:
        arms = typing.get_args(hint)
        return isinstance(value, dict) and (not arms or all(
            isinstance(key, str) and fits(item, arms[1]) for key, item in value.items()))
    if typing.is_typeddict(hint):
        return isinstance(value, dict) and not problems(hint, value)
    raise AssertionError("no rule for the type %r" % (hint,))


def problems(contract, value) -> list:
    hints = typing.get_type_hints(contract)
    wrong = ["missing %s" % key for key in sorted(contract.__required_keys__ - set(value))]
    wrong += ["undeclared %s" % key for key in sorted(set(value) - set(hints))]
    wrong += ["%s=%r is not %s" % (key, value[key], hints[key]) for key in sorted(set(value) & set(hints))
              if not fits(value[key], hints[key])]
    return wrong


class ContractTests(unittest.TestCase):
    def test_every_contract_is_held_to_the_wire(self):
        self.assertEqual({c.__name__ for c in wire.CONTRACTS} - {c.__name__ for c in WHERE},
                         {"RecordView"}, "a contract no golden answer is compared with")

    def test_every_reply_fits_its_contract(self):
        for contract in WHERE:
            seen = found(contract)
            with self.subTest(contract.__name__):
                self.assertTrue(seen, "no golden answer carries this shape; the check would be empty")
                for value in seen:
                    self.assertEqual(problems(contract, value), [])

    def test_every_declared_key_is_carried_somewhere(self):
        """A key no reply carries is a field a port would build for nothing, or a golden that
        does not cover the case that carries it."""
        for contract in WHERE:
            with self.subTest(contract.__name__):
                carried = set().union(*(set(value) for value in found(contract)))
                self.assertEqual(sorted(set(typing.get_type_hints(contract)) - carried), [])

    def test_a_row_is_a_record_and_what_the_listings_add(self):
        added = set(typing.get_type_hints(wire.PendingRow)) - set(typing.get_type_hints(wire.RecordView))
        self.assertEqual(added, {"thread_enabled", "name", "project", "cwd_basename"})

    def test_describe_record_builds_exactly_a_record_view(self):
        """The producer itself, not only its golden: every key describe_record writes."""
        import ast
        import inspect
        from codex_auto_resume.control import records
        tree = ast.parse(inspect.getsource(records.describe_record))
        built = next(node for node in ast.walk(tree) if isinstance(node, ast.Return)).value
        self.assertEqual({key.value for key in built.keys}, set(typing.get_type_hints(wire.RecordView)))

    def test_reported_for_builds_exactly_a_compat_reported(self):
        """The producer of `reported`, in every state it can be in, not only the one the goldens
        happen to hold (no engine is found there, so each golden says `unavailable`)."""
        import tempfile
        from unittest.mock import patch
        from codex_auto_resume import compat
        from codex_auto_resume.compat import reported, views
        self.assertEqual(set(typing.get_type_hints(wire.CompatReported)), {"state", *reported.COUNTS})
        usable = {"status": "ok", "engine": {"found": True, "version": "codex-cli 0.153.4"}}
        entry = {"version": "codex-cli 0.153.4", "reports": 2, "worked": 1, "failed": 1, "neither": 0, "both": 0}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reported.json"
            for raw in (None, b"{", json.dumps({"format": reported.FORMAT, "versions": []}),
                        json.dumps({"format": reported.FORMAT, "versions": [entry]})):
                if raw is not None:
                    (path.write_bytes if isinstance(raw, bytes) else path.write_text)(raw)
                with patch.object(reported, "BUNDLED", path):
                    for view in (usable, compat.unusable_view("absent")):
                        answer = views.reported_for(view)
                        with self.subTest(raw=raw, status=view["status"], state=answer["state"]):
                            self.assertEqual(problems(wire.CompatReported, answer), [])
                            self.assertIs(type(answer["state"]), str, "the word, not the enum")

    def test_the_checker_refuses_what_it_should(self):
        """Not vacuous: each rule, broken on purpose, is caught."""
        self.assertFalse(fits(True, int), "a bool is not an int")
        self.assertFalse(fits(None, float))
        self.assertTrue(fits(3, float), "a JSON integer is a float")
        self.assertFalse(fits(["a", 1], list[str]))
        self.assertIn("missing name", problems(wire.CompatEngine, {"found": True, "version": None})
                      + problems(wire.SchemaField, {"type": "bool", "group": "g", "category": "c",
                                                    "default": False, "master": False}))
        self.assertIn("undeclared extra", problems(wire.CompatEngine,
                                                   {"found": True, "version": None, "extra": 1}))


if __name__ == "__main__":
    unittest.main()

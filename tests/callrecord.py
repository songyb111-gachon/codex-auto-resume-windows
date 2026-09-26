"""A worker that runs scenarios and writes down every call they made of a Codex backend.

It runs under whichever package is first on its path - this checkout's, or a tagged release's
taken out of git by tests/released.py - and imports nothing of the package before a scenario asks
for it, so the same scenario, from the same unchanged test module, runs against either. What it
records is what tests/neutral.py records: every call an engine made of the backend it was built
with, by name and in order, with its positional arguments and the names of its keywords. The ids a
scenario makes up are drawn from one seed, so two runs of one scenario make up the same ones.

It depends on nothing the package gained after v0.6.10: an engine is still built by
`engine/options.py`'s OptionsMixin, and that is all it patches. tests/test_released_calls.py starts
these and compares. Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import json
import random
import sys
import unittest
from unittest import mock
import uuid

# Every call an engine can make of a backend (tests/neutral.py, BACKEND_CALLS).
BACKEND_CALLS = ("send", "delete_queue", "loaded", "usage", "app_identity")


def plain(value):
    """`value` as JSON carries it; anything else as its repr."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    return repr(value)


def run_one(test_id: str, seed: str) -> dict:
    """One scenario as written: whether it passed, how many engines it built, and every backend call."""
    from codex_auto_resume.engine import options
    calls, engines = [], []
    drawn = random.Random(seed)

    def uuid4():
        return uuid.UUID(int=drawn.getrandbits(128), version=4)

    built = options.OptionsMixin.__init__

    def build_engine(self, store, source, backend, *args, **kwargs):
        built(self, store, source, backend, *args, **kwargs)
        engines.append(True)
        if getattr(backend, "_released_recorded", False):
            return
        for name in BACKEND_CALLS:
            method = getattr(backend, name, None)
            if method is None:
                continue

            def recorded(*arguments, _name=name, _method=method, **keywords):
                calls.append([_name, plain(list(arguments)), sorted(keywords)])
                return _method(*arguments, **keywords)
            setattr(backend, name, recorded)
        try:
            backend._released_recorded = True
        except AttributeError:
            pass

    tests = []

    def flatten(suite):
        for test in suite:
            (tests.append(test) if isinstance(test, unittest.TestCase) else flatten(test))

    flatten(unittest.defaultTestLoader.loadTestsFromName(test_id))
    if len(tests) != 1:
        raise LookupError("%s names %d tests" % (test_id, len(tests)))
    result = unittest.TestResult()
    with mock.patch.object(uuid, "uuid4", uuid4), \
            mock.patch.object(options.OptionsMixin, "__init__", build_engine):
        unittest.TestSuite([tests[0]]).run(result)
    problems = [text.strip().splitlines()[-1] for _, text in result.errors + result.failures]
    return {"ok": result.wasSuccessful(), "engines": len(engines), "calls": calls,
            "problems": problems[:3]}


def serve() -> None:
    """One scenario id a line in, one JSON result a line out, until the input ends. The package is
    imported first, from the front of the path, before any test module can put another there."""
    import codex_auto_resume
    from codex_auto_resume.engine import options  # noqa: F401 - loaded now, from this package
    out = sys.stdout
    sys.stdout = sys.stderr
    out.write(json.dumps({"package": codex_auto_resume.__file__}) + "\n")
    out.flush()
    for line in sys.stdin:
        test_id = line.strip()
        if not test_id:
            continue
        try:
            result = run_one(test_id, test_id)
        except Exception as exc:                        # noqa: BLE001 - reported, not raised
            result = {"error": "%s: %s" % (type(exc).__name__, exc)}
        result["id"] = test_id
        out.write(json.dumps(result) + "\n")
        out.flush()

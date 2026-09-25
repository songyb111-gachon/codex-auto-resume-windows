"""A capability of the tests' own, and a home to run it in, for every advanced test.

The registry this edition ships is empty, so every rule of the registry, the arming, the ledger
and the surfaces is held here against a capability defined by the tests: `definition()` makes
one, `Code` is its code - it answers what a test tells it to - and `catalogs()` writes its
statement into a copy of the shipped catalogs, in all nine languages.

Nothing here reaches the real machine. Every runtime is given a policy and a Compatibility
Registry view of the test's own (`AdvancedCase.policy`, `AdvancedCase.compat`), so no test reads
the real Software\\Policies keys or the real Codex installation, and every home is a temporary
directory.

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "tests", ROOT / "advanced" / "src", ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from codex_auto_resume import config, l10n  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402
from codex_auto_resume_advanced import plug as advanced, policy, statement  # noqa: E402
from codex_auto_resume_advanced.registry import CapabilityDef, Ceilings, Registry  # noqa: E402
from codex_auto_resume_advanced.runtime import Runtime  # noqa: E402

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER_THREAD = "0a1b2c3d-0001-7000-8000-000000000002"
KEY = "a" * 64
ENGINE = "0.155.0"
NOW = 1_800_000_000.0
COMPAT = "not_loaded_recovery"


class Code:
    """A test capability's code: every hook answers what `answers` says - a value, a callable
    given the hook's arguments, or an exception to raise - and DEFER otherwise."""

    def __init__(self, paths):
        self.paths = paths
        self.answers, self.asked = {}, []

    def _answer(self, hook, *arguments):
        self.asked.append(hook)
        answer = self.answers.get(hook, DEFER)
        if isinstance(answer, Exception):
            raise answer
        return answer(*arguments) if callable(answer) else answer

    def __getattr__(self, hook):
        if hook.startswith("_") or hook in ("paths", "answers", "asked"):
            raise AttributeError(hook)
        return lambda *arguments: self._answer(hook, *arguments)


def definition(**changes) -> CapabilityDef:
    """A capability the tests own: wakes a conversation, say. Every field can be changed."""
    made = {}

    def make(paths):
        made.setdefault("code", Code(paths))
        return made["code"]

    fields = dict(id="test_wake", points=frozenset({Point.GATES, Point.TEXT, Point.SENDER,
                                                    Point.TICK, Point.SCHEDULE}),
                  revision=1, departs_from=("A11",), compat=COMPAT,
                  ceilings=Ceilings(per_day=3, per_conversation=2), journal_prefix="tw",
                  make=make, codes=("woke", "slept"))
    fields.update(changes)
    return CapabilityDef(**fields)


def code_of(runtime, capability="test_wake") -> Code:
    return runtime._code_of(runtime.registry.get(capability))


def catalogs(where, *definitions, leave_out=()) -> statement.Catalogs:
    """The shipped catalogs, copied into `where`, with a statement for each of `definitions` in
    every language - except the (locale, field) pairs in `leave_out`."""
    directory = Path(where) / "locales"
    shutil.copytree(statement.DIRECTORY, directory)
    for locale in l10n.LOCALES:
        path = directory / ("%s.json" % locale)
        table = json.loads(path.read_text(encoding="utf-8"))
        for made in definitions:
            for field in statement.FIELDS:
                if (locale, str(field)) not in leave_out:
                    table[statement.key(made.id, field)] = "%s %s (%s)" % (made.id, field, locale)
        path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    return statement.Catalogs(directory)


def view(state="COMPATIBLE", *, version=ENGINE, capability=COMPAT, reason="local_checks_passed"):
    """A Compatibility Registry view as compat.permits reads one."""
    return {"status": "ok", "engine": {"found": True, "version": version},
            "capabilities": {capability: {"state": state, "reason": reason}}}


class AdvancedCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "home"
        self.paths = config.Paths(self.home)
        self.now = NOW
        self.policy = policy.NONE
        self.compat = view()
        self.catalogs = catalogs(temporary.name, definition())

    def options(self, *definitions) -> dict:
        return dict(registry=Registry(definitions or (definition(),)), clock=lambda: self.now,
                    policy=lambda: self.policy, view=lambda: self.compat, catalogs=self.catalogs)

    def runtime(self, *definitions) -> Runtime:
        made = Runtime(self.paths, **self.options(*definitions))
        self.addCleanup(made.state.close)
        return made

    def plug(self, *definitions) -> advanced.AdvancedPlug:
        made = advanced.AdvancedPlug(self.paths, **self.options(*definitions))
        self.addCleanup(lambda: made._runtime and made._runtime.state.close())
        return made

    def arm(self, runtime, capability="test_wake", state="armed", **changes):
        request = dict(state=state, revision=runtime.registry.get(capability).revision,
                       generation=runtime.state.meta()["generation"], acknowledged_version=ENGINE,
                       actor="dashboard")
        request.update(changes)
        return runtime.arming.arm(capability, **request)

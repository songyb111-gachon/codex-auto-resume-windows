"""The harness the capabilities that take failures up are held against (v0.6.14, stage 3b).

Core's own engine, store and simulated Codex home (tests/codexsim.py, through test_plug_points'
PluggedCase), with an advanced plug that ships one capability - the shipped definition and its
shipped statement - and a policy, a Compatibility Registry view and a table of measurements of the
test's own, on which it arms with no warning. No test reads the real policy keys or the real Codex.

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from advancedcase import ENGINE  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume_advanced import policy, statement  # noqa: E402
from codex_auto_resume_advanced.registry import Registry  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor  # noqa: E402
from test_engine import T1, TURN_A, fail_turn  # noqa: E402
from test_plug_points import PluggedCase, failed  # noqa: E402


class TakingCase(PluggedCase):
    """`DEFINITION` is the shipped capability under test; `BESIDE`, shipped ones armed beside it."""
    DEFINITION = None
    BESIDE = ()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.where = Path(temporary.name)
        self.compat = ac.view(capability=self.DEFINITION.compat)
        self.policy = policy.NONE
        self.measured = {}
        super().setUp()

    @property
    def cap(self) -> str:
        return self.DEFINITION.id

    def advanced(self, h=None):
        h = h or self.h
        made = ac.advanced.AdvancedPlug(
            config.Paths(self.where / ("home-%d" % id(h))), registry=Registry((*self.BESIDE, self.DEFINITION)),
            clock=lambda: h.now, policy=lambda: self.policy, view=lambda: self.compat,
            measured=lambda: self.measured, catalogs=statement.CATALOGS)
        self.addCleanup(lambda: made._runtime and made._runtime.state.close())
        return made

    def arm(self, plug, state="armed", capability=None, **changes):
        runtime = plug.runtime
        definition = runtime.registry.get(capability or self.cap)
        request = dict(state=state, revision=definition.revision,
                       generation=runtime.state.meta()["generation"], acknowledged_version=ENGINE,
                       actor=Actor.DASHBOARD)
        request.update(changes)
        result = runtime.arming.arm(definition.id, **request)
        self.assertTrue(result["done"], result)
        runtime.states(fresh=True)
        return result

    def armed(self, h=None, state="armed"):
        """The capability on (or watched), and the harness's engine rebuilt with its plug."""
        h = h or self.h
        plug = self.advanced(h)
        for definition in self.BESIDE:
            self.arm(plug, capability=definition.id)
        self.arm(plug, state=state)
        self.plugged(plug, h)
        return plug

    def failing(self, error_json=None, h=None, *, thread=T1, turn=TURN_A):
        """A failed turn, a second after now: after the capability stood where it stands, which is
        all a capability ever takes up."""
        h = h or self.h
        h.now += 1
        return failed(h, error_json, thread=thread, turn=turn, completed=h.now)

    def again(self, h, error_json, *, step=10, thread=T1):
        """The continuation that is due goes, Codex runs it, and its turn fails with `error_json`:
        the record of that failure."""
        sent = len(h.backend.send_calls)
        for _ in range(240):
            h.tick(advance=step)
            if len(h.backend.send_calls) > sent:
                break
        self.assertEqual(len(h.backend.send_calls), sent + 1, "a continuation was sent")
        turn = h.home.dispatch(thread, status="inProgress", progress=False)
        fail_turn(h.home, thread, turn, error_json=error_json)
        h.tick(advance=1)
        return h.records(thread)[-1]

    def spends(self, plug):
        if not plug.runtime.state.exists():
            return []
        with contextlib.closing(sqlite3.connect(plug.runtime.state.path)) as connection:
            return connection.execute("SELECT capability, thread_id, interruption_id FROM spend").fetchall()

    def journal(self, plug):
        return [(line["code"], line["point"], line["answer"])
                for line in plug.runtime.state.journal(capability=self.cap)]

    def fill(self, plug, count, thread=lambda index: T1, *, at=None):
        """`count` units this capability spent, a minute ago, each on the conversation `thread` names."""
        state = plug.runtime.state
        with state._transaction() as connection:
            for index in range(count):
                state.record_spend(connection, "main", self.cap, thread(index), "%064x" % (index + 1),
                                   (self.h.now if at is None else at) - 60)

    def choose(self, plug, key, value):
        runtime = plug.runtime
        result = runtime.arming.set_option(self.cap, key, value, generation=runtime.state.meta()["generation"],
                                           actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)

    def standard(self, error_json, *, h=None):
        """What the standard edition registers for this failure: (category, state, next look, error)."""
        h = h or self.fresh()
        failed(h, error_json, completed=h.now)
        h.tick()
        row = h.record()
        return None if row is None else (row["category"], row["state"], row["next_retry_at"] - h.now,
                                         row["last_error"])

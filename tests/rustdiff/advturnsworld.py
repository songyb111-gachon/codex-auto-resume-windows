"""The fakes of the `advturns` traces (seat S7.2e1), the reference's half: `REFERENCE_WORLD` is put before
`advturns.REFERENCE` and defines `World` - how each capability of the scenario is made (the tag's own class, with the
scenario's fakes where the class takes them) and the steps that move a fake. `examples/advturns/world.rs` is the Rust
half, the same rules. Every fake notes each call it is asked in `asked`, in order, as `[fake, call, ...]`.

The seams (`scenario["seams"]`): `turns` {thread: turn | null | "raise"} and `codes` {"thread turn": code | "raise"}
(a turn: turn_id, status, errored, completed_at, final_agent, ordinal, kinds [[kind, count], ...]); `session`
{"open": "raise", "enter": "raise", "answers": {method: [answer | "raise", ...]}}; `unheld`: true | false | "raise".
The steps: ["live", shown | null], ["told", key, capability, end, model_restored], ["stop_request", key],
["retry_settings"], ["flag", "empty_refused", bool], ["seam", name, value] (a seam replaced from here on).
The continuation family's looks (S7.2e1b): `recent` [thread, ...] | "raise"; `between` {thread: n | "raise"}; `plans`
{thread: [status, ...] | null | "raise"}; `goals` {thread: status | null | "raise"}; `own` {thread: bool | "raise"}
(core's reader takes it for a conversation it recovers; default true); `children` {parent: [{thread_id, turn_id, status,
category}, ...] | "raise"}. The view's `thread_enabled` is `scenario["enabled"]` {thread: bool | "raise"}, default true.
"""
from __future__ import annotations

REFERENCE_WORLD = r'''
import importlib
import types

from codex_auto_resume_advanced.codex.turns import TurnsUnavailable


class FakeSession:
    def __init__(self, world):
        self.world = world

    def __enter__(self):
        self.world.note("session", "enter")
        if self.world.seams.get("session", {}).get("enter") == "raise":
            raise RuntimeError("raised")
        return self

    def __exit__(self, *exc):
        self.world.note("session", "exit")
        return False

    def call(self, method, params=None):
        self.world.note("session", method, params)
        answers = self.world.seams.get("session", {}).get("answers", {}).get(method, [None])
        index = self.world.calls.get(method, 0)
        self.world.calls[method] = index + 1
        answer = answers[min(index, len(answers) - 1)]
        if answer == "raise":
            raise RuntimeError("raised")
        return answer


class FakeFollower:
    def __init__(self, world):
        self.world, self.shown, self.ends = world, None, []

    def live(self):
        return None if self.shown is None else dict(self.shown)

    def stop(self, key=None, reason=None):
        self.world.note("follower", "stop", key, str(reason))
        return self.shown is not None and (key is None or self.shown["key"] == key)

    def drain(self, capability):
        taken = [end for end in self.ends if end["capability"] == capability]
        self.ends = [end for end in self.ends if end["capability"] != capability]
        return taken


class FakeTurns:
    def __init__(self, world):
        self.world = world

    def latest(self, thread_id):
        self.world.note("turns", "latest", thread_id)
        found = self.world.seams.get("turns", {}).get(thread_id) if isinstance(thread_id, str) else None
        if found == "raise":
            raise TurnsUnavailable("raised")
        if found is None:
            return None
        return types.SimpleNamespace(turn_id=found["turn_id"], status=found["status"],
                                     errored=found.get("errored", False), completed_at=found.get("completed_at"),
                                     final_agent=found.get("final_agent", False), ordinal=found["ordinal"],
                                     kinds=dict(found.get("kinds", [])), started_at=None)

    def turn_code(self, thread_id, turn_id):
        self.world.note("turns", "turn_code", thread_id, turn_id)
        found = self.world.seams.get("codes", {}).get("%s %s" % (thread_id, turn_id))
        if found == "raise":
            raise TurnsUnavailable("raised")
        return found

    def recent(self, since):
        self.world.note("turns", "recent", since)
        found = self.world.seams.get("recent", [])
        if found == "raise":
            raise TurnsUnavailable("raised")
        return list(found)

    def between(self, thread_id, after, before):
        self.world.note("turns", "between", thread_id, after, before)
        found = self.world.seams.get("between", {}).get(thread_id, 0)
        if found == "raise":
            raise TurnsUnavailable("raised")
        return found

    def plan_statuses(self, thread_id):
        self.world.note("turns", "plan_statuses", thread_id)
        found = self.world.seams.get("plans", {}).get(thread_id)
        if found == "raise":
            raise TurnsUnavailable("raised")
        return None if found is None else list(found)


class FakeGoals:
    def __init__(self, world):
        self.world = world

    def read(self, thread_id):
        self.world.note("goals", "read", thread_id)
        found = self.world.seams.get("goals", {}).get(thread_id)
        if found == "raise":
            raise RuntimeError("raised")
        return None if found is None else types.SimpleNamespace(status=found, goal_id="g", updated_at_ms=0)


class FakeSource:
    def __init__(self, world):
        self.world, self.widened = world, frozenset()

    def latest(self, thread_id):
        self.world.note("source", "latest", thread_id, sorted(str(word) for word in self.widened))
        found = self.world.seams.get("own", {}).get(thread_id, True)
        if found == "raise":
            raise RuntimeError("raised")
        return {"thread_id": thread_id} if found else None


class FakeLineage:
    def __init__(self, world):
        self.world = world

    def children(self, parent):
        self.world.note("lineage", "children", parent)
        found = self.world.seams.get("children", {}).get(parent, [])
        if found == "raise":
            raise RuntimeError("raised")
        return [types.SimpleNamespace(thread_id=child.get("thread_id"), turn_id=child.get("turn_id"),
                                      status=child.get("status"), category=child.get("category"))
                for child in found]


class World:
    """The scenario's fakes, by capability."""

    MODULES = {
        "silent_continuation": "silent", "every_conversation": "everyconversation", "parallel_dispatch": "parallel",
        "other_sessions": "sessions", "once_more_when_unsure": "oncemore", "headless_run": "headless",
        "compact_continue": "compact", "model_fallback": "fallback", "codex_retry_settings": "retries",
        "empty_response": "emptyreply", "keep_going": "keepgoing", "subagent_parent": "subagent",
    }
    LOOKING = {"empty_response": "EmptyResponse", "keep_going": "KeepGoing", "subagent_parent": "SubagentParent"}

    def __init__(self, seams, asked, clock):
        self.seams, self.asked, self.clock = seams, asked, clock
        self.calls = {}
        self.follower = FakeFollower(self)
        self.turns = FakeTurns(self)
        from codex_auto_resume import l10n
        l10n.set_preference("en")

    def note(self, *entry):
        self.asked.append(list(entry))

    def open(self, capability):
        self.note("session", "open", capability)
        if self.seams.get("session", {}).get("open") == "raise":
            raise RuntimeError("raised")
        return FakeSession(self)

    def app(self):
        self.note("app", "running")
        return False

    def unheld(self, thread_id):
        self.note("unheld", thread_id)
        found = self.seams.get("unheld", True)
        if found == "raise":
            raise RuntimeError("raised")
        return found

    def noted(self, cls):
        world = self

        class Noted(cls):
            __slots__ = ()

            def unloaded(self, record):
                found = super().unloaded(record)
                if hasattr(found, "mode") and hasattr(found, "seconds"):
                    world.note("route", found.capability, found.key, float(found.seconds), found.mode)
                return found
        return Noted

    def maker(self, capability):
        def make(paths):
            module = importlib.import_module("codex_auto_resume_advanced.engine." + self.MODULES[capability])
            run = dict(session=self.open, follower=self.follower, app_running=self.app)
            if capability == "headless_run":
                return self.noted(module.HeadlessRunCode)(paths, **run)
            if capability == "compact_continue":
                return self.noted(module.CompactContinue)(paths, turns=self.turns, **run)
            if capability == "model_fallback":
                return self.noted(module.ModelFallback)(paths, turns=self.turns, unheld_now=self.unheld, **run)
            if capability == "codex_retry_settings":
                return module.RetrySettings(paths, session=lambda: self.open(capability), clock=lambda: self.clock[0])
            if capability in self.LOOKING:
                import codex_auto_resume.codex as core_codex
                module.Turns = lambda home: self.turns
                for name, fake in (("Goals", FakeGoals), ("Lineage", FakeLineage)):
                    if hasattr(module, name):
                        setattr(module, name, lambda home, fake=fake: fake(self))
                core_codex.LocalSource = lambda home: FakeSource(self)
                return getattr(module, self.LOOKING[capability])(paths, home="fake-codex-home")
            return module.make(paths)
        return make

    def step(self, op, args, runtime):
        from codex_auto_resume_advanced.codex import headless
        from codex_auto_resume_advanced.vocabulary import RunEnd
        if op == "seam":
            self.seams[args[0]] = args[1]
            return None
        if op == "flag":
            if args[0] == "empty_refused":
                headless.EMPTY_REFUSED = bool(args[1])
            return None
        if op == "live":
            self.follower.shown = args[0]
            return None
        if op == "told":
            self.follower.ends.append({"key": args[0], "capability": args[1], "end": RunEnd(args[2]),
                                       "model_restored": args[3]})
            return None
        if op == "stop_request":
            return runtime.state.run_stop(args[0])
        if op == "owe":
            return runtime.state.run_owed(args[0], args[1], args[2], args[3], started_at=args[4], ends_by=args[5])
        if op == "retry_settings":
            return [list(pair) for pair in headless.retry_settings(self.clock[0])]
        raise SystemExit("unknown op %s" % op)
'''

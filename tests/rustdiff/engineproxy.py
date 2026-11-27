"""CODEX_AR_CORE=rust: the `Engine` the frozen scenario modules build, as car-engine (S4.2, PLAN 4.2 and 4.3).

`shim.install()` puts this class in place of `codex_auto_resume.engine.Engine` as the package loads, so every module that
builds an engine - a test's harness, the watcher's App, Rescan, the Diagnostics check - builds this one. Each engine is
a session of one `car-harness serve` process the whole run shares (rust/crates/car-harness/src/proxy.rs), holding one
car-engine `Engine`; every method call goes there, and everything the engine asks of its world comes back over the same pipe and is answered here
by the objects the test handed in, unchanged: its store, its source, its backend, its clock, its log, its notifier,
its words for this time, jitter's draw (`_random`), `time.localtime` and the environment. So a scenario is the same
test, unedited, deciding on the Rust engine, with every row it reads written by the test's own store.

What the modules read and set of an engine besides its methods (listed from the modules and the product code they
drive - tests/test_*.py and checkup/rescan/runtime): `store`, `source`, `backend`, `clock`, `log`, `notify`, `plug`,
`home_lock`, `engine_state`, `connectivity`, `once_words`, `retiring`, `home_key`, `language`, `options` (a dict the
test may write into), `policy_values` and `managed` (what `apply_policy` adopted), `detection_failed`, `handed_waits`,
`_usage_cache` (set to None: the next look reads usage again) and `_random` (the draw jitter asks). The attributes
are this object's own; `options`, `retiring`, `once_words` and `home_key` are handed to car-engine before each call,
and what car-engine holds of them is read back after it.

Not a test module (no `test_` prefix), and stdlib only at import: the product's modules are imported where used.
"""
from __future__ import annotations

from contextlib import nullcontext
import enum
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import weakref

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = object()


def harness() -> Path:
    named = os.environ.get("CODEX_AR_HARNESS_EXE")
    if named:
        return Path(named)
    target = Path(os.environ["CARGO_TARGET_DIR"]) if os.environ.get("CARGO_TARGET_DIR") else ROOT / "rust" / "target"
    return target / "release" / "car-harness.exe"


def plain(value):
    """A Python value as JSON carries it to car-engine."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((plain(item) for item in value), key=repr)
    if hasattr(value, "value") and isinstance(getattr(value, "value"), (str, int)):     # an Enum
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {name: plain(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, Path):
        return str(value)
    return repr(value)


def _gates(vector):
    return {name: tuple(gate) if isinstance(gate, list) else gate for name, gate in (vector or {}).items()}


class _Pipe:
    """The one `car-harness serve` of this process, started at the first engine; its sessions are the engines.

    One lock, re-entered by the thread that holds it: an answer may call another engine (a backend that ticks a second
    engine while the first one's send waits), whose request then goes out nested and is answered before the first
    one's answer is written. An engine let go is closed at the next request, never from the collector's thread."""

    def __init__(self):
        self.lock, self.process, self.next_session, self.next_id, self.depth = threading.RLock(), None, 0, 0, 0
        self.gone = []

    def start(self):
        if self.process is None or self.process.poll() is not None:
            self.process = subprocess.Popen([str(harness()), "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, cwd=str(ROOT))
        return self.process

    def session(self) -> int:
        with self.lock:
            self.next_session += 1
            return self.next_session

    def write(self, message):
        process = self.start()
        process.stdin.write((json.dumps(message, ensure_ascii=True) + "\n").encode("utf-8"))
        process.stdin.flush()

    def read(self):
        line = self.process.stdout.readline()
        if not line:
            raise _Exited("car-harness ended (exit %s)" % self.process.poll())
        return json.loads(line)

    def let_go(self, session):
        self.gone.append(session)

    def request(self, engine, call, **fields):
        with self.lock:
            self.depth += 1
            try:
                if self.depth == 1 and self.gone:
                    closing, self.gone[:] = list(self.gone), []
                    self.next_id += 1
                    self.write({"id": self.next_id, "call": "proxy.close", "session": 0, "sessions": closing})
                    self.read()
                self.next_id += 1
                self.write(dict(fields, id=self.next_id, call=call, session=engine._session))
                return engine._pump()["reply"].get("value")
            finally:
                self.depth -= 1


PIPE = _Pipe()


class _Exited(RuntimeError):
    """car-harness ended while an engine call was waiting for it."""


class Panic(Exception):
    """Raised by a seam object the test hands in (a store, source or backend method): car-harness panics at that call
    instead of handing car-engine an exception - what a panic in a Rust seam would be. The reference meets the same
    call raising, which is what it catches; a diff holds the two to the same outcome."""


class _HarnessView:
    """The view car-engine handed a plug's hook (P2, P8, P22), read from the Python side: each read is car-engine's own
    view's, by a callback while car-harness waits (the innermost view it holds - at an errand's run, that run's)."""

    def __init__(self, engine):
        object.__setattr__(self, "_engine", engine)

    @property
    def now(self):
        return self._engine._callback(["view", "now", []])

    def __getattr__(self, name):
        from codex_auto_resume.engine.storeview import VIEW_READS
        if name not in VIEW_READS:
            raise AttributeError(name)

        def read(*arguments, **keywords):
            return self._engine._callback(["view", name, plain(list(arguments))])
        return read


class _HarnessGuard:
    """One of core's errand guards, as an errand enters it: `permitted` read by car-engine under the store's lock, the
    guard held while the block runs (car-harness proxyplug.rs `guard_entered`)."""

    def __init__(self, engine):
        self._engine = engine

    def __enter__(self):
        return self._engine._callback(["guard_enter"])

    def __exit__(self, *unused):
        self._engine._callback(["guard_exit"])
        return False


class Engine:
    """car-engine's `Engine`, with the reference's constructor."""

    def __init__(self, store, source, backend, *, dispatch_lock=nullcontext, clock=time.time, log=None,
                 options=None, notify=None, language=None, home_lock=None, engine_state=None, plug=None,
                 connectivity=None, home_key="", open_store=None, once_words=None):
        import random
        from codex_auto_resume.domain.plug import guard
        from codex_auto_resume import managed as admin, settings as policy
        set_ = object.__setattr__
        set_(self, "_guards", [])
        set_(self, "_raised", {})
        set_(self, "_usage_cached", False)
        self.store, self.source, self.backend = store, source, backend
        self.plug = guard(plug)
        self.dispatch_lock, self.clock = dispatch_lock, clock
        self.home_key, self.retiring = home_key, False
        self.open_store = open_store
        self.once_words = once_words
        self.log = log or (lambda *args: None)
        self.notify = notify or (lambda *args: None)
        self.language = language or "en"
        self.policy_values = policy.defaults()
        self.managed = admin.NONE
        self.home_lock = home_lock or (lambda: True)
        self.engine_state = engine_state or (lambda: "verified")
        self.connectivity = connectivity or (lambda: None)
        self._random = random.Random()
        self.detection_failed, self.handed_waits = None, {}
        set_(self, "options", {})
        set_(self, "_session", PIPE.session())
        weakref.finalize(self, PIPE.let_go, self._session)
        given = dict(options or {})
        set_(self, "_plug_objects", {})
        handed = None if self.plug.null else {"edition": str(getattr(self.plug.edition, "value", self.plug.edition)),
                                              "badge": str(self.plug.badge)}
        reply = self._request("proxy.open", options=plain(given), home_key=home_key, language=language,
                              once_words=once_words is not None, plug=handed)
        self._raise_if(reply)
        # car-engine's own defaults with what was given applied, as it holds them; a name it does not know is kept as
        # given (the reference's dict keeps every name).
        self._take_options(given)
        self._mirror(reply.get("state") if isinstance(reply, dict) else None)

    # ------------------------------------------------------------------ the pipe
    def _pump(self):
        """Read car-harness until a reply or a callback's answer, answering every question it asks meanwhile."""
        while True:
            message = PIPE.read()
            if "ask" in message:
                PIPE.write(self._answer(message["ask"], message.get("args") or []))
                continue
            return message

    def _request(self, call, **fields):
        return PIPE.request(self, call, **fields)

    def _callback(self, args):
        PIPE.write({"callback": plain(args)})
        message = self._pump()
        if "raise" in message:
            raise self._exception(message["raise"])
        return message.get("value")

    def _exception(self, name):
        known = self._raised.get(name)
        if known is not None:
            return known
        if name == "StoreError":
            from codex_auto_resume.store import StoreError
            return StoreError("car-engine: StoreError")
        found = getattr(__builtins__ if isinstance(__builtins__, dict) is False else None, name, None) \
            if not isinstance(__builtins__, dict) else __builtins__.get(name)
        if isinstance(found, type) and issubclass(found, BaseException):
            return found("car-engine: %s" % name)
        return RuntimeError("car-engine: %s" % name)

    def _raise_if(self, reply):
        if isinstance(reply, dict) and "raised" in reply:
            raise self._exception(reply["raised"])

    def _sync(self):
        return {"options": plain(self.options), "retiring": bool(self.retiring), "once_words": self.once_words is not None,
                "home_key": self.home_key}

    def _mirror(self, state):
        if not isinstance(state, dict):
            return
        options = state.get("options")
        if isinstance(options, dict):
            self._take_options(options)
        if "policy_values" in state:
            object.__setattr__(self, "policy_values", state["policy_values"])
        if "detection_failed" in state:
            object.__setattr__(self, "detection_failed", state["detection_failed"])
        if "handed_waits" in state:
            object.__setattr__(self, "handed_waits", state["handed_waits"])
        if "usage_cached" in state:
            object.__setattr__(self, "_usage_cached", bool(state["usage_cached"]))

    def _take_options(self, options):
        for name, value in options.items():
            if name == "retry_ladder" and isinstance(value, list):
                value = tuple(value)
            elif name == "recoverable_categories" and isinstance(value, list):
                value = frozenset(value)
            self.options[name] = value

    def _call(self, method, *args):
        with PIPE.lock:
            object.__setattr__(self, "_raised", {})
            reply = self._request("proxy.call", method=method, args=plain(list(args)), sync=self._sync())
            self._mirror(reply.get("state") if isinstance(reply, dict) else None)
            self._raise_if(reply)
            return reply.get("result")

    # ------------------------------------------------------------------ what car-engine asks
    def _answer(self, name, args):
        try:
            found = {"value": plain(self._asked(name, args))}
            if os.environ.get("CODEX_AR_ENGINEPROXY_TRACE"):
                sys.stderr.write("ASK %s %s -> %s\n" % (name, str(args)[:160], str(found)[:200]))
            return found
        except Panic as exc:                # this call panics in car-harness, as a Rust seam's would (D15's boundaries)
            return {"panic": str(exc)}
        except Exception as exc:          # handed to car-engine as its class, and raised again here if it leaves
            self._raised[type(exc).__name__] = exc
            return {"raise": type(exc).__name__}

    def _asked(self, name, args):
        kind, _, method = name.partition(".")
        if kind == "store":
            return self._store_call(method, args)
        if kind == "plug":
            return self._plug_call(method, args)
        if kind == "source":
            return self._source_call(method, args)
        if kind == "backend":
            return self._backend_call(method, args)
        if kind == "once":
            return self._once_call(method, args)
        if name == "clock":
            return self.clock()
        if name == "log":
            thread, event, detail = args
            return self.log(thread, event, tuple(detail) if isinstance(detail, list) else detail)
        if name == "notify":
            return self.notify(*args)
        if name == "home_lock":
            return self.home_lock()
        if name == "engine_state":
            return self.engine_state()
        if name == "connectivity":
            return self.connectivity()
        if name == "draw":
            return self._random.random()
        if name == "environ":
            return os.environ.get(args[0])
        if name == "windows_languages":
            from codex_auto_resume import l10n
            return list(l10n._windows_preferred() or [])
        if name == "local.localtime":
            found = time.localtime(args[0])
            return [found.tm_year, found.tm_mon, found.tm_mday, found.tm_hour, found.tm_min, found.tm_sec,
                    found.tm_wday]
        if name == "local.mktime":
            return time.mktime(tuple(args) + (0, 0, -1))
        raise NotImplementedError(name)

    def _store_call(self, method, args):
        store = self.store
        if method == "update":
            key, changes, at, event, flags = args
            values = dict(changes)
            values.update(at=at, event=event)
            if flags:
                values["flags"] = flags
            return store.update(key, **values)
        if method in ("correlate", "release_withdrawn"):
            *head, keywords = args
            return getattr(store, method)(*head, **keywords)
        if method == "records_in":
            states, home_key = args
            return store.records_in(frozenset(states), home_key=home_key)
        if method in ("record_gates", "record_would_send"):
            key, vector, *rest = args
            return getattr(store, method)(key, _gates(vector), *rest)
        if method == "guard_enter":
            held = store.submission_guard(args[0])
            permitted = held.__enter__()
            self._guards.append(held)
            return permitted
        if method == "record_guard_enter":
            record, now = args
            held = store.record_guard(record, self.plug, now)
            permitted = held.__enter__()
            self._guards.append(held)
            return permitted
        if method == "reserve_record":
            record, now, quiet_until = args
            return store.reserve_record(record, now, ledger=self.plug, quiet_until=quiet_until)
        if method == "guard_exit":
            return self._guards.pop().__exit__(None, None, None)
        if method == "reserve_detailed":
            from codex_auto_resume.domain.plug import Point
            key, now, keywords = args
            keywords = dict(keywords, gates=_gates(keywords["gates"]), ledger=self.plug,
                            carried=frozenset(Point(word) for word in keywords["carried"]),
                            caps=tuple(keywords["caps"]),
                            resend=tuple(keywords["resend"]) if keywords["resend"] is not None else None)
            return store.reserve_detailed(key, now, **keywords)
        if method == "release_claim":
            key, target, reason, now, next_retry_at = args
            return store.release_claim(key, target, reason, now, next_retry_at=next_retry_at)
        if method == "register":
            detection, now, keywords = args
            return store.register(detection, now, **keywords)
        if method in ("hold_changed", "hold_waiting"):
            return getattr(store, method)(*args, actor="engine")
        if method == "usage_checked":
            key, now, read, source = args
            return store.usage_checked(key, now, read, source=source)
        return getattr(store, method)(*args)

    # ------------------------------------------------------------------ the plug the test handed (car-harness proxyplug.rs)
    def _plug_call(self, method, args):
        """A hook of the test's own plug, as car-policy's `Guarded` in car-engine asks it: the plug's own method, its
        answer said as car-harness reads it. What it answers with that core runs later is kept here by number."""
        from codex_auto_resume.domain.plug import BACKEND, Edition, Point, Surface
        if method == "object":
            number, name, arguments = args
            return self._plug_object(self._plug_objects[number], name, arguments)
        raw = self.plug.plug
        if method in ("records", "tick", "resident"):
            args = [_HarnessView(self)]
        elif method == "sender":
            args = [args[0], BACKEND]
        elif method == "wants":
            args = [Point(args[0])]
        elif method == "surface":
            args = [Surface(args[0]), args[1]]
        elif method == "edition_changed":
            args = [Edition(args[0])]
        return self._plug_said(getattr(raw, method)(*args))

    def _plug_said(self, answer):
        from codex_auto_resume.domain.plug import BACKEND, DEFER, Alternative
        if answer is DEFER or answer is BACKEND:
            return {"defer": True}
        if isinstance(answer, Alternative):
            return {"word": answer.value}
        if answer is None or isinstance(answer, (bool, int, float, str, dict, list, tuple, set, frozenset, enum.Enum)):
            return {"value": plain(answer)}
        number = len(self._plug_objects) + 1
        self._plug_objects[number] = answer
        return {"object": number, "has": [name for name in ("run", "send", "pools", "resume", "takes_words", "start")
                                          if getattr(answer, name, None) is not None]}

    def _plug_object(self, found, name, arguments):
        if name == "run":
            return {"value": plain(found.run(lambda: _HarnessGuard(self)))}
        if name == "send":
            thread_id, prompt, client_id = arguments
            sent = found.send(thread_id, prompt) if client_id is None else found.send(thread_id, prompt,
                                                                                    client_id=client_id)
            return {"value": plain(sent)}
        if name == "resume":
            thread_id, still, words, client_id = arguments
            handed = {} if words is None else {"words": words, "client_id": client_id}
            unloaded = (lambda: bool(self._callback(["still_unloaded"]))) if still else None
            return {"value": plain(found.resume(thread_id, launch_guard=nullcontext(True), still_unloaded=unloaded,
                                                **handed))}
        if name == "takes_words":
            taken = getattr(found, "takes_words")
            return {"value": plain(taken() if callable(taken) else taken)}
        if name == "start":
            return {"value": plain(found.start(arguments[0]))}
        return {"value": plain(getattr(found, name)(*arguments))}

    def _source_call(self, method, args):
        source = self.source
        if method == "latest_failures":
            since, needs_you, admissible, shapes = args
            extra = {"admissible": True, "shapes": True} if admissible else {}
            if needs_you:
                return source.latest_failures(since, needs_you=frozenset(needs_you), **extra)
            return source.latest_failures(since, **extra)
        if method == "passed_over":
            since, before, known = args
            return source.passed_over(since, before, known=frozenset(known))
        if method == "task_facts":
            thread, fingerprint, tokens = args
            keywords = {}
            if fingerprint:
                keywords["fingerprint"] = True
            if tokens:
                keywords["tokens"] = True
            return source.task_facts(thread, **keywords)
        if method == "activity":
            threads, now, booted = args
            return source.activity(tuple(threads), now, booted=booted)
        if method in ("newer_than_engine", "taken"):
            thread, kinds, rest = args
            rest = frozenset(rest) if method == "taken" else rest
            return getattr(source, method)(thread, frozenset(kinds), rest)
        if method == "set_kinds":
            kinds, widened = args
            source.session_kinds = frozenset(kinds)
            source.widened = frozenset(widened)
            return None
        return getattr(source, method)(*args)

    def _backend_call(self, method, args):
        backend = self.backend
        if method == "getattr":
            return getattr(backend, args[0], None)
        if method == "send":
            thread, prompt, key = args
            guard = self.store.submission_guard(key) if key is not None else None
            return backend.send(thread, prompt, launch_guard=guard)
        if method == "holder":
            holder = getattr(backend, "holder", None)
            return [False, None] if holder is None else [True, holder(args[0])]
        return getattr(backend, method)(*args)

    def _once_call(self, method, args):
        words = self.once_words
        if method == "prune":
            return words.prune(lambda key: bool(self._callback([key])))
        return getattr(words, method)(*args)

    # ------------------------------------------------------------------ the attributes kept as the reference's
    WATCHER_OPTIONS = {"delivery_timeout_seconds": 300}

    @property
    def _usage_cache(self):
        return True if self._usage_cached else None

    @_usage_cache.setter
    def _usage_cache(self, value):
        if value is None:
            self._call("clear_usage_cache")

    # ------------------------------------------------------------------ the engine's methods
    def tick(self):
        return self._call("tick")

    def watch(self):
        return self._call("watch")

    def watch_needed(self):
        return self._call("watch_needed")

    def observe_all(self):
        return self._call("observe_all")

    def observe_projections(self):
        return self._call("observe_projections")

    def collect(self):
        return self._call("collect")

    def attempt(self, row):
        return self._call("attempt", row)

    def observe(self, row):
        return self._call("observe", row)

    def apply_policy(self, values, managed=None) -> None:
        from codex_auto_resume import managed as admin
        held = managed if isinstance(managed, admin.Managed) else None
        self._call("apply_policy", values, held)
        self.managed = held if held is not None else admin.NONE

    def after_sleep(self, since, slept):
        return self._call("after_sleep", since, slept)

    def activity(self, threads=()):
        return self._call("activity", list(threads))

    def last_usage(self):
        found = self._call("last_usage")
        return None if found is None else (found[0], found[1])

    def limits(self):
        return self._call("limits")

    def capacity_limits(self):
        return self._call("capacity_limits")

    def recovers(self, category):
        return self._call("recovers", category)

    def presend_problem(self, claim, forced=False):
        found = self._call("presend_problem", claim, forced)
        return None if found is None else tuple(found)

    def detection_since(self, settings):
        return self._call("detection_since", settings)

    def not_taken_up(self, record):
        found = self._call("not_taken_up", record)
        return None if found is None else tuple(found)

    def valid_interruption(self, row):
        return self._call("valid_interruption", row)

    def proof(self, row):
        return self._call("proof", row)

    def persons_turns(self, thread, turns):
        return self._call("persons_turns", thread, list(turns))

    def foreign(self, row, turn):
        return self._call("foreign", row, turn)

    def fresh_throughout(self, thread_id, since):
        return self._call("fresh_throughout", thread_id, since)

    def tier(self, thread_id):
        return self._call("tier", thread_id)

    def allowed(self, row):
        return self._call("allowed", row)

    def observing(self, settings):
        return self._call("observing", settings)

    def quiet_until(self, now):
        return self._call("quiet_until", now)

    def delay_for(self, attempt):
        return self._call("delay_for", attempt)

    def first_delay(self, category):
        return self._call("first_delay", category)

    def caps(self, relaxed=None):
        return tuple(self._call("caps", relaxed))

    def close(self):
        PIPE.let_go(self._session)


Engine.rust_core = "car-engine"


def install(module) -> None:
    """Put the proxy in place of `codex_auto_resume.engine.Engine` (the package just loaded)."""
    from codex_auto_resume.engine import options as reference_options
    Engine.WATCHER_OPTIONS = reference_options.WATCHER_OPTIONS
    if getattr(module, "Engine", None) is not Engine:
        Engine.__wrapped__ = getattr(module, "Engine", None)
        module.Engine = Engine

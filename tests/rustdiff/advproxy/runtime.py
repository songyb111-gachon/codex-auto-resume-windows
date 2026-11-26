"""The forwarders of S7.2a3 (owner Q3 (c)): `runtime.Runtime`, its `state` and `arming`, and `state.AdvancedState`, as
car-adv's over the pipe (pipe.py). A test builds them with the reference's own constructors and reads them with the
reference's own names; what they decide is car-adv's, and everything car-adv asks of the test's world - the clock,
the policy, the view and the measurements handed in, a capability's `make` and its code's hooks, the objects those
hooks answer with, core's view, and `Arming`'s edges into modules not ported yet - is answered by the test's own
objects, unchanged (`Runtime.answer`).

Not ported here, so not forwarded (each named in table.py): `Runtime.claim` (P11 runs on core's own SQLite connection,
in core's process; car-store's claim is held by diffs_engine_records), `run_measurement` and `complete_measurement`
(S7.4), a `state.scoped(...)` made by a test itself with lambdas of its own.
"""
from __future__ import annotations

import enum
import inspect
import time

from .pipe import PIPE, plain

# runtime._own: the optional hooks a code has only where its class defines them.
OPTIONAL = ("bind", "rule_for", "taken", "carries", "not_taken", "holds", "watched_due", "words_sent",
            "acted_when_told", "tend", "images_of")
# What an object a hook answered with can be asked (ProxyThing in advserve).
OBJECT_METHODS = ("send", "resume", "run", "start", "pools", "words")
_DEFAULT = object()


def _own(code, name):
    if inspect.getattr_static(code, name, None) is None:
        return None
    found = getattr(code, name, None)
    return found if callable(found) else None


def dump_def(item, shipped: bool) -> dict:
    """A capability definition as advprobe's `defs::from_json` reads it (advdiff.dump_def's shape), and whether its
    `make` is the shipped package's (car-adv's own table makes it) or a test's (asked back)."""
    return {"id": item.id, "kind": str(item.kind), "points": sorted(str(point) for point in item.points),
            "revision": item.revision, "departs_from": list(item.departs_from), "compat": item.compat,
            "ceilings": None if item.ceilings is None else [item.ceilings.per_day, item.ceilings.per_conversation],
            "journal_prefix": item.journal_prefix, "codes": list(item.codes),
            "measurements": [str(each) for each in item.measurements],
            "options": [{"key": str(each.key), "choices": list(each.choices), "default": each.default,
                         "custom": None if each.custom is None else list(each.custom)} for each in item.options],
            "rules_editor": item.rules_editor, "samples": item.samples, "resends": item.resends,
            "requires": list(item.requires), "wordings": [str(each) for each in item.wordings],
            "narrowed_by": [str(each) for each in item.narrowed_by], "sends": item.sends,
            "make": "shipped" if shipped else "python"}


def _shipped(make) -> bool:
    module = getattr(make, "__module__", "") or ""
    return module.startswith("codex_auto_resume_advanced.")


def definitions(registry) -> list:
    return [dump_def(each, _shipped(each.make)) for each in registry]


class _Session:
    """What every forwarder shares: its session, the raises it re-raises, the questions it answers."""

    _session = None

    def raised(self, reply):
        """car-adv's raise as the reference's own class: the state's (StateError, StaleGeneration, Refused,
        SteerRefused), a registry's, a built-in's by name; a panic as RuntimeError."""
        from codex_auto_resume_advanced import state as package
        from codex_auto_resume_advanced.state import steers
        from codex_auto_resume_advanced import registry
        name, message, word = reply.get("raised"), reply.get("message") or "", reply.get("word")
        if name == "Refused":
            return package.Refused(word)
        if name == "SteerRefused":
            return steers.SteerRefused(word)
        if name in ("StateError", "StaleGeneration"):
            return getattr(package, name)(message)
        if name == "RegistryError":
            return registry.RegistryError(message)
        made = __builtins__.get(name) if isinstance(__builtins__, dict) else getattr(__builtins__, name, None)
        if isinstance(made, type) and issubclass(made, BaseException):
            return made(message) if message else made()
        return RuntimeError("%s: %s" % (name, message))


# ------------------------------------------------------------------ the state

# The reference's answer shapes the JSON loses: a method whose answer is a tuple, or a set.
TUPLES = {"move", "move_set", "all_off", "add_rule"}
# A state method's name as car-adv's `StatePort` calls it, where the two differ (runtime/faults.rs).
FAULT_NAMES = {"move": "move_to"}


def _scoped_names(state, capability):
    """What a `Scoped` of `capability` offers: the reference's own names for it (its reads are closures, made but
    never called here), and nothing else - a view writes nothing."""
    from codex_auto_resume_advanced.state import Scoped
    made = Scoped(state, capability)
    return set(made._reads) | {name for name in dir(Scoped) if not name.startswith("_")}
SETS = set()


class StateProxy(_Session):
    """`AdvancedState` as car-adv's (`state::calls`): every public method by its name. `paths`, `registry`,
    `directory`, `path` and `clock` are the constructor's, as the reference keeps them."""

    def __init__(self, owner, paths, registry, clock):
        self._owner = owner
        self.paths, self.registry, self.clock = paths, registry, clock
        from codex_auto_resume_advanced.state.schema import FILE_NAME
        from pathlib import Path
        self.directory = Path(paths.advanced_dir)
        self.path = self.directory / FILE_NAME

    @property
    def _session(self):
        return self._owner._session

    def raised(self, reply):
        return self._owner.raised(reply)

    def _call(self, name, *arguments, **keywords):
        found = PIPE.request(self._session, "state", method=name, args=plain(list(arguments)),
                             kwargs=plain(keywords))
        return _shaped(name, found)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*arguments, **keywords):
            import sqlite3
            if arguments and isinstance(arguments[0], sqlite3.Connection):
                # A fixture writer on the test's own connection (`record_spend(connection, "main", ...)`): the
                # reference's method, on that connection - the test's arrangement, not the subject.
                reference = _reference_state()
                if isinstance(inspect.getattr_static(reference, name, None), staticmethod):
                    return getattr(reference, name)(*arguments, **keywords)
                return getattr(reference, name)(self, *arguments, **keywords)
            return self._call(name, *arguments, **keywords)
        return call

    # `patch.object(runtime.state, "arming", side_effect=StateError(...))`: the mock is this object's own, for the
    # test's own calls, and car-adv's runtime is told the method raises (its `faults`) until the patch ends.
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if not name.startswith("_") and self._owner_runtime() is not None:
            effect = getattr(value, "side_effect", None)
            raises = isinstance(effect, BaseException) or (isinstance(effect, type)
                                                           and issubclass(effect, BaseException))
            self._owner._call("fault", FAULT_NAMES.get(name, name), raises)

    def __delattr__(self, name):
        object.__delattr__(self, name)
        if not name.startswith("_") and self._owner_runtime() is not None:
            self._owner._call("fault", FAULT_NAMES.get(name, name), False)

    def _owner_runtime(self):
        owner = self.__dict__.get("_owner")
        return owner if isinstance(owner, Runtime) and owner.__dict__.get("_session") is not None else None

    def scoped(self, capability, on=None, verdict=None, armed=None):
        """`Scoped(self, capability, on, verdict, armed)`: car-adv's, its callables asked back by its number."""
        return MadeScoped(self, capability, on, verdict, armed)

    # A test that writes or reads the file itself (`_transaction`, `_read`) gets a connection of its own to the file
    # car-adv keeps, with the reference's transaction rule (state/session.py `_begin`); a static helper the reference
    # runs on that connection (`_prune`, `_prune_spend`) is the reference's own, named in table.py as not forwarded.
    def _connect(self, create):
        import sqlite3
        if create:
            self._call("meta")                     # car-adv makes the file and its schema, as `_open(create=True)`
        if not self.path.is_file():
            return None
        connection = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _transaction(self, *, create=True):
        return self._begun(create, "BEGIN IMMEDIATE")

    def _read(self):
        return self._begun(False, "BEGIN")

    def _begun(self, create, statement):
        from contextlib import contextmanager
        import sqlite3
        from codex_auto_resume_advanced.state import StateError

        @contextmanager
        def begun():
            connection = self._connect(create)
            if connection is None:
                yield None
                return
            try:
                connection.execute(statement)
                yield connection
                connection.execute("COMMIT")
            except BaseException as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                if isinstance(exc, sqlite3.Error):
                    raise StateError("advanced state transaction failed") from exc
                raise
            finally:
                connection.close()
        return begun()

    @staticmethod
    def _prune(connection, now):
        from codex_auto_resume_advanced.state.journal import JournalMixin
        return JournalMixin._prune(connection, now)

    @staticmethod
    def _prune_spend(*arguments, **keywords):
        from codex_auto_resume_advanced.state.journal import JournalMixin
        return JournalMixin._prune_spend(*arguments, **keywords)


def _scoped_answer(owner, line):
    made = owner.__dict__.get("_scopes", {})[line["scoped"]]
    return made.asked(line["name"], line["arg"]) if "arg" in line else made.asked(line["name"])


def _hashable(key):
    """A key JSON carried as a list is the reference's tuple (`(bucket, minutes)`)."""
    return tuple(_hashable(each) for each in key) if isinstance(key, list) else key


def _unpairs(value):
    if isinstance(value, dict):
        if set(value) == {"__pairs__"}:
            return {_hashable(_unpairs(key)): _unpairs(item) for key, item in value["__pairs__"]}
        return {key: _unpairs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unpairs(item) for item in value]
    return value


def _reference_state():
    """The reference's own `AdvancedState` class (table.py keeps it as the forwarder's `__advproxy_reference__`)."""
    found = getattr(AdvancedState, "__advproxy_reference__", None)
    if found is None:
        from codex_auto_resume_advanced.state.session import SessionMixin
        from codex_auto_resume_advanced.state.spend import SpendMixin
        return type("Reference", (SpendMixin, SessionMixin), {})
    return found


def _arming_rows(rows):
    from codex_auto_resume_advanced.vocabulary import ArmingState, ArmingWarning
    if not isinstance(rows, dict):
        return rows
    return {capability: dict(row, state=ArmingState(row["state"]),
                             warnings=tuple(ArmingWarning(each) for each in row.get("warnings") or ()))
            if isinstance(row, dict) else row for capability, row in rows.items()}


STATE_SHAPES = {"arming": _arming_rows}


def _shaped(name, found):
    found = _unpairs(found)
    if name in STATE_SHAPES:
        return STATE_SHAPES[name](found)
    if name in TUPLES and isinstance(found, list):
        return tuple(found)
    if name in SETS and isinstance(found, list):
        return frozenset(found)
    return found


PRIVATE = ("_transaction", "_read", "_prune", "_prune_spend")


class _ReferenceClass(type):
    """A class attribute the forwarder lacks is the reference class's (`AdvancedState._tables(connection)`, a static
    helper a test runs on a connection of its own)."""

    def __getattr__(cls, name):
        reference = cls.__dict__.get("__advproxy_reference__")
        if reference is None or name.startswith("__"):
            raise AttributeError(name)
        return getattr(reference, name)


class AdvancedState(_Session, metaclass=_ReferenceClass):
    """`state.AdvancedState(paths, registry=REGISTRY, clock=time.time)`, a session of its own in advserve."""

    def __init__(self, paths, *, registry=_DEFAULT, clock=time.time, **options):
        if registry is _DEFAULT:
            from codex_auto_resume_advanced.registry import REGISTRY
            registry = REGISTRY
        self._proxy = StateProxy(self, paths, registry, clock)
        self._session = PIPE.session(self)
        PIPE.request(self._session, "open", kind="state", home=str(paths.home), definitions=definitions(registry))

    def answer(self, line):
        if line.get("ask") == "source" and line.get("name") == "clock":
            return {"value": self._proxy.clock()}
        if line.get("ask") == "scoped":
            return _scoped_answer(self, line)
        raise LookupError(line.get("ask"))

    def __getattr__(self, name):
        if name.startswith("_") and name not in PRIVATE:
            raise AttributeError(name)
        return getattr(self._proxy, name)


# ------------------------------------------------------------------ arming

class ArmingProxy:
    """`Arming` as car-adv's: every method by its name, the answers given back their Python shapes."""

    def __init__(self, runtime):
        self._runtime = runtime
        self.state = runtime.state
        self.registry = runtime.registry
        self.clock = runtime.clock
        self.catalogs = runtime._arming_options.get("catalogs")
        self.secrets = None

    def _call(self, name, *arguments, **keywords):
        return PIPE.request(self._runtime._session, "arming", method=name, args=[_arg(each) for each in arguments],
                            kwargs={key: _arg(each) for key, each in keywords.items()})

    # What a test reads or replaces of the reference's Arming by its private name: the sources handed in, kept by
    # the runtime and asked by car-adv at each use (`_policy` and the rest), so a replacement takes effect at once.
    SOURCES = {"_policy": "policy", "_view": "view", "_measured": "measured", "_live": "live"}

    def __setattr__(self, name, value):
        if name == "catalogs" and "_runtime" in self.__dict__ and value is not None:
            self._runtime._catalogs.fill(value)
        if name in ArmingProxy.SOURCES:
            self._runtime._arming_options[ArmingProxy.SOURCES[name]] = value
            return
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        if name in ArmingProxy.SOURCES:
            return self._runtime._arming_options.get(ArmingProxy.SOURCES[name])
        if name.startswith("_"):
            raise AttributeError(name)
        shape = ARMING_SHAPES.get(name, lambda found: found)
        return lambda *arguments, **keywords: shape(self._call(name, *arguments, **keywords))


def _arg(value):
    from codex_auto_resume_advanced.registry import CapabilityDef
    if isinstance(value, CapabilityDef):
        return dump_def(value, _shipped(value.make))
    if hasattr(value, "forbid") and hasattr(value, "force_shadow"):
        return {"forbid": value.forbid, "force_shadow": value.force_shadow,
                "allowed": None if value.allowed is None else sorted(value.allowed)}
    if isinstance(value, dict) and value and all(isinstance(key, enum.Enum) for key in value) \
            and all(isinstance(each, tuple) for each in value.values()):
        return [[plain(key), *plain(list(each))] for key, each in value.items()]   # a measurement table
    return plain(value)


def _states(pairs):
    from codex_auto_resume_advanced.vocabulary import ArmingState
    return {capability: ArmingState(state) for capability, state in pairs}


def _measured(rows):
    from codex_auto_resume_advanced.vocabulary import Measurement, Verdict
    return {Measurement(m): (Verdict(v), e) for m, v, e in rows}


def _checked(rows):
    from codex_auto_resume_advanced.vocabulary import AutoResult, Measurement
    return {Measurement(m): AutoResult(r) for m, r in rows}


def _policy(found):
    from codex_auto_resume_advanced import policy
    return policy.Policy(forbid=found["forbid"], force_shadow=found["force_shadow"],
                         allowed=None if found["allowed"] is None else frozenset(found["allowed"]))


def _warnings(found):
    from codex_auto_resume_advanced.vocabulary import ArmingWarning
    return tuple(ArmingWarning(each) for each in found)


def _read(found):
    states, since, failed = found
    return _states(states), {capability: at for capability, at in since}, failed


ARMING_SHAPES = {"current": _states, "read": _read, "measured": _measured, "checked": _checked, "policy": _policy,
                 "warnings": _warnings, "why": lambda pairs: {capability: word for capability, word in pairs}}


# ------------------------------------------------------------------ the runtime

class _Catalogs:
    """The catalogs car-adv reads: a folder of this runtime's own holding a copy of the handed-in catalogs' files, so
    `runtime.arming.catalogs = other` (a test's) takes effect as it does on the reference's Arming - before car-adv
    has read a language (it keeps what it read, as the reference's Catalogs keeps its own cache)."""

    def __init__(self, catalogs):
        import shutil
        import tempfile
        import weakref
        self.folder = tempfile.mkdtemp(prefix="car-advproxy-catalogs-")
        weakref.finalize(self, shutil.rmtree, self.folder, True)
        self.fill(catalogs)

    def fill(self, catalogs):
        import shutil
        from pathlib import Path
        self.catalogs = catalogs
        for old in Path(self.folder).glob("*"):
            if old.is_file():
                old.unlink()
        for each in Path(catalogs.directory).glob("*.json"):
            shutil.copyfile(each, Path(self.folder) / each.name)


class _RustThing:
    """An object car-adv made and handed the test (the errands of a tick, a channel of its own): asked by number."""

    def __init__(self, runtime, number, kind, view=None):
        self._runtime, self._number, self.kind, self._view = runtime, number, kind, view

    def _ask(self, method, *arguments):
        return PIPE.request(self._runtime._session, "object", object=self._number, method=method,
                            args=plain(list(arguments)), view=self._view)

    def run(self, guard):
        self._runtime._guard = guard
        return self._ask("run")

    def send(self, thread_id, prompt, client_id=None):
        return self._ask("send", thread_id, prompt, client_id)

    def resume(self, thread_id, *arguments, words=None, client_id=None, **keywords):
        return self._ask("resume", thread_id, words, client_id)

    def start(self, command):
        return self._ask("start", list(command))


class Runtime(_Session):
    """car-adv's `Runtime`, with the reference's constructor and names."""

    def __init__(self, paths, *, registry=_DEFAULT, clock=time.time, measure_session_factory=None,
                 measure_launcher=None, measure_backend=None, measure_cli=None, measure_ipc=None, measure_hands=None,
                 evidence_dir=None, **arming):
        from codex_auto_resume_advanced import statement
        if registry is _DEFAULT:
            from codex_auto_resume_advanced.registry import REGISTRY
            registry = REGISTRY
        self.paths, self.registry, self.clock = paths, registry, clock
        self._arming_options = arming
        self._measure = dict(session_factory=measure_session_factory, launcher=measure_launcher,
                             backend=measure_backend, cli=measure_cli, ipc=measure_ipc, hands=measure_hands,
                             evidence_dir=evidence_dir)
        self._code, self._made_raised, self._objects, self._views = {}, {}, {}, {}
        self._backend, self._guard = None, None
        self.state = StateProxy(self, paths, registry, clock)
        catalogs = arming.get("catalogs") or statement.CATALOGS
        self._catalogs = _Catalogs(catalogs)
        self._session = PIPE.session(self)
        PIPE.request(self._session, "open", kind="runtime", home=str(paths.home), definitions=definitions(registry),
                     catalogs=str(self._catalogs.folder), view=arming.get("view") is not None,
                     measured=arming.get("measured") is not None, live=arming.get("live") is not None)
        self.arming = ArmingProxy(self)
        from codex_auto_resume_advanced.ledger import ClaimLedger
        self.ledger = ClaimLedger(self.state)

    # -------------------------------------------------------------- calls
    def _call(self, method, *arguments, view=None, **keywords):
        return PIPE.request(self._session, "runtime", method=method, args=[plain(each) for each in arguments],
                            kwargs=plain(keywords), view=view)

    def _view_id(self, view):
        number = len(self._views) + 1
        self._views[number] = view
        return number

    def _said(self, reply, view=None):
        from codex_auto_resume.domain.plug import DEFER, Alternative
        if reply is None:
            return None
        if "defer" in reply:
            return DEFER
        if "backend" in reply:
            return self._backend
        if "word" in reply:
            return Alternative(reply["word"])
        if "tuple" in reply:
            return tuple(reply["tuple"])
        if "set" in reply:
            return frozenset(reply["set"])
        if "object" in reply:
            return self._objects[reply["object"]]
        if "rust" in reply:
            return _RustThing(self, reply["rust"], reply["kind"], view)
        return reply.get("value")

    def states(self, *, fresh=False, live=()) -> dict:
        return _states(self._call("states", fresh=fresh, live=list(live)))

    def wants(self, point) -> bool:
        return self._call("wants", point)

    def ask(self, point, *arguments):
        from codex_auto_resume.domain.plug import Point
        encoded = [plain(each) for each in arguments]
        if point == Point.SENDER and len(arguments) > 1:
            self._backend = arguments[1]
            encoded[1] = {"__backend__": True}
        return self._said(PIPE.request(self._session, "runtime", method="ask", args=[plain(point)] + encoded,
                                       kwargs={}, view=None))

    def start_route(self, request):
        return self._said(self._call("start_route", request))

    def start_held(self):
        return self._call("start_held")

    def supervise(self, facts):
        return self._said(self._call("supervise", facts))

    def supervise_held(self):
        return self._call("supervise_held")

    def tick(self, view):
        number = self._view_id(view)
        return self._said(self._call("tick", view=number), number)

    def resident(self, view):
        number = self._view_id(view)
        return self._said(self._call("resident", view=number), number)

    def records(self, view):
        return self._said(self._call("records", view=self._view_id(view)))

    def partition(self, records):
        return self._said(self._call("partition", records))

    def moved(self, record, state):
        return self._said(self._call("moved", record, state))

    def sessions(self):
        from codex_auto_resume.domain.plug import SessionKind
        found = self._said(self._call("sessions"))
        return found if not isinstance(found, list) else frozenset(SessionKind(each) for each in found)

    def eligibility(self):
        from codex_auto_resume.domain.plug import Widening
        found = self._said(self._call("eligibility"))
        return found if not isinstance(found, list) else frozenset(Widening(each) for each in found)

    def conversation_off(self, thread_id) -> None:
        self._call("conversation_off", thread_id)

    def _code_of(self, definition):
        if definition.id not in self._code:
            try:
                self._call("make", definition.id)
            except BaseException:
                made = self._made_raised.pop(definition.id, None)
                if made is not None:
                    raise made
                raise
        return self._code[definition.id]

    def action(self, definition):
        if definition.id not in self._code:
            self._call("action", definition.id)
        return self._code[definition.id]

    def claim(self, connection, record, now, carried):
        raise NotImplementedError("advproxy: P11 runs on core's own connection, in core's process (table.py)")

    def run_measurement(self, measurement, thread=None, may_spend=False):
        raise NotImplementedError("advproxy: run_measurement is S7.4's (table.py)")

    def complete_measurement(self, measurement, verdict, note):
        raise NotImplementedError("advproxy: complete_measurement is S7.4's (table.py)")

    # -------------------------------------------------------------- what car-adv asks back
    def answer(self, line):
        kind = line.get("ask")
        if kind == "scoped":
            return _scoped_answer(self, line)
        if kind == "hook":
            return self._hook(line["capability"], line["hook"], line.get("args") or [])
        if kind == "source":
            return {"value": self._source(line["name"])}
        if kind == "make":
            return self._make(line["capability"])
        if kind == "object":
            return self._object(line["object"], line["method"], line.get("args") or [])
        if kind == "view":
            return self._view(line["view"], line["method"], line.get("args") or [])
        if kind == "edge":
            return {"value": plain(EDGES[line["name"]](self, *(line.get("args") or [])))}
        if kind == "log":
            import logging
            from codex_auto_resume.logbook import LOGGER_NAME
            logging.getLogger(LOGGER_NAME).info(line["line"])
            return None
        raise LookupError(kind)

    def _source(self, name):
        options = self._arming_options
        if name == "clock":
            return self.clock()
        if name == "language":
            from codex_auto_resume import l10n
            return l10n.current()
        if name == "policy":
            from codex_auto_resume_advanced import policy
            found = (options.get("policy") or policy.read)()
            return _arg(found)
        if name in ("view", "live"):
            return plain(options[name]())
        if name == "measured":
            found = options["measured"]()
            return _arg(found) if isinstance(found, dict) and found else ([] if isinstance(found, dict) else None)
        raise LookupError(name)

    def _make(self, capability):
        definition = self.registry.get(capability)
        try:
            code = definition.make(self.paths)
        except BaseException as error:
            self._made_raised[capability] = error
            raise
        if code is None:
            return None
        self._code[capability] = code
        return {"own": [name for name in OPTIONAL if _own(code, name) is not None]}

    def _decoded(self, value):
        if isinstance(value, dict):
            if set(value) == {"__view__"}:
                return self._views.get(value["__view__"])
            if set(value) == {"__scoped__"}:
                return ScopedProxy(self, value["__scoped__"])
            if set(value) == {"__told__"}:
                number = value["__told__"]
                return lambda: PIPE.request(self._session, "told", told=number)
            if set(value) == {"__backend__"}:
                return self._backend
        return value

    def _hook(self, capability, hook, arguments):
        from codex_auto_resume.domain.plug import Point
        code = self._code[capability]
        arguments = [self._decoded(each) for each in arguments]
        if hook == "taken" and arguments:
            arguments[0] = Point(arguments[0])
        if hook == "sender":
            arguments.append(self._backend)
        answer = getattr(code, hook)(*arguments)
        return self._encode(answer)

    def _encode(self, answer):
        from codex_auto_resume.domain.plug import DEFER, Alternative
        if answer is DEFER:
            return {"defer": True}
        if self._backend is not None and answer is self._backend:
            return {"backend": True}
        if isinstance(answer, Alternative):
            return {"word": answer.value}
        if isinstance(answer, tuple):
            return {"tuple": plain(list(answer))}
        if isinstance(answer, (set, frozenset)):
            return {"set": plain(answer)}
        if answer is None or isinstance(answer, (bool, int, float, str, dict, list, enum.Enum)):
            return {"value": plain(answer)}
        number = len(self._objects) + 1
        self._objects[number] = answer
        return {"object": number, "has": [name for name in OBJECT_METHODS if getattr(answer, name, None) is not None]}

    def _object(self, number, method, arguments):
        found = self._objects[number]
        if method == "run":
            return self._encode(found.run(self._guard))
        if method == "pools":
            return self._encode(found.pools())
        if method == "words":
            return self._encode(getattr(found, "words"))
        if method == "send":
            thread_id, prompt, client_id = (list(arguments) + [None, None, None])[:3]
            return self._encode(found.send(thread_id, prompt, client_id=client_id) if client_id is not None
                                else found.send(thread_id, prompt))
        if method == "resume":
            thread_id, words, client_id = (list(arguments) + [None, None, None])[:3]
            keywords = {key: each for key, each in (("words", words), ("client_id", client_id)) if each is not None}
            return self._encode(found.resume(thread_id, **keywords))
        if method == "start":
            return self._encode(found.start(*arguments))
        raise AttributeError(method)

    def _view(self, number, method, arguments):
        found = getattr(self._views[number], method)
        found = found(*arguments) if callable(found) else found
        return {"value": plain(found)}


class MadeScoped:
    """A `Scoped` a test made itself (`state.scoped(...)`), as car-adv's: every call by its name, `on`, `verdict` and
    `armed` answered here (pipe `scoped` questions, through the owner's `answer`)."""

    def __init__(self, state, capability, on, verdict, armed):
        self._state, self.capability = state, capability
        self._callables = {"on": on, "verdict": verdict, "armed": armed}
        owner = state._owner
        scopes = owner.__dict__.setdefault("_scopes", {})
        self._number = len(scopes) + 1
        scopes[self._number] = self

    def __getattr__(self, name):
        if name.startswith("_") or name not in _scoped_names(self._state, self.capability):
            raise AttributeError(name)

        def call(*arguments, **keywords):
            found = PIPE.request(self._state._session, "made_scoped", scoped=self._number,
                                 capability=self.capability, method=name, args=plain(list(arguments)),
                                 kwargs=plain(keywords),
                                 **{key: value is not None for key, value in self._callables.items()})
            return _shaped(name, found)
        return call

    def asked(self, name, arg=_DEFAULT):
        found = self._callables[name]
        return {"value": plain(found() if arg is _DEFAULT else found(arg))}


class ScopedProxy:
    """A code's own `state.Scoped`, as car-adv's (`state::calls::scoped_call`), through the binding it was made with."""

    def __init__(self, runtime, capability):
        self._runtime, self.capability = runtime, capability

    def __getattr__(self, name):
        if name.startswith("_") or name not in _scoped_names(self._runtime.state, self.capability):
            raise AttributeError(name)

        def call(*arguments, **keywords):
            found = PIPE.request(self._runtime._session, "scoped", capability=self.capability, method=name,
                                 args=plain(list(arguments)), kwargs=plain(keywords))
            return _shaped(name, found)
        return call


# ------------------------------------------------------------------ Arming's edges not ported yet (table.py names each)

def _edge_hook_follow(runtime, armed):
    from codex_auto_resume_advanced.codex import inuse
    from codex_auto_resume_advanced.control import hookplugin
    hookplugin.follow(runtime.paths, inuse.home(runtime.paths), armed)


def _edge_power(runtime, armed):
    from codex_auto_resume_advanced.control import powertasks
    powertasks.follow(runtime.paths, armed)


def _edge_forget(runtime):
    from codex_auto_resume_advanced.engine import account
    account.forget(runtime.state, runtime.arming.secrets)


def _edge_touched(runtime, key):
    from codex_auto_resume_advanced.engine import usage
    from codex_auto_resume_advanced.vocabulary import OptionKey
    return list(usage.touched(OptionKey(key)))


def _edge_order(runtime, values, windows):
    from codex_auto_resume_advanced.engine import usage
    from codex_auto_resume_advanced.vocabulary import OptionKey
    values = {capability: {OptionKey(key): value for key, value in options.items()}
              for capability, options in values.items()}
    return list(usage.order_problem(values, windows))


def _edge_previews(runtime, now):
    from codex_auto_resume_advanced.engine import usage
    return [[window, words] for window, words in usage.previews(runtime.state, now).items()]


def _edge_wording(runtime, words):
    from codex_auto_resume_advanced.engine import wrapwords
    try:
        wrapwords.check_custom(words)
    except wrapwords.WordingError as error:
        return error.code
    return None


def _edge_table(runtime, engine):
    from codex_auto_resume_advanced import compatdata
    return _arg(compatdata.table_for(runtime.paths, engine))


def _edge_checked(runtime, engine):
    from codex_auto_resume_advanced import autocheck
    return [[plain(m), plain(r)] for m, r in autocheck.results_for(runtime.paths, engine).items()]


def _edge_auto_check(runtime):
    from codex_auto_resume_advanced import autocheck
    try:
        autocheck.tend(runtime.paths, clock=runtime.clock)
    except Exception:
        pass


def _edge_view(runtime):
    from codex_auto_resume_advanced import arming
    return arming._view_of(runtime.paths)


def _edge_live(runtime):
    from codex_auto_resume_advanced import arming
    return arming._live_view_of(runtime.paths)


def _edge_limit(runtime):
    from codex_auto_resume_advanced.engine import wrapwords
    return wrapwords.continuation.MAX_CUSTOM_LENGTH


def _edge_placeholders(runtime):
    from codex_auto_resume_advanced.engine import wrapwords
    return list(wrapwords.PLACEHOLDERS)


EDGES = {"hook_follow": _edge_hook_follow, "power_tasks_follow": _edge_power, "account_forget": _edge_forget,
         "usage_touched": _edge_touched, "usage_order_problem": _edge_order, "usage_previews": _edge_previews,
         "wording_problem": _edge_wording, "table_for": _edge_table, "checked_for": _edge_checked,
         "auto_check": _edge_auto_check, "default_view": _edge_view, "default_live_view": _edge_live,
         "wording_limit": _edge_limit, "wording_placeholders": _edge_placeholders}

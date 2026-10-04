"""The closed vocabularies: every word the product stores, sends, translates or branches on.

A record's state, a public code, a reason, a gate, a failure category, an error code, a
setting's choice, a registry state - each is a string from a closed list, and each list is
also a contract: the store validates against it, the window and the panel look words up by it,
the catalogs carry a sentence for each member, and the Rust core of v0.6.14 has to write the same
strings. v0.6.5 gives every list one home, `domain/vocabulary.py`, as an `enum.StrEnum`, and
keeps each old constant under its old name so that every `x in STATES` still works.

What this file pins is that none of that changed a word. Each list is held here, as it was
before the move, to its kind, its length and a digest of its members (sorted for a set, in
order for a tuple, item by item for a mapping), so a member added, dropped, renamed or
reordered anywhere fails here whichever module the list lives in. A list that changes on
purpose has its line here changed in the same commit.

Some vocabularies are not a list anywhere: they are the words a function hands back - what
the queue says of a send, what a watcher start or stop came to. Those are read from the
functions themselves, wherever they are.

And every enum is held to the code that spells its words (HOMES), and every member to what
makes a `StrEnum` safe to put where a plain string was (StrEnumTests): it hashes and compares
as its value, and JSON, the database and "%s" write it as its value.
"""
from __future__ import annotations

import ast
from enum import StrEnum
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402
from codex_auto_resume.domain import compat_vocabulary as c, plug as p, vocabulary as v  # noqa: E402
from codex_auto_resume.domain import power_vocabulary as pw  # noqa: E402

# "module.NAME" -> (kind, length, digest), or the text of a single word.
LISTS = {
    "machine.STATES": ("set", 27, "5cac947c5c3bb648"),
    "machine.WAITING": ("set", 7, "a824ab68db703524"),
    "machine.CLAIMED": ("set", 1, "feec3b8e36dd2ced"),
    "machine.IN_FLIGHT": ("set", 2, "334f92d34c55d3d4"),
    "machine.OBSERVING": ("set", 2, "62b3313d1c2197ba"),
    "machine.OUTCOMES": ("set", 6, "a7becd43513098c2"),
    "machine.EXHAUSTED": ("set", 2, "41378c015f091134"),
    "machine.TERMINAL": ("set", 15, "1cb278defda2b160"),
    "machine.V2_STATES": ("set", 18, "afdae6b420db41b5"),
    "machine.POSSIBLY_SENT": ("set", 20, "dadead4aea3c20e5"),
    "machine.WATCHED": ("set", 4, "07ba1375946c1591"),
    # v0.6.11: observe_only and observe_only_unknown - taken back for Observe only, in its own words.
    "machine.WITHDRAW_REASONS": ("set", 13, "e0093ee6641742ac"),
    "machine.SUPERSEDE_WITHDRAWALS": ("set", 3, "b63141bdc33260f0"),
    "machine.TURN_STATUSES": ("set", 5, "58aca83cec78ff2b"),
    "machine.ACTORS": ("set", 5, "eaf35d06c4c2b568"),
    # v0.6.11: offline - Windows reports no internet, so usage is not read (power.py, off by default).
    # and observe_only, observe_only_unknown: a withdrawal's reasons are reasons too.
    # v0.6.13: not_recoverable (a gate reason until then) and admission_expired - a failure the plug
    # took up (P17) that nothing takes up now, and one taken up a day ago.
    "machine.REASONS": ("set", 69, "120fe1a7f071af97"),
    # v0.6.11: postponed, held, hold_released and tier_set - a person's (or the objection window's)
    # later time, a hold, letting it go, and a conversation's tier - and observe only's would_send.
    # And dispatched_while_observing and unpostponed: one taken back for Observe only that ran all the
    # same, and a person's own postponement taken away.
    "machine.EVENT_CODES": ("set", 28, "338d004c0e77ba46"),
    "machine.WAITING_CODES": ("set", 5, "aef153e5808afe46"),
    "machine.PUBLIC_CODES": ("set", 22, "33761768f9d99cd0"),
    "machine.PAGES": ("tuple", 6, "ffad1c9f0521398d"),
    # v0.6.11: `held`, a record that waits for a person (schema 4's hold).
    "machine.OVERLAYS": ("tuple", 8, "275fd01184c6c4e3"),
    "machine.GATE_RESULTS": ("set", 4, "9a50f41ff116a706"),
    "machine.GATES": ("tuple", 13, "547089c399324718"),
    # v0.6.11: `held`, a gate core passed and the edition's plug held (domain/plug.py, HOLD);
    # and schema 4's `postponed`, `quiet_hours` and `observe_only`, reasons of consent and schedule;
    # and `offline`, the usage gate's while Windows reports no internet (power.py).
    # v0.6.11 stage 3b: `plugged`, thread_available passed for a route the plug named (P16).
    # v0.6.13: admission_expired, a reason now (not_recoverable was a gate reason already).
    "machine.GATE_REASONS": ("set", 84, "e9c8c91279989dd7"),
    "machine.PASS": "PASS",
    "machine.WAIT": "WAIT",
    "machine.BLOCK": "BLOCK",
    "machine.UNKNOWN": "UNKNOWN",
    "machine.NOT_CHECKED": "not_checked",
    "machine.HELD": "held",
    "machine.PLUGGED": "plugged",
    "machine.POSTPONED": "postponed",
    "machine.QUIET_HOURS": "quiet_hours",
    "machine.OBSERVE_ONLY": "observe_only",
    # v0.6.11, schema 4: a record's hold, and a conversation's tier, least asking first.
    "machine.HOLDS": ("set", 6, "46f978e63d3c05c3"),
    "machine.IMPORTANCE_TIERS": ("tuple", 4, "1020c428556c4555"),
    "failures.CATEGORIES": ("set", 14, "05e7b8e16f528bde"),
    # v0.6.10: auth_service_transient, which nothing produces, left TRANSIENT for RESERVED.
    "failures.TRANSIENT": ("set", 5, "7c4f1306a8dcfc48"),
    "failures.RESERVED": ("set", 1, "4adafa358990cf26"),
    "failures.TERMINAL": ("set", 6, "7e746dc3d4241dd2"),
    "failures.USAGE_LIMIT": "usage_limit",
    "failures.UNKNOWN": "unknown",
    "store.ENGINE_STATES": ("set", 6, "a40ef34f9adea697"),
    "codex.KNOWN_STATUSES": ("set", 4, "23d2734c27812d29"),
    "logbook.STATE_CODES": ("set", 27, "5cac947c5c3bb648"),
    # v0.6.11: a postponement's three refusals, a record that is not held, a tier that is none, and
    # a project that cannot be read or one too many; and what an administrator's policy key decides.
    # v0.6.11: not_postponed and too_many_messages - Don't postpone, and one conversation's message.
    # v0.6.12: power_unavailable - an action Windows will not do for this account on this PC.
    "control.ERROR_CODES": ("set", 34, "d4859a691c1a1d4f"),
    "control.FALLBACK_CODE": "request_failed",
    # v0.6.11: v0.6.10's four again - v0.6.11-beta's careful was folded into detailed.
    "continuation.STYLES": ("tuple", 4, "a390c91bf5107f3f"),
    "continuation.CUSTOM_MODES": ("tuple", 2, "a4a918de1aaec837"),
    "continuation.DEFAULT_STYLE": "standard",
    "continuation.DEFAULT_CUSTOM_MODE": "global",
    "settings.THEMES": ("tuple", 3, "bde3c29151568c16"),
    # v0.6.11: and the needs-you notice, the one event off by default.
    "settings.NOTIFICATION_EVENTS": ("tuple", 5, "b702d9979f24798b"),
    "settings.RETRY_TIMING": ("dict", 3, "8a8e62ec299a7928"),
    "settings.DEFAULT_TIMING": "normal",
    "settings.THEME_SYSTEM": "system",
    "settings.DEFAULT_THEME": "system",
    # v0.6.11: the nine new languages, less the two held until they mirror (l10n.HELD).
    "settings.CONTINUATION_LANGUAGES": ("tuple", 17, "f644e75d1d333a60"),
    # v0.6.11: the days quiet hours start on, and the tiers a conversation may have by default.
    "settings.QUIET_DAYS": ("tuple", 3, "b7883f3f9fa3397d"),
    "settings.TIERS": ("tuple", 4, "1020c428556c4555"),
    # v0.6.11: what a conversation first seen gets, and which projects may resume without a person.
    "settings.NEW_CONVERSATION_POLICIES": ("tuple", 2, "472d79c55b2067ec"),
    "settings.PROJECT_POLICIES": ("tuple", 3, "db754fee43e7f8d8"),
    "projects.POLICIES": ("tuple", 3, "db754fee43e7f8d8"),
    # v0.6.11: nine more catalogs after pt-BR - ru, it, tr, pl, uk, vi, id, ar, he - of which ar and he
    # are held: registered and complete, never offered or reached, until every surface mirrors.
    "l10n.LOCALES": ("tuple", 18, "edc6caaef8734aff"),
    "l10n.OFFERED": ("tuple", 16, "42b9ab738414dc8b"),
    "l10n.HELD": ("set", 2, "2332329b5394bfec"),
    "l10n.CHOICES": ("tuple", 17, "f4e304d71a4b6670"),
    "l10n.SYSTEM": "system",
    "l10n.DEFAULT": "en",
    "compat.STATES": ("tuple", 6, "17f36047142c2622"),
    "compat.RESULTS": ("tuple", 4, "734fbec0fd7cd8f0"),
    "compat.TIERS": ("tuple", 4, "c97af83c55d98a0e"),
    "compat.COARSE": ("dict", 6, "516c60fa0957de72"),
    "compat.ENGINE_STATES": ("tuple", 6, "36426170c5b3e61b"),
    "compat.CHECKS": ("tuple", 13, "4f60ac9722005257"),
    "compat.CAPABILITIES": ("dict", 16, "2ccc411f04f2d0eb"),
    "compat.SEND_GATE": ("tuple", 2, "9f067781e177f778"),
    "compat.RESOLUTION_REASONS": ("set", 8, "d1dc0426f2a468e1"),
    "compat.VIEW_REASONS": ("set", 4, "9045e2f225c7f918"),
    "compat.REASONS": ("set", 12, "b2bfabba4abedce6"),
    "compat.REGISTRY_REASONS": ("set", 8, "636a07a2cfd0f395"),
    "compat.SOURCES": ("tuple", 3, "fcc67bee7807d4f6"),
    "compat.BUNDLED_STATES": ("tuple", 3, "e20d4920785e4c46"),
    "compat.CACHE_STATES": ("tuple", 7, "b7014857f6846fe7"),
    "compat.RESTRICTING_STATES": ("tuple", 3, "5e2634d654b72fc6"),
    "compat.TRUSTING_STATES": ("tuple", 1, "a0f8264885403e66"),
    "compat.DATA_SOURCES": ("tuple", 3, "a3ac64703823133c"),
    "compat.VIEW_STATUSES": ("tuple", 5, "be7f4d53d1bdaeef"),
    "compat.CACHE_ORIGINS": ("tuple", 2, "59bbca123a0129bb"),
    "compat.IMPORT_REASONS": ("set", 18, "5e96319d7f426e99"),
    "compat.PERMIT_REASONS": ("set", 7, "c91623c654ca27fc"),
    "compat.VERIFIED": "VERIFIED",
    "compat.COMPATIBLE": "COMPATIBLE",
    "compat.INCOMPATIBLE": "INCOMPATIBLE",
    "compat.UNKNOWN": "UNKNOWN",
    "compat.PASS": "PASS",
    "compat.FAIL": "FAIL",
    "compat.UNAVAILABLE": "UNAVAILABLE",
    "compat.NOT_APPLICABLE": "NOT_APPLICABLE",
    "compatio.REFRESH_ANSWERS": ("tuple", 5, "4cda52986c543d8a"),
    "compatio.REFRESH_EXIT": ("dict", 3, "bd6b85c278fb7567"),
    "windows.PASS": "PASS",
    "windows.FAIL": "FAIL",
    "windows.UNAVAILABLE": "UNAVAILABLE",
    "ui.tray.ICON_STATES": ("tuple", 5, "e94d5138669400b3"),
    "ui.popup.STATES": ("tuple", 6, "b38c816dbd792bf5"),
    "ui.popup.ATTENTION_OVERLAYS": ("set", 4, "a707a2b300127033"),
    # v0.6.11: and the needs-you notice's light, attention; and a long sleep's, paused (power.py).
    # and Show me what happens' card, waiting.
    "notifier.NOTICE_STATUS": ("dict", 12, "ccfbc4aee6adaf58"),
    # v0.6.12: the power action's five notices follow them, in a table of their own (PowerNotice), and the
    # whole table is both.
    "notifier.POWER_STATUS": ("dict", 5, "d403490eeafa7732"),
    "notifier.POWER_EVENTS": ("tuple", 5, "e5a05bae37eb8e45"),
    "notifier.STATUS": ("dict", 17, "2ec8a9e6e4566ab5"),
    "mcpserver.Server.START_WORDING": ("dict", 4, "f15e04a780f57870"),
    # v0.6.11: the two editions, and the plug that is the whole difference between them.
    "edition.EDITIONS": ("tuple", 2, "49cc206af3867704"),
    "edition.PLUG_FAILURES": ("tuple", 4, "4414d548d1f8f251"),
    # P14 joined the twelve: core tells the plug of each move of a record as it writes it. P15 too:
    # how a continuation is carried and proven, where CLIENT_ID - no marker - joined HOLD. And P16:
    # what continues a conversation the app does not hold, a route core carries out (stage 3b).
    # v0.6.13: P17, a failure core never recovers alone taken up, and ADMIT and the five AS_ words
    # that take one up, at P17 and at known_failure; and the form a failure's error took.
    "domain.plug.POINTS": ("tuple", 16, "07e8ae14d7f49978"),
    "domain.plug.ANSWERS": ("set", 8, "451124ce82b474fa"),
    "domain.plug.FAILURE_FORMS": ("tuple", 5, "bcc0ad1bd6f81009"),
    "domain.plug.SURFACES": ("tuple", 5, "d41ac5a6d67be21b"),
    "domain.plug.EXTRA": "advanced",
}

# The words a function hands back: (qualified name, the key of the dict it returns - or None
# for the value itself, or the first of a tuple) -> every word, found in its source.
RETURNED = {
    ("Backend.send", "outcome"): {"accepted", "not_started", "unknown"},
    ("Backend.send", "error_code"): {"queue_preflight_failed", "queue_consent_refused", "queue_spawn_failed",
                                     "queue_response_unconfirmed", "queue_timeout", "queue_result_unknown"},
    ("Backend.loaded", None): {"loaded", "notLoaded", "unknown"},
    ("WatcherMixin.start_watcher", "state"): {"already-running"},
    ("await_watcher", "state"): {"running", "exited", "unconfirmed"},
    ("WatcherMixin.stop_watcher", "state"): {"not-running"},
    ("await_stopped", "state"): {"stopped", "still-finishing", "unknown"},
}


def value_of(name):
    """The value `codex_auto_resume.<name>` names, however deep the module part goes.

    The longest importable prefix is imported and the rest is read off it. Taking only the
    first segment would work by accident for a module inside a package: `ui.popup.STATES`
    would import `codex_auto_resume.ui` and find `popup` on it only because some earlier test
    in the same process had imported it and Python had set the attribute on the parent. The
    whole suite would pass and this file alone would fail.
    """
    parts = name.split(".")
    value, taken = None, 0
    for count in range(len(parts), 0, -1):
        try:
            value = importlib.import_module("codex_auto_resume." + ".".join(parts[:count]))
        except ImportError:
            continue
        taken = count
        break
    if value is None:
        raise ImportError("no module of codex_auto_resume is named in %r" % name)
    for part in parts[taken:]:
        value = getattr(value, part)
    return value


def shape(value):
    """(kind, the members in the order that matters) for a list, or None for a single word."""
    if isinstance(value, (set, frozenset)):
        return "set", sorted(value)
    if isinstance(value, dict):
        return "dict", list(value.items())
    if isinstance(value, tuple):
        return "tuple", list(value)
    return None


def digest(members) -> str:
    return hashlib.sha256(json.dumps(members).encode("utf-8")).hexdigest()[:16]


def _strings(node, assigned):
    """The strings an expression can be: a constant, either branch of a conditional, or a name
    the function assigns only such things to."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _strings(node.body, assigned) | _strings(node.orelse, assigned)
    if isinstance(node, ast.Name):
        return assigned.get(node.id, set())
    return set()


def returned_words(qualname, key):
    """Every word the function `qualname` returns - under `key` in a dict it returns, or, when
    `key` is None, as the value itself or the first element of a tuple - wherever in the
    package the function is defined. Exactly one definition must answer to the name."""
    found, words = [], set()
    for path, tree in srcscan.package_asts().items():
        names = srcscan.qualnames(tree)
        for function in ast.walk(tree):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) and names[function] == qualname:
                found.append(srcscan.relative(path))
                assigned = {}
                for node in ast.walk(function):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                assigned.setdefault(target.id, set()).update(_strings(node.value, {}))
                for node in ast.walk(function):
                    if not isinstance(node, ast.Return) or node.value is None:
                        continue
                    if key is None:
                        value = node.value.elts[0] if isinstance(node.value, ast.Tuple) else node.value
                        words |= _strings(value, assigned)
                        continue
                    for mapping in ast.walk(node.value):
                        if isinstance(mapping, ast.Dict):
                            words |= {word for name, value in zip(mapping.keys, mapping.values)
                                      if isinstance(name, ast.Constant) and name.value == key
                                      for word in _strings(value, assigned)}
    if len(found) != 1:
        raise AssertionError("%s is defined %d times: %s" % (qualname, len(found), found))
    return words


# Each vocabulary, and where the code spells its words today: a list (a tuple in its order, a
# set as a set), the keys of a table (in their order), or the words functions return.
HOMES = {
    v.RecordState: ("list", "machine.STATES"),
    v.PublicCode: ("list", "machine.PUBLIC_CODES"),
    v.WithdrawReason: ("list", "machine.WITHDRAW_REASONS"),
    v.ReasonCode: ("list", "machine.REASONS"),
    v.EventCode: ("list", "machine.EVENT_CODES"),
    v.Actor: ("list", "machine.ACTORS"),
    v.TurnStatus: ("list", "machine.TURN_STATUSES"),
    v.Page: ("list", "machine.PAGES"),
    v.Overlay: ("list", "machine.OVERLAYS"),
    v.HoldKind: ("list", "machine.HOLDS"),
    v.ImportanceTier: ("list", "machine.IMPORTANCE_TIERS", "settings.TIERS"),
    v.GateName: ("list", "machine.GATES"),
    v.GateResult: ("list", "machine.GATE_RESULTS"),
    v.FailureCategory: ("list", "failures.CATEGORIES"),
    v.EngineState: ("list", "store.ENGINE_STATES", "compat.ENGINE_STATES"),
    v.WatcherStartState: ("returned", ("WatcherMixin.start_watcher", "state"), ("await_watcher", "state")),
    v.WatcherStopState: ("returned", ("WatcherMixin.stop_watcher", "state"), ("await_stopped", "state")),
    v.ErrorCode: ("list", "control.ERROR_CODES"),
    v.ContinuationStyle: ("list", "continuation.STYLES"),
    v.CustomMode: ("list", "continuation.CUSTOM_MODES"),
    v.Theme: ("list", "settings.THEMES"),
    v.Design: ("list", "settings.DESIGNS", "brand.DESIGNS"),
    # v0.6.11: the presets, the keys of settings.RETRY_TIMING, and Custom after them.
    v.RetryTiming: ("list", "settings.RETRY_TIMINGS", "ladder.TIMINGS"),
    v.RetryWait: ("list", "ladder.WAITS"),
    v.ChainCeiling: ("list", "ladder.CEILINGS", "settings.CHAIN_CEILINGS"),
    v.TaskGuard: ("list", "guards.TASK_GUARDS", "settings.TASK_GUARDS"),
    v.ContextGuard: ("list", "guards.CONTEXT_GUARDS", "settings.CONTEXT_GUARDS"),
    v.QuietDays: ("list", "settings.QUIET_DAYS"),
    v.NewConversationPolicy: ("list", "settings.NEW_CONVERSATION_POLICIES"),
    v.ProjectPolicy: ("list", "settings.PROJECT_POLICIES", "projects.POLICIES"),
    v.NotifyEvent: ("list", "settings.NOTIFICATION_EVENTS"),
    # v0.6.11: how long a turn may not move before a needs-you notice says so.
    v.StallWait: ("list", "needsyou.STALL_WAITS"),
    # v0.6.11: keeping this PC awake while a task waits, for how long, and after how long a sleep to ask.
    v.KeepAwake: ("list", "power.KEEP_AWAKE_MODES", "settings.KEEP_AWAKE_MODES"),
    v.AwakeCap: ("list", "power.AWAKE_CAPS", "settings.AWAKE_CAPS"),
    v.SleepWait: ("list", "power.SLEEP_WAITS", "settings.SLEEP_WAITS"),
    # v0.6.11: the watcher's memory guard and its limit, and how the watcher last ended.
    v.MemoryGuard: ("list", "memguard.MODES", "settings.MEMORY_GUARD_MODES"),
    v.MemoryLimit: ("list", "memguard.LIMITS", "settings.MEMORY_LIMITS"),
    v.WatcherEnd: ("list", "store.WATCHER_ENDS"),
    # v0.6.11: who may open the state folder, as Diagnostics is told it.
    v.StateAccess: ("list", "win.acl.STATE_ACCESS"),
    v.Locale: ("list", "l10n.LOCALES"),
    v.SendOutcome: ("returned", ("Backend.send", "outcome")),
    v.SendError: ("returned", ("Backend.send", "error_code")),
    v.LoadedState: ("returned", ("Backend.loaded", None)),
    v.ActivityState: ("list", "ui.popup.STATES"),
    v.IconState: ("list", "ui.tray.ICON_STATES"),
    v.NoticeKind: ("keys", "notifier.NOTICE_STATUS"),
    v.CompatState: ("list", "compat.STATES"),
    v.LocalResult: ("list", "compat.RESULTS"),
    v.Tier: ("list", "compat.TIERS"),
    v.CompatCheck: ("list", "compat.CHECKS"),
    v.Capability: ("keys", "compat.CAPABILITIES"),
    v.ResolutionReason: ("list", "compat.RESOLUTION_REASONS"),
    v.ViewReason: ("list", "compat.VIEW_REASONS"),
    v.RegistryReason: ("list", "compat.REGISTRY_REASONS"),
    v.ImportReason: ("list", "compat.IMPORT_REASONS"),
    v.PermitReason: ("list", "compat.PERMIT_REASONS"),
    v.CompatSource: ("list", "compat.SOURCES"),
    v.BundledState: ("list", "compat.BUNDLED_STATES"),
    v.CacheState: ("list", "compat.CACHE_STATES"),
    v.DataSource: ("list", "compat.DATA_SOURCES"),
    v.ViewStatus: ("list", "compat.VIEW_STATUSES"),
    v.CacheOrigin: ("list", "compat.CACHE_ORIGINS"),
    v.RefreshAnswer: ("list", "compatio.REFRESH_ANSWERS"),
    v.ReportedState: ("list", "compat.reported.STATES"),
    # v0.6.11: the plug interface's own words, which live beside it in domain/plug.py.
    p.Edition: ("list", "edition.EDITIONS"),
    p.PlugFailure: ("list", "edition.PLUG_FAILURES"),
    p.Point: ("list", "domain.plug.POINTS"),
    p.Alternative: ("list", "domain.plug.ANSWERS"),
    p.Surface: ("list", "domain.plug.SURFACES"),
    p.FailureForm: ("list", "domain.plug.FAILURE_FORMS"),
    # v0.6.12: the power action's own words, beside domain/vocabulary.py at its line budget.
    pw.PowerAction: ("list", "poweraction.ACTIONS"),
    pw.PowerAfter: ("list", "poweraction.AFTERS"),
    pw.PowerRepeat: ("list", "poweraction.REPEATS"),
    pw.PowerPhase: ("list", "poweraction.PHASES"),
    pw.PowerWait: ("list", "poweraction.WAITS"),
    pw.PowerEnd: ("list", "poweraction.ENDS"),
    pw.PowerClass: ("list", "poweraction.CLASSES"),
    pw.PowerUnavailable: ("list", "poweraction.UNAVAILABLE"),
    pw.PowerNotice: ("keys", "notifier.POWER_STATUS"),
}


def enums():
    """Every vocabulary the four modules define: `domain/vocabulary.py`; `domain/compat_vocabulary.py`,
    the registry's, out of it since v0.6.11 and named through it still; `domain/plug.py`, whose six
    are the plug interface's own; and `domain/power_vocabulary.py`, the power action's (v0.6.12). Each
    is held to every rule here all the same."""
    return [value for module in (v, c, p, pw) for value in vars(module).values()
            if inspect.isclass(value) and issubclass(value, StrEnum) and value is not StrEnum
            and value.__module__ == module.__name__]


def members():
    for cls in enums():
        for member in cls:
            yield cls, member


class ListTests(unittest.TestCase):
    def test_every_list_has_the_members_it_had(self):
        for name, expected in LISTS.items():
            with self.subTest(name):
                value = value_of(name)
                found = shape(value)
                if found is None:
                    self.assertIsInstance(expected, str, "a list became a single word")
                    self.assertEqual(value, expected)
                    continue
                kind, members = found
                self.assertEqual((kind, len(value), digest(members)), expected,
                                 "its members are now %s" % json.dumps(members))

    def test_every_returned_vocabulary_has_the_words_it_had(self):
        for (qualname, key), expected in RETURNED.items():
            with self.subTest(qualname=qualname, key=key):
                self.assertEqual(returned_words(qualname, key), expected)

    def test_the_reader_of_returned_words_sees_each_way_one_is_spelled(self):
        source = ("def f(x):\n"
                  "    state = 'a' if x else 'b'\n"
                  "    if x > 1:\n"
                  "        return {'state': state, 'other': 'z'}\n"
                  "    if x > 2:\n"
                  "        return {'state': 'c'}\n"
                  "    if x > 3:\n"
                  "        return 'd', True\n"
                  "    return 'e'\n")
        tree = ast.parse(source)
        with mock.patch.object(srcscan, "package_asts", return_value={Path("f.py"): tree}), \
                mock.patch.object(srcscan, "relative", return_value="f.py"):
            self.assertEqual(returned_words("f", "state"), {"a", "b", "c"})
            self.assertEqual(returned_words("f", None), {"d", "e"})


class HomeTests(unittest.TestCase):
    def test_every_vocabulary_has_a_home(self):
        self.assertEqual(sorted(cls.__name__ for cls in enums()), sorted(cls.__name__ for cls in HOMES))

    def test_every_vocabulary_is_exactly_the_words_its_home_spells(self):
        for cls, (kind, *homes) in HOMES.items():
            with self.subTest(cls.__name__):
                if kind == "returned":
                    words = set()
                    for qualname, key in homes:
                        words |= returned_words(qualname, key)
                    self.assertEqual(words, set(cls))
                    continue
                for home in homes:
                    value = value_of(home)
                    if kind == "keys":
                        self.assertEqual(list(value), list(cls), home)
                    elif isinstance(value, tuple):
                        self.assertEqual(value, tuple(cls), home)
                    else:
                        self.assertEqual(value, frozenset(cls), home)

    def test_the_words_spelled_beside_a_vocabulary_are_its_members(self):
        from codex_auto_resume import (brand,
                                       compat,
                                       continuation,
                                       control,
                                       failures,
                                       l10n,
                                       machine,
                                       mcpserver,
                                       notifier,
                                       codex,
                                       settings,
                                       windows)
        from codex_auto_resume.ui import popup as tray_popup
        self.assertLessEqual(set(v.WithdrawReason), set(v.ReasonCode))
        # Every kind of notice is a word of one of the two lists, the power action's after the others (v0.6.12).
        self.assertEqual(list(notifier.STATUS), list(v.NoticeKind) + list(pw.PowerNotice))
        self.assertEqual(notifier.POWER_EVENTS, tuple(pw.PowerNotice))
        self.assertEqual(list(compat.COARSE.values()), list(v.EngineState))
        self.assertEqual(list(mcpserver.Server.START_WORDING), ["running", "already-running", "exited", "unconfirmed"])
        self.assertEqual(set(mcpserver.Server.START_WORDING), set(v.WatcherStartState))
        self.assertLessEqual(tray_popup.ATTENTION_OVERLAYS, set(v.Overlay))
        self.assertEqual(codex.KNOWN_STATUSES, set(v.TurnStatus) - {v.TurnStatus.OTHER})
        # A picker offers every language but the held ones, in the vocabulary's order.
        self.assertLessEqual(l10n.HELD, set(v.Locale))
        offered = tuple(locale for locale in v.Locale if locale not in l10n.HELD)
        self.assertEqual(l10n.OFFERED, offered)
        self.assertEqual(l10n.CHOICES, (l10n.SYSTEM,) + offered)
        self.assertEqual(settings.CONTINUATION_LANGUAGES, (settings.FOLLOW_INTERFACE,) + offered)
        for word, cls in ((machine.PASS, v.GateResult), (machine.WAIT, v.GateResult), (machine.BLOCK, v.GateResult),
                          (machine.UNKNOWN, v.GateResult), (failures.USAGE_LIMIT, v.FailureCategory),
                          (failures.UNKNOWN, v.FailureCategory), (control.FALLBACK_CODE, v.ErrorCode),
                          (continuation.DEFAULT_STYLE, v.ContinuationStyle),
                          (continuation.DEFAULT_CUSTOM_MODE, v.CustomMode), (settings.DEFAULT_THEME, v.Theme),
                          (settings.DEFAULT_DESIGN, v.Design), (brand.DEFAULT_DESIGN, v.Design),
                          (settings.DEFAULT_TIMING, v.RetryTiming), (l10n.DEFAULT, v.Locale),
                          (compat.VERIFIED, v.CompatState), (compat.COMPATIBLE, v.CompatState),
                          (compat.INCOMPATIBLE, v.CompatState), (compat.UNKNOWN, v.CompatState),
                          (compat.PASS, v.LocalResult), (compat.FAIL, v.LocalResult),
                          (compat.UNAVAILABLE, v.LocalResult), (compat.NOT_APPLICABLE, v.LocalResult),
                          (windows.PASS, v.LocalResult), (windows.FAIL, v.LocalResult),
                          (windows.UNAVAILABLE, v.LocalResult)):
            with self.subTest(word=word):
                self.assertIn(word, frozenset(cls))
        for subset in (machine.WAITING, machine.CLAIMED, machine.IN_FLIGHT, machine.OBSERVING, machine.OUTCOMES,
                       machine.EXHAUSTED, machine.TERMINAL, machine.V2_STATES, machine.POSSIBLY_SENT,
                       machine.WATCHED):
            self.assertLessEqual(subset, frozenset(v.RecordState))
        self.assertLessEqual(machine.WAITING_CODES, frozenset(v.PublicCode))
        self.assertLessEqual(machine.SUPERSEDE_WITHDRAWALS, frozenset(v.WithdrawReason))
        self.assertLessEqual(set(compat.SEND_GATE), set(v.Capability))
        self.assertLessEqual(set(compat.RESTRICTING_STATES) | set(compat.TRUSTING_STATES), set(v.CacheState))
        self.assertEqual(set(compat.REASONS), set(v.ResolutionReason) | set(v.ViewReason))
        self.assertLessEqual({tier for _checks, tier in compat.CAPABILITIES.values()}, set(v.Tier))
        self.assertLessEqual({check for checks, _tier in compat.CAPABILITIES.values() for check in checks},
                             set(v.CompatCheck))

    def test_every_state_and_every_category_is_in_exactly_one_group(self):
        """machine.STATES and failures.CATEGORIES are the whole vocabulary; the groups the rest of
        the product decides by must still cover it, each member once."""
        from codex_auto_resume import failures, machine
        groups = (machine.WAITING, machine.CLAIMED, machine.IN_FLIGHT, machine.OBSERVING, machine.TERMINAL)
        self.assertEqual(sorted(state for group in groups for state in group), sorted(machine.STATES))
        groups = (failures.TRANSIENT, failures.TERMINAL, failures.RESERVED, {failures.USAGE_LIMIT, failures.UNKNOWN})
        self.assertEqual(sorted(category for group in groups for category in group), sorted(failures.CATEGORIES))

    def test_a_members_name_is_its_value_in_capitals(self):
        for cls, member in members():
            with self.subTest(vocabulary=cls.__name__, member=member.value):
                self.assertEqual(member.name, member.value.upper().replace("-", "_"))

    def test_no_word_is_two_members(self):
        for cls in enums():
            with self.subTest(cls.__name__):
                self.assertEqual(len(cls.__members__), len(cls), "an alias: two names for one word")


class StrEnumTests(unittest.TestCase):
    """What makes a member safe wherever a plain string was: `StrEnum` is `(str, ReprEnum)`, so
    `str.__hash__`, `str.__eq__`, `str.__str__` and `str.__format__` come before `Enum`'s."""

    def test_a_member_hashes_and_compares_as_its_value(self):
        for cls, member in members():
            with self.subTest(vocabulary=cls.__name__, member=member.value):
                self.assertIs(type(member.value), str)
                self.assertEqual(hash(member), hash(member.value))
                self.assertEqual(member, member.value)
                self.assertIn(member.value, frozenset(cls))
                self.assertIn(member, frozenset(member.value for member in cls))
                self.assertEqual({member.value: 1}[member], 1)

    def test_json_writes_a_member_as_its_value(self):
        for cls, member in members():
            plain = member.value
            with self.subTest(vocabulary=cls.__name__, member=plain):
                self.assertEqual(json.dumps(member), json.dumps(plain))
                self.assertEqual(json.dumps({member: [member]}), json.dumps({plain: [plain]}))
                # The pure-Python writer (indent, as settings.save writes) and sorted keys.
                self.assertEqual(json.dumps({member: member, "~": 1}, indent=2, sort_keys=True),
                                 json.dumps({plain: plain, "~": 1}, indent=2, sort_keys=True))
                self.assertEqual(json.dumps([member], ensure_ascii=False, separators=(",", ":")),
                                 json.dumps([plain], ensure_ascii=False, separators=(",", ":")))

    def test_the_database_binds_a_member_as_its_value(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE TABLE words (word TEXT)")
            for cls, member in members():
                with self.subTest(vocabulary=cls.__name__, member=member.value):
                    connection.execute("DELETE FROM words")
                    connection.execute("INSERT INTO words VALUES (?)", (member,))
                    self.assertEqual(connection.execute("SELECT word, typeof(word), word = ? FROM words",
                                                        (member.value,)).fetchone(), (member.value, "text", 1))
                    self.assertIs(type(connection.execute("SELECT word FROM words").fetchone()[0]), str)
        finally:
            connection.close()

    def test_formatting_writes_a_member_as_its_value(self):
        for cls, member in members():
            plain = member.value
            with self.subTest(vocabulary=cls.__name__, member=plain):
                self.assertEqual("%s" % member, plain)
                self.assertEqual("%s" % (member,), plain)
                self.assertEqual("{}".format(member), plain)
                self.assertEqual(f"{member}", plain)
                self.assertEqual(format(member, ""), plain)
                self.assertEqual(str(member), plain)
                self.assertEqual("x." + member, "x." + plain)
                self.assertIs(type("x." + member), str)


if __name__ == "__main__":
    unittest.main()

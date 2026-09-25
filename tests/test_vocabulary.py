"""The closed vocabularies: every word the product stores, sends, translates or branches on.

A record's state, a public code, a reason, a gate, a failure category, an error code, a
setting's choice, a registry state - each is a string from a closed list, and each list is
also a contract: the store validates against it, the window and the panel look words up by it,
the catalogs carry a sentence for each member, and the Rust core of v0.6.8 has to write the same
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
from codex_auto_resume.domain import vocabulary as v  # noqa: E402

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
    "machine.WITHDRAW_REASONS": ("set", 11, "48bbe2160073f30c"),
    "machine.SUPERSEDE_WITHDRAWALS": ("set", 3, "b63141bdc33260f0"),
    "machine.TURN_STATUSES": ("set", 5, "58aca83cec78ff2b"),
    "machine.ACTORS": ("set", 5, "eaf35d06c4c2b568"),
    "machine.REASONS": ("set", 63, "05852eb344a83206"),
    "machine.EVENT_CODES": ("set", 21, "09df0cbe0e244464"),
    "machine.WAITING_CODES": ("set", 5, "aef153e5808afe46"),
    "machine.PUBLIC_CODES": ("set", 22, "33761768f9d99cd0"),
    "machine.PAGES": ("tuple", 6, "ffad1c9f0521398d"),
    "machine.OVERLAYS": ("tuple", 7, "ec4b756213ffdd1a"),
    "machine.GATE_RESULTS": ("set", 4, "9a50f41ff116a706"),
    "machine.GATES": ("tuple", 13, "547089c399324718"),
    "machine.GATE_REASONS": ("set", 75, "bb52a0048f24986e"),
    "machine.PASS": "PASS",
    "machine.WAIT": "WAIT",
    "machine.BLOCK": "BLOCK",
    "machine.UNKNOWN": "UNKNOWN",
    "machine.NOT_CHECKED": "not_checked",
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
    "control.ERROR_CODES": ("set", 23, "f5946a4030e69cad"),
    "control.FALLBACK_CODE": "request_failed",
    "continuation.STYLES": ("tuple", 4, "a390c91bf5107f3f"),
    "continuation.CUSTOM_MODES": ("tuple", 2, "a4a918de1aaec837"),
    "continuation.DEFAULT_STYLE": "standard",
    "continuation.DEFAULT_CUSTOM_MODE": "global",
    "settings.THEMES": ("tuple", 3, "bde3c29151568c16"),
    "settings.NOTIFICATION_EVENTS": ("tuple", 4, "edd0f68b3c5a94e6"),
    "settings.RETRY_TIMING": ("dict", 3, "8a8e62ec299a7928"),
    "settings.DEFAULT_TIMING": "normal",
    "settings.THEME_SYSTEM": "system",
    "settings.DEFAULT_THEME": "system",
    "settings.CONTINUATION_LANGUAGES": ("tuple", 10, "9207f7f2b9ec65dc"),
    "l10n.LOCALES": ("tuple", 9, "0d5c5b962a6ec666"),
    "l10n.CHOICES": ("tuple", 10, "8a44c689a27e4025"),
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
    "notifier.STATUS": ("dict", 7, "ed71f4ec9cabc7bc"),
    "mcpserver.Server.START_WORDING": ("dict", 4, "f15e04a780f57870"),
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
    v.RetryTiming: ("keys", "settings.RETRY_TIMING"),
    v.NotifyEvent: ("list", "settings.NOTIFICATION_EVENTS"),
    v.Locale: ("list", "l10n.LOCALES"),
    v.SendOutcome: ("returned", ("Backend.send", "outcome")),
    v.SendError: ("returned", ("Backend.send", "error_code")),
    v.LoadedState: ("returned", ("Backend.loaded", None)),
    v.ActivityState: ("list", "ui.popup.STATES"),
    v.IconState: ("list", "ui.tray.ICON_STATES"),
    v.NoticeKind: ("keys", "notifier.STATUS"),
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
}


def enums():
    """Every vocabulary the module defines."""
    return [value for value in vars(v).values()
            if inspect.isclass(value) and issubclass(value, StrEnum) and value is not StrEnum]


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
                                       codex,
                                       settings,
                                       windows)
        from codex_auto_resume.ui import popup as tray_popup
        self.assertLessEqual(set(v.WithdrawReason), set(v.ReasonCode))
        self.assertEqual(list(compat.COARSE.values()), list(v.EngineState))
        self.assertEqual(list(mcpserver.Server.START_WORDING), ["running", "already-running", "exited", "unconfirmed"])
        self.assertEqual(set(mcpserver.Server.START_WORDING), set(v.WatcherStartState))
        self.assertLessEqual(tray_popup.ATTENTION_OVERLAYS, set(v.Overlay))
        self.assertEqual(codex.KNOWN_STATUSES, set(v.TurnStatus) - {v.TurnStatus.OTHER})
        self.assertEqual(l10n.CHOICES, (l10n.SYSTEM,) + tuple(v.Locale))
        self.assertEqual(settings.CONTINUATION_LANGUAGES, (settings.FOLLOW_INTERFACE,) + tuple(v.Locale))
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

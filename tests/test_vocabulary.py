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
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402

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
    "machine.OVERLAYS": ("tuple", 6, "efd2afa61a31ffc8"),
    "machine.GATE_RESULTS": ("set", 4, "9a50f41ff116a706"),
    "machine.GATES": ("tuple", 13, "547089c399324718"),
    "machine.GATE_REASONS": ("set", 75, "bb52a0048f24986e"),
    "machine.PASS": "PASS",
    "machine.WAIT": "WAIT",
    "machine.BLOCK": "BLOCK",
    "machine.UNKNOWN": "UNKNOWN",
    "machine.NOT_CHECKED": "not_checked",
    "failures.CATEGORIES": ("set", 14, "05e7b8e16f528bde"),
    "failures.TRANSIENT": ("set", 6, "263ab064e954fe3c"),
    "failures.TERMINAL": ("set", 6, "7e746dc3d4241dd2"),
    "failures.USAGE_LIMIT": "usage_limit",
    "failures.UNKNOWN": "unknown",
    "store.ENGINE_STATES": ("set", 4, "a6289bec093a1f82"),
    "source.KNOWN_STATUSES": ("set", 4, "23d2734c27812d29"),
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
    "compat.STATES": ("tuple", 4, "c57aa4c709521ea5"),
    "compat.RESULTS": ("tuple", 4, "734fbec0fd7cd8f0"),
    "compat.TIERS": ("tuple", 4, "c97af83c55d98a0e"),
    "compat.COARSE": ("dict", 4, "8962344937f67c48"),
    "compat.ENGINE_STATES": ("tuple", 4, "18ab4e20bda17c5b"),
    "compat.CHECKS": ("tuple", 13, "4f60ac9722005257"),
    "compat.CAPABILITIES": ("dict", 16, "2ccc411f04f2d0eb"),
    "compat.SEND_GATE": ("tuple", 2, "9f067781e177f778"),
    "compat.RESOLUTION_REASONS": ("set", 6, "271aac9f628b0a21"),
    "compat.VIEW_REASONS": ("set", 4, "9045e2f225c7f918"),
    "compat.REASONS": ("set", 10, "e9b6e345812a2732"),
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
    "tray.ICON_STATES": ("tuple", 5, "e94d5138669400b3"),
    "tray_popup.STATES": ("tuple", 6, "b38c816dbd792bf5"),
    "tray_popup.ATTENTION_OVERLAYS": ("set", 3, "bfd22fd50a01ffd8"),
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
    ("Control.start_watcher", "state"): {"already-running"},
    ("await_watcher", "state"): {"running", "exited", "unconfirmed"},
    ("Control.stop_watcher", "state"): {"not-running"},
    ("await_stopped", "state"): {"stopped", "still-finishing", "unknown"},
}


def value_of(name):
    module, _, attribute = name.partition(".")
    value = importlib.import_module("codex_auto_resume." + module)
    for part in attribute.split("."):
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


if __name__ == "__main__":
    unittest.main()

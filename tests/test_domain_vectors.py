"""The identifiers, the gate vector and the settings file, exactly as the code writes them.

Each of these is written once and read back for as long as the product lives, often by a
later version of it:

* **An interruption id** is computed from a failed turn every time the watcher looks. Compute
  it any differently and every record in the state becomes a *new* interruption - a second
  recovery of a failure that was already recovered. It hashes `float.hex()`, which is
  Python's own spelling of a number, so the vectors cover the spellings that are easy to get
  wrong: zero and negative zero, a negative time, a long mantissa, a subnormal, and an ordinal
  too large for 64 bits.
* **The marker** is how the engine finds its own continuation in Codex's history. Its text is
  searched for in Codex's database; a byte of difference and the engine no longer recognises
  the message it sent.
* **The gate vector** is stored with every record and shown on every surface.
* **The settings file** is hashed by the settings window into its strings-cache key, and the
  user's own Custom text is kept in it as `\\uXXXX` escapes.

The vectors were computed from the code as it was before v0.6.5 gathered the identifiers into
`domain/ids.py`, and they are literal: a change that moves any byte of any of them fails here.
The Rust core of v0.6.8 has to reproduce every one.

The acceptance tables pin the other half: call site by call site, which spellings each reader
of an identifier takes and how it refuses the rest. They do not agree - the control layer reads
anything as its text, the command line only text; the store keeps any key it has ever been
given, the history reader only the exact id - and gathering them into one parser must change
none of it.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote
import uuid

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # the store fixtures live next to this file

from test_store import failure, raw, raw_row  # noqa: E402

from codex_auto_resume import (cli, control, diagnostics, logbook, machine, mcpserver,  # noqa: E402
                               codex, notify, settings, store as store_module, windows)
from codex_auto_resume.control import ControlError  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.store import Store, StoreError  # noqa: E402

THREAD = "0a1b2c3d-0000-4000-8000-00000000000a"
TURN = "0a1b2c3d-0000-4000-8000-00000000000b"
KEY = "ab" * 32


# ---------------------------------------------------------------------- interruption ids
# name -> (completed_at, ordinal, float(completed_at).hex(), the interruption id). For a
# recoverable failure of THREAD's turn TURN.
VECTORS = {
    "an ordinary failure": (1726000000.5, 3, "0x1.9b82ae0200000p+30",
                            "3dcadac46ccd046b9cc97b69e00976734f36b3071f4f664fdeace499736b8fbf"),
    "a whole second, as an int": (1726000000, 3, "0x1.9b82ae0000000p+30",
                                  "8a477d036428c73f753377b7fb10b0b9c07f6b40e7929cc4a1ffdc5353f308df"),
    "a whole second, as a float": (1726000000.0, 3, "0x1.9b82ae0000000p+30",
                                   "8a477d036428c73f753377b7fb10b0b9c07f6b40e7929cc4a1ffdc5353f308df"),
    "a long mantissa": (1726000000.123456789, 3, "0x1.9b82ae007e6b7p+30",
                        "5d6be63a51f9fbd60e32a18a4d98c3cbcc388336a4ab44d59a1fb985d459c2d6"),
    "zero": (0, 0, "0x0.0p+0",
             "bb8693ba67f9ed554c979b9ca6b8e52a621bded45fffb1e58b2574a4e1ca768a"),
    "negative zero": (-0.0, 0, "-0x0.0p+0",
                      "deed9b081dff932213bc41613ca2c5446f4c584e4125707a38e088882cdc619f"),
    "a negative epoch": (-86400.25, 1, "-0x1.5180400000000p+16",
                         "7f8a35e60c87192ef489f5c691a6a189ab78291f84dd691da95ff1c6fc57fe6c"),
    "the smallest subnormal": (5e-324, 1, "0x0.0000000000001p-1022",
                               "3aa798885c501f44c55c40c1adfedfb8c7b3f2b094ea600508d2bb17750c6377"),
    "an ordinal past 64 bits": (1726000000.5, 2 ** 64 + 1, "0x1.9b82ae0200000p+30",
                                "92c836e8647216004ba67af81b61495c33df219264bbc9d0ece272ea6fca9ac7"),
}


def detected(completed, ordinal) -> str:
    """The id `codex.detect` gives the failure. Codex's history only holds times from 2000 to
    2100, so for the vectors outside that window the window is opened: the id has none."""
    row = {"thread_id": THREAD, "turn_id": TURN, "status": "failed", "started_at": completed - 1,
           "completed_at": completed, "ordinal": ordinal, "category": "usage_limit"}
    low, high = machine.EPOCH_CODEX
    if low <= completed <= high:
        return codex.detect(row)["interruption_id"]
    # Patched where it is used, not where it is re-exported: `normalize` reads the time, and
    # since v0.6.10-alpha it lives in `codex/values.py` and holds its own reference to `epoch`.
    with patch.object(codex.values, "epoch", return_value=True):
        return codex.detect(row)["interruption_id"]


def reference(thread_id, turn_id, completed, ordinal) -> str:
    """The formula, written out once more so it can be read: SHA-256 of the compact JSON array
    [thread, turn, float(completed).hex(), ordinal], ASCII-encoded, as lowercase hex."""
    text = json.dumps([thread_id, turn_id, float(completed).hex(), ordinal], separators=(",", ":"))
    return hashlib.sha256(text.encode("ascii")).hexdigest()


class InterruptionIdTests(unittest.TestCase):
    def test_detection_gives_each_failure_its_recorded_id(self):
        for name, (completed, ordinal, _spelled, expected) in VECTORS.items():
            with self.subTest(name):
                self.assertEqual(detected(completed, ordinal), expected)

    def test_the_id_is_the_documented_formula(self):
        for name, (completed, ordinal, spelled, expected) in VECTORS.items():
            with self.subTest(name):
                self.assertEqual(float(completed).hex(), spelled)
                self.assertEqual(reference(THREAD, TURN, completed, ordinal), expected)

    def test_the_one_implementation_gives_each_failure_its_recorded_id(self):
        for name, (completed, ordinal, _spelled, expected) in VECTORS.items():
            with self.subTest(name):
                self.assertEqual(ids.interruption_id(THREAD, TURN, completed, ordinal), expected)
                self.assertTrue(ids.is_interruption_id(expected))

    def test_a_whole_second_is_one_interruption_whether_it_is_an_int_or_a_float(self):
        self.assertEqual(VECTORS["a whole second, as an int"][3], VECTORS["a whole second, as a float"][3])
        self.assertNotEqual(VECTORS["zero"][3], VECTORS["negative zero"][3])


# ------------------------------------------------------------------------------ marker
class MarkerTests(unittest.TestCase):
    def test_the_store_writes_the_marker_of_the_key_it_is_given(self):
        with tempfile.TemporaryDirectory() as temp:
            with Store(Path(temp) / "state") as store:
                for key in (KEY, "rec-0001"):
                    with self.subTest(key):
                        self.assertTrue(store.register(failure(key, THREAD, str(uuid.uuid4())), 111.0))
                        self.assertEqual(store.get(key)["marker"], "[codex-auto-resume:%s]" % key)

    def test_the_history_reader_looks_only_for_a_marker_of_an_exact_id(self):
        accepted = []
        for text in ("[codex-auto-resume:%s]" % KEY, "[codex-auto-resume:%s]" % KEY.upper(),
                     "[codex-auto-resume:%s]\n" % KEY, " [codex-auto-resume:%s]" % KEY,
                     "[codex-auto-resume:%s]" % KEY[:-1], "[codex-auto-resume:rec-0001]",
                     "[codex-auto-resume: %s]" % KEY, "codex-auto-resume:%s" % KEY, None):
            try:
                codex.LocalSource._identity(THREAD, text)
            except codex.SourceError:
                continue
            accepted.append(text)
        self.assertEqual(accepted, ["[codex-auto-resume:%s]" % KEY])

    def test_the_one_implementation_writes_and_reads_the_same_marker(self):
        self.assertEqual(ids.marker(KEY), "[codex-auto-resume:%s]" % KEY)
        self.assertEqual(ids.marker("rec-0001"), "[codex-auto-resume:rec-0001]")
        self.assertTrue(ids.is_marker(ids.marker(KEY)))
        self.assertFalse(ids.is_marker(ids.marker("rec-0001")))
        self.assertTrue(ids.marker(KEY).startswith(ids.MARKER_PREFIX))


# --------------------------------------------------------------------------- gate vector
EVERY_GATE_UNKNOWN = (
    '{"attempt_budget":["UNKNOWN","not_checked"],"chain_budget":["UNKNOWN","not_checked"],'
    '"consent":["UNKNOWN","not_checked"],"engine_compatible":["UNKNOWN","not_checked"],'
    '"identity":["UNKNOWN","not_checked"],"known_failure":["UNKNOWN","not_checked"],'
    '"no_newer_user_work":["UNKNOWN","not_checked"],"no_progress_budget":["UNKNOWN","not_checked"],'
    '"schedule":["UNKNOWN","not_checked"],"single_owner":["UNKNOWN","not_checked"],'
    '"submission_safe":["UNKNOWN","not_checked"],"thread_available":["UNKNOWN","not_checked"],'
    '"usage":["UNKNOWN","not_checked"]}')
EVERY_GATE_PASSES = EVERY_GATE_UNKNOWN.replace('"UNKNOWN","not_checked"', '"PASS","ok"')
ORDER = ("consent", "engine_compatible", "single_owner", "submission_safe", "identity",
         "known_failure", "schedule", "chain_budget", "attempt_budget", "no_progress_budget",
         "thread_available", "no_newer_user_work", "usage")


class GateVectorTests(unittest.TestCase):
    def test_what_is_stored_for_a_vector(self):
        passing = {name: ("PASS", "ok") for name in ORDER}
        self.assertEqual(machine.encode_gates({}), EVERY_GATE_UNKNOWN)
        self.assertEqual(machine.encode_gates(passing), EVERY_GATE_PASSES)
        # A refusal is stored with its reason; a result that is not one is UNKNOWN, a reason
        # that is not one is `other`, and a name that is not a gate is not stored.
        mixed = dict(passing, consent=("BLOCK", "paused"), schedule=("WAIT", "not_due"),
                     usage=("MAYBE", "usage_available"), identity=("PASS", "made up"), extra=("PASS", "ok"))
        self.assertEqual(machine.encode_gates(mixed), EVERY_GATE_PASSES
                         .replace('"consent":["PASS","ok"]', '"consent":["BLOCK","paused"]')
                         .replace('"identity":["PASS","ok"]', '"identity":["PASS","other"]')
                         .replace('"schedule":["PASS","ok"]', '"schedule":["WAIT","not_due"]')
                         .replace('"usage":["PASS","ok"]', '"usage":["UNKNOWN","usage_available"]'))

    def test_what_is_read_back(self):
        unknown = {name: ("UNKNOWN", "not_checked") for name in ORDER}
        for text in (None, "", "not json", "[]", "x" * 4001, EVERY_GATE_UNKNOWN):
            with self.subTest(text=(text or "")[:20]):
                self.assertEqual(machine.decode_gates(text), unknown)
        self.assertEqual(list(machine.decode_gates(EVERY_GATE_PASSES)), list(ORDER))
        self.assertEqual(machine.decode_gates(EVERY_GATE_PASSES), {name: ("PASS", "ok") for name in ORDER})
        stored = ('{"consent":["PASS","ok"],"usage":["WAIT","nonsense"],"schedule":["MAYBE","ok"],'
                  '"identity":["PASS",3]}')
        self.assertEqual(machine.decode_gates(stored),
                         dict(unknown, consent=("PASS", "ok"), usage=("WAIT", "other")))


# ------------------------------------------------------------------------ settings file
# v0.6.10 writes no recover_ or custom_message_ key for auth_service_transient, which nothing
# produces (failures.RESERVED); a file that still has them reads as it did (test_settings).
DEFAULT_FILE = """{
  "codex_exe": null,
  "config_version": 2,
  "continuation_language": "follow",
  "continuation_style": "standard",
  "custom_message": null,
  "custom_message_mode": "global",
  "custom_message_network_transient": null,
  "custom_message_rate_limit_transient": null,
  "custom_message_server_5xx": null,
  "custom_message_stream_interrupted": null,
  "custom_message_timeout": null,
  "custom_message_usage_limit": null,
  "design": "soft",
  "detection_lookback_hours": 6.0,
  "interface_language": "system",
  "max_chain_continuations": 6,
  "max_no_progress": 3,
  "max_recovery_attempts": 4,
  "notification_card": true,
  "notifications": true,
  "notify_interruption": true,
  "notify_result": true,
  "notify_starting": true,
  "notify_stopped": true,
  "panel_theme": "same",
  "recover_network_transient": true,
  "recover_rate_limit_transient": true,
  "recover_server_5xx": true,
  "recover_stream_interrupted": true,
  "recover_timeout": true,
  "recover_usage_limit": true,
  "reduce_motion": false,
  "retry_timing": "normal",
  "show_tray": true,
  "start_with_codex": false,
  "theme": "system"
}"""
KOREAN = "\uc5ec\uae30\uc11c \uc774\uc5b4\uc11c \uacc4\uc18d\ud574 \uc8fc\uc138\uc694. {reason}"
KOREAN_USAGE = "\ud55c\ub3c4\uac00 \ud480\ub838\uc5b4\uc694 \u2014 \uacc4\uc18d!"


class SettingsFileTests(unittest.TestCase):
    def saved(self, values) -> bytes:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "settings.json"
            settings.save(target, values)
            written = target.read_bytes()
            self.assertEqual(settings.load(target), settings.coerce(values))
        return written

    def test_the_defaults_are_written_as_these_bytes(self):
        # Sorted keys, two spaces, no final newline; the lines end as a text file does here.
        self.assertEqual(self.saved(settings.defaults()),
                         DEFAULT_FILE.replace("\n", os.linesep).encode("ascii"))

    def test_the_users_own_words_are_kept_as_escapes(self):
        written = self.saved(dict(settings.defaults(), custom_message=KOREAN,
                                  custom_message_usage_limit=KOREAN_USAGE, theme="dark"))
        expected = (DEFAULT_FILE
                    .replace('"custom_message": null', '"custom_message": "\\uc5ec\\uae30\\uc11c '
                             '\\uc774\\uc5b4\\uc11c \\uacc4\\uc18d\\ud574 \\uc8fc\\uc138\\uc694. {reason}"')
                    .replace('"custom_message_usage_limit": null', '"custom_message_usage_limit": '
                             '"\\ud55c\\ub3c4\\uac00 \\ud480\\ub838\\uc5b4\\uc694 \\u2014 \\uacc4\\uc18d!"')
                    .replace('"theme": "system"', '"theme": "dark"'))
        self.assertEqual(written, expected.replace("\n", os.linesep).encode("ascii"))


# -------------------------------------------------------------------- who takes what
# Spellings of a conversation's id, and how each reader answers them.
UUIDS = {
    "canonical": THREAD,
    "capitals": THREAD.upper(),
    "braces": "{" + THREAD + "}",
    "urn": "urn:uuid:" + THREAD,
    "no dashes": THREAD.replace("-", ""),
    "arabic digit": THREAD[:-1] + "\u0660",
    "underscore": THREAD[:9] + "0_00" + THREAD[13:],
    "padded": " " + THREAD + " ",
    "newline": THREAD + "\n",
    "short": THREAD[:-1],
    "long": THREAD + "0",
    "not hex": THREAD[:-1] + "g",
    "empty": "",
    "last": "--last",
    "none": None,
    "int": 12345,
    "bytes": THREAD.encode("ascii"),
    "uuid object": uuid.UUID(THREAD),
}
# A UUID written some other way than the canonical text: Python's parser reads it, and every
# reader refuses it - some of them saying why.
SPELLED_OTHERWISE = {"capitals", "braces", "urn", "no dashes", "arabic digit", "underscore"}
NOT_A_UUID = {"padded", "newline", "short", "long", "not hex", "empty", "last", "none", "int", "bytes"}


def answer(call):
    """("ok", what it returned) or (the exception's class, its text, its code if it has one)."""
    try:
        return ("ok", call())
    except Exception as exc:
        return (type(exc), str(exc), getattr(exc, "code", None))


def normalized(value) -> bool:
    row = {"thread_id": value, "turn_id": TURN, "status": "failed", "started_at": 1e9,
           "completed_at": 1e9 + 1, "ordinal": 1, "category": "usage_limit"}
    return codex.normalize(row) is not None


class ThreadIdTests(unittest.TestCase):
    def test_the_spellings_are_the_ones_named(self):
        self.assertEqual(set(UUIDS), {"canonical", "uuid object"} | SPELLED_OTHERWISE | NOT_A_UUID)

    def expect(self, reader, table):
        for name, value in UUIDS.items():
            with self.subTest(name):
                self.assertEqual(reader(value), table(name))

    def test_the_store(self):
        self.expect(lambda value: answer(lambda: store_module._uuid(value, "thread_id")),
                    lambda name: ("ok", THREAD) if name == "canonical"
                    else (StoreError, "Invalid thread_id: canonical UUID required", None)
                    if name in SPELLED_OTHERWISE else (StoreError, "Invalid thread_id", None))

    def test_the_history_reader(self):
        self.expect(normalized, lambda name: name == "canonical")

    def test_the_control_layer_reads_any_value_as_its_text(self):
        self.expect(lambda value: answer(lambda: control._thread_id(value)),
                    lambda name: ("ok", THREAD) if name in ("canonical", "uuid object")
                    else (ControlError, "thread id must be lowercase canonical UUID text", "invalid_thread_id")
                    if name in SPELLED_OTHERWISE
                    else (ControlError, "thread id must be a canonical UUID", "invalid_thread_id"))

    def test_the_command_line_takes_only_the_text(self):
        self.expect(lambda value: answer(lambda: cli.canonical_thread_id(value)),
                    lambda name: ("ok", THREAD) if name == "canonical"
                    else (cli.CliError, "thread id must be lowercase canonical UUID text", None)
                    if name in SPELLED_OTHERWISE | {"uuid object"}
                    else (cli.CliError, "thread id must be a canonical UUID (never --last or a name)", None))

    def test_the_codex_adapter(self):
        # Every caller in the adapter turns the ValueError into its own fixed answer, so only
        # its type is part of the contract.
        self.expect(lambda value: answer(lambda: windows.canonical_uuid(value))[0],
                    lambda name: "ok" if name == "canonical" else ValueError)

    def test_the_log(self):
        self.expect(lambda value: logbook.render(value, "loaded", None),
                    lambda name: "thread %s: loaded" % THREAD if name == "canonical" else "loaded")

    def test_the_published_pattern_takes_exactly_what_the_parser_takes(self):
        """The MCP schema and the diagnostics bundle describe a UUID by a pattern, and every
        reader parses one with Python's own parser; over every spelling here, and every
        single-character change to the canonical text, the two agree."""
        pattern = re.compile(ids.uuid_pattern())
        spellings = [value for value in UUIDS.values() if isinstance(value, str)]
        spellings += [THREAD[:at] + character + THREAD[at + 1:] for at in range(len(THREAD))
                      for character in "0aA-g_ \u0660{"]
        for text in spellings:
            with self.subTest(text=text):
                self.assertEqual(ids.is_uuid(text), pattern.fullmatch(text) is not None)

    def test_the_diagnostics_bundle_aliases_any_case_and_leaves_the_rest(self):
        expected = {
            "canonical": "x <thread> y", "capitals": "x <thread> y", "braces": "x {<thread>} y",
            "urn": "x urn:uuid:<thread> y", "no dashes": "x <record> y",
            "arabic digit": "x 0a1b2c3d-0000-4000-8000-00000000000\u0660 y",
            "underscore": "x 0a1b2c3d-0_00-4000-8000-<record> y", "padded": "x  <thread>  y",
            "newline": "x <thread>\n y", "short": "x 0a1b2c3d-0000-4000-8000-00000000000 y",
            "long": "x 0a1b2c3d-0000-4000-8000-<record> y",
            "not hex": "x 0a1b2c3d-0000-4000-8000-00000000000g y", "empty": "x  y", "last": "x --last y",
        }
        redact = diagnostics.Redactor()
        for name, text in expected.items():
            with self.subTest(name):
                self.assertEqual(re.sub(r"(thread|record)-[0-9a-f]{8}", r"<\1>",
                                        redact.text("x " + UUIDS[name] + " y")), text)


# Spellings of an interruption id, and of the keys the store keeps.
KEYS = {
    "exact": KEY,
    "capitals": KEY.upper(),
    "padded": "  " + KEY + " ",
    "tab and newline": "\t" + KEY + "\n",
    "ideographic space": "\u3000" + KEY,
    "63": KEY[:-1],
    "65": KEY + "a",
    "not hex": KEY[:-1] + "g",
    "fullwidth digit": KEY[:-1] + "\uff10",
    "store key": "rec-0001",
    "underscores": "a_b-C",
    "128": "k" * 128,
    "129": "k" * 129,
    "empty": "",
    "none": None,
    "zero": 0,
    "false": False,
    "int": 7,
}
# What a person or a link may hand over: surrounding white space is dropped and capitals are
# lowered, and then it must be exactly an id.
HANDED_OVER = {"exact", "capitals", "padded", "tab and newline", "ideographic space"}
# What the store has always kept as a record's key, or the key of its parent or its chain.
STORE_KEYS = {"exact", "capitals", "63", "65", "not hex", "store key", "underscores", "128"}


class InterruptionIdAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name) / "state"
        with Store(root) as store:
            store.register(failure("seed" * 16, THREAD), 111.0)
        db = raw(root)
        try:
            cls.row = raw_row(db, "seed" * 16)
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_the_spellings_are_the_ones_named(self):
        self.assertLessEqual(HANDED_OVER | STORE_KEYS, set(KEYS))

    def test_the_control_layer(self):
        for name, value in KEYS.items():
            with self.subTest(name):
                self.assertEqual(answer(lambda: control._identifier(value)),
                                 ("ok", KEY) if name in HANDED_OVER
                                 else (ControlError, "invalid interruption id", "invalid_id"))

    def test_a_notification_button(self):
        for name, value in KEYS.items():
            if isinstance(value, str):
                with self.subTest(name):
                    self.assertEqual(notify.parse_cancel_uri("codex-auto-resume:cancel?i=" + quote(value, safe="")),
                                     KEY if name in HANDED_OVER else None)

    def test_the_history_reader_takes_only_the_exact_id_in_a_marker(self):
        for name, value in KEYS.items():
            if isinstance(value, str):
                with self.subTest(name):
                    self.assertEqual(answer(lambda: codex.LocalSource._identity(THREAD, "[codex-auto-resume:%s]" % value)),
                                     ("ok", None) if name == "exact"
                                     else (codex.SourceError, "Invalid delivery identity", None))

    def test_the_store_keeps_any_key_it_has_ever_kept(self):
        for field in ("interruption_id", "parent_interruption_id", "chain_origin_id"):
            for name, value in KEYS.items():
                row = dict(self.row, **{field: value})
                if field == "interruption_id":
                    row["marker"] = "[codex-auto-resume:%s]" % value
                with self.subTest(field=field, key=name):
                    kept = name in STORE_KEYS or (field == "parent_interruption_id" and value is None)
                    self.assertEqual(answer(lambda: store_module._validated_record(row)[field]),
                                     ("ok", value) if kept else (StoreError, "Invalid %s" % field, None))

    def test_the_log_prints_a_hex_detail_up_to_an_ids_length(self):
        expected = {"exact": KEY[:12], "63": KEY[:12], "none": "", "zero": "0", "int": "7"}
        for name, value in KEYS.items():
            with self.subTest(name):
                self.assertEqual(logbook.render(THREAD, "usageLimitExceeded_detected", None, value),
                                 "thread %s: usageLimitExceeded detected (interruption %s)"
                                 % (THREAD, expected.get(name, "?")))

    def test_the_diagnostics_bundle_aliases_twelve_to_sixty_four_hex_digits(self):
        aliased = {"exact", "padded", "tab and newline", "ideographic space", "63"}
        redact = diagnostics.Redactor()
        for name, value in KEYS.items():
            if isinstance(value, str):
                with self.subTest(name):
                    text = re.sub(r"(thread|record)-[0-9a-f]{8}", r"<\1>", redact.text("x " + value + " y"))
                    self.assertEqual(text, "x " + (value.replace(KEY, "<record>").replace(KEY[:-1], "<record>")
                                                   if name in aliased else value) + " y")


CLIENTS = {"plain": "abc-DEF-123", "64": "a" * 64, "65": "a" * 65, "underscore": "a_b", "space": "a b",
           "empty": "", "none": None, "int": 5, "unicode": "\u00e9", "newline": "abc\n"}


class ClientIdTests(unittest.TestCase):
    def test_the_history_reader_and_the_store_take_the_same_client_ids(self):
        taken = {"plain", "64"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "state"
            with Store(root) as store:
                store.register(failure(KEY, THREAD), 111.0)
            db = raw(root)
            try:
                row = raw_row(db, KEY)
            finally:
                db.close()
        for name, value in CLIENTS.items():
            with self.subTest(name):
                self.assertEqual(ids.is_client_id(value), name in taken)
                self.assertEqual(answer(lambda: store_module._validated_record(
                    dict(row, recovery_client_id=value))["recovery_client_id"]),
                    ("ok", value) if name in taken | {"none"}
                    else (StoreError, "Invalid recovery_client_id", None))


class SchemaPatternTests(unittest.TestCase):
    def test_the_mcp_tools_describe_an_id_with_these_patterns(self):
        patterns = {}
        for tool in mcpserver.TOOLS:
            for name, schema in tool["inputSchema"].get("properties", {}).items():
                if "pattern" in schema:
                    patterns.setdefault(name, set()).add(schema["pattern"])
        self.assertEqual(patterns, {
            "interruption_id": {"^[0-9a-fA-F]{64}$"},
            "thread_id": {"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
        })


if __name__ == "__main__":
    unittest.main()

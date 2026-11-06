"""A reason outlives the version that wrote it (#58's follow-up): what an older and a newer version do with one they
do not know.

A record waiting `app_server_unmatched` meets an older version when a person uses Install another version: v0.6.15 to
v0.6.21 read the same schema 5 file as it is, and v0.6.14 and older read what `downgrade-state` writes, which keeps
`last_error`. `last_error` is free text to every store back to v0.5 (store/validate.py, _short_text), so it refuses nothing;
each surface reads the word through machine.public_reason and decode_gates, which say "other" for a word they do not know.

Asked of the tagged releases themselves, in processes of their own (tests/released.py): their store opens the file, the
record is still the waiting record it was and nothing is sent for it, and the first time their own engine looks at it they
write their own word over it. What a window of theirs shows until then is S("why.other", null): the catalog has no such
sentence, so the reason line is empty for at most one look, and never false.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import released  # noqa: E402
from codex_auto_resume import machine  # noqa: E402
from codex_auto_resume.store import downgrade_to_v3  # noqa: E402
from test_engine import Harness, T1, TURN_A  # noqa: E402
from codexsim import RESET  # noqa: E402

# The newest release before this work: the one a person going back is most likely to pick.
V0621 = "v0.6.21"
UNMATCHED = "app_server_unmatched"

# The release's own store, vocabulary, catalog and engine on a state and a Codex home a test built with tests/codexsim.py
# (which imports nothing of the product): how it reads the one record; then one look of its engine with no app.
_OLDER = r"""
import json, sys
from pathlib import Path
root, tests, now, options = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]), sys.argv[4]
sys.path.append(tests)
from codexsim import CodexHome, SimBackend
from codex_auto_resume import l10n, machine
from codex_auto_resume.codex import LocalSource
from codex_auto_resume.engine import Engine
from codex_auto_resume.store import Store
clock = [now]
home = CodexHome.__new__(CodexHome)              # the home the test built; nothing is created again
home.root, home._items, home.clock = root / "codex-home", 100000, lambda: clock[0]
backend = SimBackend(home)
backend.app = None
with Store(root) as store:
    row = store.all_records()[0]
    read = {"state": row["state"], "last_error": row["last_error"], "code": machine.public_code(row),
            "reason": machine.public_reason(row), "overlays": machine.overlays(row),
            "gate": list(machine.decode_gates(row["gate_eval"])["thread_available"]),
            "sentence": l10n.catalog("en").get("why.other")}
    engine = Engine(store, LocalSource(home.root), backend, clock=lambda: clock[0], log=lambda *a: None,
                    options=json.loads(options), notify=lambda *a: None)
    for _ in range(3):
        clock[0] += 600
        engine.tick()
    row = store.all_records()[0]
    print(json.dumps({"read": read, "sent": len(backend.send_calls), "state": row["state"],
                      "last_error": row["last_error"], "records": len(store.all_records())}))
"""


class WrittenByThisVersionCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.h = Harness(Path(temporary.name) / "state")
        self.addCleanup(self.h.close)
        self.h.enable()
        self.h.home.add_thread(T1)
        self.h.home.fail_usage(T1, TURN_A)
        self.h.tick()
        self.h.backend.app = None
        self.h.backend.app_look = "unmatched"
        self.h.now = RESET + 61
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("waiting_for_app", UNMATCHED))
        self.assertEqual(self.h.backend.send_calls, [])


class OlderVersionTests(WrittenByThisVersionCase):
    def older(self, tag):
        self.h.store.close()
        return released.run(tag, _OLDER, self.h.root, _HERE, self.h.now, json.dumps(self.h.options))

    def assert_fails_safe(self, found):
        read = found["read"]
        self.assertEqual((read["state"], read["last_error"], read["code"]), ("waiting_for_app", UNMATCHED, "waiting_thread"))
        self.assertEqual(read["reason"], "other", "it would show a word it has no sentence for")
        self.assertEqual(read["gate"], ["WAIT", "other"], "a wait stays a wait")
        self.assertEqual(read["overlays"], [])
        self.assertIsNone(read["sentence"], "no sentence: the reason line is empty, and never false")
        self.assertEqual(found["sent"], 0)
        self.assertEqual((found["state"], found["last_error"]), ("waiting_for_app", "desktop_app_unavailable"))
        self.assertEqual(found["records"], 1)

    def test_v0_6_21_reads_the_same_file_as_it_is_and_writes_its_own_word_at_its_first_look(self):
        self.assert_fails_safe(self.older(V0621))

    def test_v0_6_10_reads_what_the_downgrade_keeps(self):
        self.h.store.close()
        downgrade_to_v3(self.h.root)
        self.assert_fails_safe(released.run(released.V0610, _OLDER, self.h.root, _HERE, self.h.now,
                                            json.dumps(self.h.options)))


class NewerVersionTests(WrittenByThisVersionCase):
    def test_a_word_of_a_later_version_is_other_and_this_engine_writes_its_own(self):
        gates = json.loads(self.h.record()["gate_eval"])
        gates["thread_available"] = ["WAIT", "from_a_later_version"]
        connection = sqlite3.connect(self.h.root / "state.sqlite")
        connection.execute("UPDATE interruptions SET last_error='from_a_later_version', gate_eval=?", (json.dumps(gates),))
        connection.commit()
        connection.close()
        row = self.h.record()
        self.assertEqual(machine.public_reason(row), "other")
        self.assertEqual(machine.decode_gates(row["gate_eval"])["thread_available"], ("WAIT", "other"))
        self.assertEqual(machine.overlays(row), [])
        self.h.tick(advance=3600)
        self.assertEqual(self.h.record()["last_error"], UNMATCHED)
        self.assertEqual(self.h.backend.send_calls, [])

    def test_an_older_version_s_word_is_read_as_it_was_and_replaced_at_the_next_look(self):
        connection = sqlite3.connect(self.h.root / "state.sqlite")
        connection.execute("UPDATE interruptions SET last_error='desktop_app_unavailable'")
        connection.commit()
        connection.close()
        row = self.h.record()
        self.assertEqual(machine.public_reason(row), "desktop_app_unavailable")
        self.h.tick(advance=3600)
        self.assertEqual(self.h.record()["last_error"], UNMATCHED)


if __name__ == "__main__":
    unittest.main()

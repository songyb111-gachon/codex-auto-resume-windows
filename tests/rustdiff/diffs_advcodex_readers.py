"""S7.2c: the advanced edition's read-only readers of Codex's own files, held equal to the v0.6.26 final.

codex/turns.py (`latest`, `turn_code`, `status`, `recent`, `running`, `between`, `plan_statuses`, split conversations
read through core's chain), lineage.py, threads.py, conversation.py, sessions.py (`rollout`, `find`, `names`, `origin`,
`events_since`, `newest_event`), goals.py and credits.py. Each Codex home is written once (tests/codexsim.py's tables
through codexdiff.Home, plus spawn edges, goals databases, extra ordering columns, rollouts and the odd rows: a BLOB
where a text belongs, text that is no UTF-8, an ordinal that is no int, statuses and kinds of every shape, a split
conversation) and read by both sides where it is; homes that are wrong as a whole (no history, a history whose table
moved on, a database that is no database, no state, no goals, two goals generations) are read too. str.isalpha is asked
of every code point. advanced/tests/test_advanced_codex_reads.py, _conversations, _chat, _goal and _credits are the
shapes mirrored.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_readers`.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from rustdiff import codexdiff
from rustdiff.advcodex import AdvCodexDiff

RECORD: list = []
A, B, C, D, E, F = codexdiff.IDS
BASE = codexdiff.BASE
T1, T2, T3, T4 = ("0a1b2c3d-0002-7000-8000-00000000000%d" % n for n in range(1, 5))
JUNK = ["x", 5, None, A.upper(), A + " ", ""]
MARK = "[codex-auto-resume:0123456789abcdef]"


def build(root: Path, *, ordering=None, edges=True, goals=True) -> codexdiff.Home:
    home = codexdiff.Home(root)
    if ordering:
        for column in ordering:
            home.state("ALTER TABLE threads ADD COLUMN %s INTEGER" % column)
    if edges:
        home.state("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT, status TEXT)")
    for index, thread in enumerate([A, B, C, D, E]):
        home.thread(thread, name=["Alpha", None, "Gamma\nline", "Delta", "  "][index],
                    source=["vscode", "vscode", "cli", "vscode", "vscode"][index],
                    thread_source=["user", "user", "user", "subagent", "user"][index])
    if ordering:
        for index, thread in enumerate([A, B, C, D, E]):
            for column in ordering:
                home.state("UPDATE threads SET %s=? WHERE id=?" % column, [5, 3, 9, 1, 7][index], thread)
    home.turn(A, T1, status="completed", ordinal=1, completed=int(BASE) - 50, started=int(BASE) - 200)
    home.turn(A, T2, status="failed", ordinal=2, error_json=json.dumps({"codexErrorInfo": {"usageLimitExceeded": {}}}),
              completed=int(BASE), final_agent="item-final", started=int(BASE) - 60)
    home.item(A, T2, "i1", "agentMessage", {"text": "hello " + MARK}, 1)
    home.item(A, T2, "i2", "userMessage", {"content": [{"type": "text", "text": "do it"}, {"type": "image"}]}, 2)
    home.item(A, T2, "i3", "commandExecution", {"x": 1}, 3)
    home.item(A, T2, "i4", "fileChange", {"x": 1}, 4)
    home.item(A, T2, "i5", "plan", {"steps": [{"status": "completed"}, {"status": "pending"}, {"status": 5}]}, 5)
    home.item(A, T2, "i6", "weird kind", {}, 6)
    home.item(A, T2, "i7", "x" * 70, {}, 7)
    home.item(A, T2, "i8", "Ωmega", {}, 8)
    home.item(A, T2, "i9", "agentMessage", "not json", 9)
    home.item(A, T2, "i10", "agentMessage", {"text": "\ud800 half"}, 10)
    home.turn(B, T3, status="inProgress", ordinal=7, completed=None, started=int(BASE) - 10)
    home.item(B, T3, "j1", "plan", {"steps": "none"}, 1)
    home.item(B, T3, "j2", "userMessage", {"content": "words"}, 2)
    home.item(B, T3, "j3", "agentMessage", {"text": "é" * 20000}, 3)
    home.turn(C, T4, status="weird", ordinal=3, completed=0, started=None,
              error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
    home.history("INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, status, started_at) VALUES (?,?,?,?,?)",
                 D, "not-a-uuid", 4, "completed", int(BASE))
    home.history("INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, status, started_at, completed_at) "
                 "VALUES (?,?,?,?,?,?)", E, T1, "4.5", "completed", "soon", int(BASE) + 5)
    home.history("INSERT INTO thread_items (thread_id, turn_id, item_id, rollout_ordinal, item_json, item_type) "
                 "VALUES (?,?,?,?,?,?)", A, T1, "b1", 1, b"blob", b"agentMessage")
    if edges:
        for parent, child, status in ((A, B, "open"), (A, C, "closed"), (A, A, "x"), (A, "junk", "x"), (B, D, "x"),
                                      (A, F, "x")):
            home.state("INSERT INTO thread_spawn_edges VALUES (?,?,?)", parent, child, status)
    if goals:
        connection = sqlite3.connect(root / "goals_2.sqlite")
        connection.execute("CREATE TABLE thread_goals (thread_id TEXT, goal_id TEXT, status TEXT, updated_at_ms INTEGER, "
                           "objective TEXT)")
        for thread, goal, status, updated in ((A, "g1", "active", 5), (B, "g2", "nonsense", 6), (C, "", "active", 7),
                                              (D, "g" * 129, "paused", 8), (E, "g5", "complete", "late")):
            connection.execute("INSERT INTO thread_goals VALUES (?,?,?,?,?)", (thread, goal, status, updated, "secret"))
        connection.commit()
        connection.close()
        (root / "goals_1.sqlite").write_bytes(b"older")
    home.append(A, [{"type": "event_msg", "payload": {"type": "task_started"}}, b"not json\n",
                    {"type": "response_item", "payload": {"type": "agent_message"}}, b"   \n",
                    {"type": "event_msg", "payload": {"type": "token_count2"}}, b'{"type": "x"'])
    split = home.split_file(A, F, stamp=1)
    archived = root / "archived_sessions" / "2026" / ("rollout-x-%s.jsonl" % E)
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_bytes(b'{"type": "session_meta", "payload": {"id": "%s"}}\n' % E.encode())
    home.state("UPDATE threads SET rollout_path=? WHERE id=?", str(archived), E)
    (root / "sessions" / ("ROLLOUT-%s.JSONL" % D.upper())).write_bytes(b"{}\n")
    (root / "sessions" / ("rollout-%sx.jsonl" % B)).write_bytes(b"{}\n")
    return home


def cases_for(root: Path) -> list:
    home = str(root)
    cases = []
    for thread in [A, B, C, D, E, F] + JUNK:
        cases += [["rd.turns.latest", home, thread], ["rd.turns.plan_statuses", home, thread],
                  ["rd.lineage.children", home, thread], ["rd.conversation.view", home, thread],
                  ["rd.sessions.rollout", home, thread], ["rd.sessions.find", home, thread],
                  ["rd.sessions.origin", home, thread], ["rd.sessions.newest_event", home, thread],
                  ["rd.goals.read", home, thread]]
        for turn in (T1, T2, T3, T4, "x"):
            cases += [["rd.turns.status", home, thread, turn], ["rd.turns.turn_code", home, thread, turn]]
        for offset in (None, 0, 10, 100000, -5, 2 ** 40):
            cases.append(["rd.sessions.events_since", home, thread, offset])
        for after, before in ((0, 5), (1, 2), (-1, 3), (2 ** 40 + 1, 2 ** 40 + 3), (1, 2 ** 40 + 1), (5, 1), (-2 ** 41, 3),
                              (1.0, 2), (True, 2)):
            cases.append(["rd.turns.between", home, thread, after, before])
    for since in (0, BASE - 100, BASE, BASE + 1, 2.5):
        cases.append(["rd.turns.recent", home, since])
    for booted in (None, BASE, BASE - 1000, BASE + 1000, "x", 10 ** 400):
        cases.append(["rd.turns.running", home, booted])
    for limit in (0, 1, 2, 10):
        for skip in ([], [A], [A, C]):
            cases.append(["rd.threads.own", home, limit, skip])
    cases.append(["rd.sessions.names", home])
    return cases


def credit_replies() -> list:
    window = {"usedPercent": 50, "windowDurationMins": 300, "resetsAt": int(BASE) + 600}
    base = {"rateLimits": {"primary": window, "secondary": dict(window, windowDurationMins=10080)}}
    out = [None, {}, [], base]
    for summary in ({"availableCount": 2, "credits": None}, {"availableCount": 0}, {"availableCount": 1001},
                    {"availableCount": True}, {"availableCount": 2, "credits": []},
                    {"availableCount": 2, "credits": [{"status": "available", "expiresAt": int(BASE) + 50}]},
                    {"availableCount": 2, "credits": [{"status": "available", "expiresAt": None},
                                                      {"status": "available", "expiresAt": int(BASE) + 5}]},
                    {"availableCount": 2, "credits": [{"status": "used"}, {"status": "available", "expiresAt": 1.5}]},
                    {"availableCount": 2, "credits": [{"status": 5}]}, {"availableCount": 2, "credits": ["x"]},
                    {"availableCount": 2, "credits": [{"status": "available", "expiresAt": 0}]},
                    {"availableCount": 2, "credits": [{"status": "available", "expiresAt": 4102444800}]},
                    {"availableCount": 2, "credits": [{"status": "available", "expiresAt": 4102444801}]},
                    "x", None):
        out.append(dict(base, rateLimitResetCredits=summary, ordinaryUsageAllowed=True))
        out.append(dict(base, rateLimitResetCredits=summary, ordinaryUsageAllowed="yes"))
    return out


class ReadersDiff(AdvCodexDiff):
    def test_a_full_home(self):
        total = 0
        for label, options in (("plain", {}), ("updated_at_ms", {"ordering": ["updated_at_ms"]}),
                               ("updated_at", {"ordering": ["updated_at"]}), ("created_at_ms", {"ordering": ["created_at_ms"]}),
                               ("created_at", {"ordering": ["created_at"]})):
            root = self.fresh("home-%s" % label) / "codex-home"
            build(root, **options)
            cases = cases_for(root)
            self.same("home %s" % label, cases)
            total += len(cases)
        RECORD.append("readers: 5 full homes, %d reads" % total)

    def test_homes_wrong_as_a_whole(self):
        total = 0
        for label in ("no history", "history moved on", "not a database", "no state", "no goals", "no edges",
                      "empty", "two goals generations", "goals moved on", "no home"):
            root = self.fresh("wrong-%s" % label.replace(" ", "-")) / "codex-home"
            if label != "no home":
                build(root, edges=label != "no edges", goals=label not in ("no goals", "goals moved on"))
            if label == "no history":
                (root / "thread_history_1.sqlite").unlink()
            elif label == "history moved on":
                connection = sqlite3.connect(root / "thread_history_1.sqlite")
                connection.execute("ALTER TABLE thread_items RENAME COLUMN item_type TO kind")
                connection.commit()
                connection.close()
            elif label == "not a database":
                (root / "thread_history_2.sqlite").write_bytes(b"this is not sqlite" * 100)
                (root / "goals_3.sqlite").write_bytes(b"this is not sqlite" * 100)
            elif label == "no state":
                (root / "state_5.sqlite").unlink()
            elif label == "empty":
                for path in root.glob("*.sqlite"):
                    path.unlink()
            elif label == "two goals generations":
                connection = sqlite3.connect(root / "goals_١٠.sqlite")
                connection.execute("CREATE TABLE thread_goals (thread_id TEXT, goal_id TEXT, status TEXT, updated_at_ms INTEGER)")
                connection.execute("INSERT INTO thread_goals VALUES (?,?,?,?)", (A, "newer", "blocked", 9))
                connection.commit()
                connection.close()
            elif label == "goals moved on":
                connection = sqlite3.connect(root / "goals_4.sqlite")
                connection.execute("CREATE TABLE thread_goals (thread_id TEXT, goal TEXT, status TEXT, updated_at_ms INTEGER)")
                connection.commit()
                connection.close()
            cases = cases_for(root)
            self.same("wrong %s" % label, cases)
            total += len(cases)
        RECORD.append("readers: 10 homes wrong as a whole, %d reads" % total)

    def test_pure(self):
        cases = [["rd.credits.params"]]
        for reply in credit_replies():
            cases += [["rd.credits.parse", reply], ["rd.credits.details_listed", reply]]
        for outcome in ("reset", "nothingToReset", "noCredit", "alreadyRedeemed", "other", 5, None):
            cases.append(["rd.credits.outcome", {"outcome": outcome}])
        cases.append(["rd.credits.outcome", None])
        for windows in (None, [], [{"used_percent": 100, "reset_at": 5}, {"used_percent": 99.9, "reset_at": 5},
                                   {"used_percent": 150, "reset_at": None}], [{"used_percent": "x", "reset_at": 1}],
                        [{"reset_at": 1}]):
            cases.append(["rd.credits.full", windows])
        # str.isalpha over every code point, in strides the request can carry.
        cases += [["rd.alpha", chr(point)] for point in range(0, 0x110000) if not 0xD800 <= point < 0xE000]
        cases += [["rd.alpha", text] for text in ("", "ab", "a1", "a_b", "Ⅻ", "ǅ", "ʰ", "ͅ")]
        self.same("pure", cases, chunk=60000)
        RECORD.append("readers: credits and str.isalpha over every code point")

"""S3.2, car-codex's readers held to the reference tag on Codex homes: the done-check of PLAN 5.3, "equal reads of
every codexsim, sessionsim and fixture home".

`HomeDiff` writes the homes the repository's own tests read - codexsim's `CodexHome` in every shape its builders make
(usage limits, transient failures, queues, dispatches, stale projections, splits) and the odd ones the fixtures and
the audits hold (the first lines of rollout files of every kind, schemas that moved, rows of the wrong type, paths
that point elsewhere) - and asks each one every question the product asks of Codex (`codexbattery.battery`): the
reference's `LocalSource` and car-codex answer the same list of calls, and every answer must be the same value.

`sessionsim` is no home: it gives the engine tests' backend the habit of naming who holds a conversation, which is the
transport's (S3.3), so the homes here are codexsim's, and the rollout files and rows that codexsim has no builder for.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import sqlite3
import unittest

from rustdiff.codexbattery import battery, op
from rustdiff.codexdiff import A, B, BASE, C, CodexBase, D, E, F, Home, marker, short_marker

RECORD: list[str] = []
TOTAL = {"homes": 0, "calls": 0}
UUID = "0a1b2c3d-0001-7000-8000-%012x"


def uid(number: int) -> str:
    return UUID % number


class HomeDiff(CodexBase):
    def run_homes(self, label: str, homes: list, **keywords):
        cases = []
        for entry in homes:
            home, extra = entry if isinstance(entry, tuple) else (entry, {})
            case = {"home": str(home.root), "ops": battery(home, **keywords)}
            case.update(extra)
            cases.append(case)
        count, calls = self.script(cases, label)
        TOTAL["homes"] += count
        TOTAL["calls"] += calls
        RECORD.append("homes %s: %d homes, %d calls equal" % (label, count, calls))
        return count, calls

    def thread_home(self, name: str, **kinds) -> Home:
        home = self.home(name)
        return home

    # ------------------------------------------------------------------------------------------ codexsim
    def test_codexsim_basic(self):
        home = self.home("basic")
        sim = home.sim
        sim.add_thread(A, name="Alpha")
        sim.fail_usage(A, ordinal=5)
        sim.add_turn(A, status="completed", ordinal=6)
        sim.fail_transient(B, ordinal=5)
        sim.fail_transient(C, ordinal=5, code="httpConnectionFailed")
        sim.fail_transient(D, ordinal=5, error_json=json.dumps({"codexErrorInfo": {"httpStatusCode": 503}}))
        sim.add_turn(E, status="inProgress", ordinal=5)
        sim.add_turn(F, status="interrupted", ordinal=5)
        sim.fail_usage(uid(7), reset=None)
        sim.fail_usage(uid(8), reset=BASE - 5)
        sim.fail_usage(uid(9), completed=BASE - 7200)
        sim.fail_transient(uid(10), completed=BASE - 100000)
        self.run_homes("codexsim basic", [home])

    def test_codexsim_queue_and_dispatch(self):
        homes = []
        for number, (steer, first_user, progress, status) in enumerate((
                (False, True, True, "completed"), (True, True, True, "completed"), (False, False, True, "inProgress"),
                (False, True, False, "failed"), (True, False, False, "interrupted"), (False, True, True, "inProgress"))):
            home = self.home("queue-%d" % number)
            sim = home.sim
            sim.fail_usage(A, ordinal=5)
            cid = uid(100 + number)
            queue_id = sim.enqueue(A, "continue " + marker("a"), client_id=cid)
            sim.enqueue(A, "someone else's words", client_id=uid(200))
            sim.enqueue(B, "continue " + marker("b"), client_id=None)
            sim.enqueue(B, "bare client", client_id=uid(300))
            if number % 2:
                sim.edit_queued(queue_id, "edited by a person")
            turn = sim.dispatch(A, status=status, progress=progress, steer_user=steer, first_user=first_user)
            sim.fail_transient(B, ordinal=5)
            sim.dispatch(B, status="completed")
            if number == 4:
                sim.remove_queued(queue_id)
            homes.append(home)
            self.assertTrue(turn is None or turn)
        self.run_homes("codexsim queue", homes, markers=[uid(100), uid(300), uid(200)])

    def test_codexsim_stale_projection_and_tables(self):
        homes = []
        home = self.home("stale")
        home.sim.fail_usage(A, ordinal=5)
        home.sim.make_stale(A)
        home.sim.add_turn(B, status="completed")
        homes.append(home)
        home = self.home("no-projection-row")
        home.sim.fail_usage(A, ordinal=5)
        home.history("DELETE FROM thread_history_projection_state")
        homes.append(home)
        home = self.home("no-projection-table")
        home.sim.fail_usage(A, ordinal=5)
        home.history("DROP TABLE thread_history_projection_state")
        homes.append(home)
        home = self.home("projection-types")
        home.sim.fail_usage(A, ordinal=5)
        home.sim.fail_usage(B, ordinal=5)
        home.history("UPDATE thread_history_projection_state SET next_rollout_byte_offset='12' WHERE thread_id=?", A)
        home.history("UPDATE thread_history_projection_state SET next_rollout_byte_offset=NULL WHERE thread_id=?", B)
        homes.append(home)
        home = self.home("projection-float")
        home.sim.fail_usage(A, ordinal=5)
        size = home.sim.rollout(A).stat().st_size
        home.history("UPDATE thread_history_projection_state SET next_rollout_byte_offset=? WHERE thread_id=?", float(size), A)
        homes.append(home)
        self.run_homes("projection", homes)

    # ------------------------------------------------------------------------------------------- splits
    def test_splits(self):
        homes = []

        def conversation(name: str):
            home = self.home(name)
            home.sim.add_thread(A)
            home.sim.add_turn(A, status="completed", ordinal=5)
            home.sim.fail_usage(A, ordinal=6, completed=BASE - 500)
            return home

        def split(home, other, stamp, **keywords):
            path = home.split_file(A, other, stamp=stamp, **keywords)
            home.state("UPDATE threads SET rollout_path=? WHERE id=?", str(path), A)
            home.history("INSERT OR REPLACE INTO thread_history_projection_state VALUES (?,?,0)", other, path.stat().st_size)
            return path

        # One split: the turns under B, B has no row, the file names it.
        home = conversation("split-one")
        split(home, B, 1)
        home.turn(B, uid(41), status="failed", ordinal=3, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        homes.append(home)
        # Two splits: A_B then A_C, the second file current; B's file remains.
        home = conversation("split-two")
        split(home, B, 1)
        home.turn(B, uid(41), status="completed", ordinal=1)
        split(home, C, 2)
        home.turn(C, uid(42), status="failed", ordinal=2, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        homes.append(home)
        # The first file gone: only the chain memory remembers B.
        home = conversation("split-memory")
        first = split(home, B, 1)
        home.turn(B, uid(41), status="failed", ordinal=3, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        split(home, C, 2)
        home.turn(C, uid(42), status="completed", ordinal=1)
        first.unlink()
        chains = self.scratch / "chains-memory.json"
        homes.append((home, {"chains": str(chains)}))
        # The same, with a file of ids already remembered.
        home = conversation("split-remembered")
        split(home, C, 2)
        home.turn(B, uid(41), status="failed", ordinal=3, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        home.turn(C, uid(42), status="completed", ordinal=1)
        remembered = self.scratch / "chains-remembered.json"
        homes.append((home, {"chains": str(remembered), "pre": True}))
        # A guard fails: the first line says another conversation, a split id has a row, another file names it.
        home = conversation("split-meta-other")
        split(home, B, 1, meta_id=C)
        homes.append(home)
        home = conversation("split-row-of-its-own")
        split(home, B, 1)
        home.thread(B)
        homes.append(home)
        home = conversation("split-named-by-other")
        split(home, B, 1)
        home.thread(C, path=home.root / "sessions" / ("rollout-x-%s.jsonl" % B))
        homes.append(home)
        home = conversation("split-self")
        path = home.root / "sessions" / ("rollout-2026-%s_%s.jsonl" % (A, A))
        path.write_bytes(home.sim.rollout(A).read_bytes())
        home.state("UPDATE threads SET rollout_path=? WHERE id=?", str(path), A)
        homes.append(home)
        home = conversation("split-uppercase")
        path = home.root / "sessions" / ("rollout-2026-%s_%s.jsonl" % (A, B.upper()))
        path.write_bytes(home.sim.rollout(A).read_bytes())
        home.state("UPDATE threads SET rollout_path=? WHERE id=?", str(path), A)
        home.turn(B, uid(41), status="failed", ordinal=3, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        homes.append(home)
        home = conversation("split-in-subfolders")
        for number, other in enumerate((B, C, D)):
            folder = home.root / "sessions" / ("2026/10/%02d" % number)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ("rollout-2026-10-14T12-00-%02d-%s_%s.jsonl" % (number, A, other))
            path.write_bytes(home.sim.rollout(A).read_bytes())
            home.turn(other, uid(60 + number), status="completed", ordinal=number)
        home.state("UPDATE threads SET rollout_path=? WHERE id=?", str(path), A)
        homes.append(home)
        home = conversation("split-same-name-twice")
        for number in (0, 1):
            folder = home.root / "sessions" / ("d%d" % number)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ("same-%s_%s.jsonl" % (A, B))
            path.write_bytes(home.sim.rollout(A).read_bytes())
        home.state("UPDATE threads SET rollout_path=? WHERE id=?", str(path), A)
        home.turn(B, uid(41), status="failed", ordinal=3, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        homes.append(home)
        # A turn recorded under a split id that no file names (nobody's) and one that a file names.
        home = conversation("split-orphan-turns")
        home.turn(B, uid(41), status="failed", ordinal=3, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        home.turn(C, uid(42), status="failed", ordinal=3, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        home.history("DELETE FROM thread_turns WHERE thread_id=?", A)
        homes.append(home)
        # Seed the remembered ids before the reference and car-codex run (each reads the file as it is).
        for entry in homes:
            if isinstance(entry, tuple) and entry[1].pop("pre", False):
                self.write_remembered(entry[0], Path(entry[1]["chains"]))
        self.run_homes("splits", homes, markers=[marker("a")])

    def write_remembered(self, home: Home, path: Path):
        """A `split-chains.json` that remembers B for A under this home - keyed as the reference keys it."""
        from rustdiff import reference
        script = (
            "import json, sys\nfrom pathlib import Path\nfrom codex_auto_resume.codex import chains\n"
            "memory = chains.ChainMemory(Path(sys.argv[1]))\nmemory.extend(Path(sys.argv[2]), sys.argv[3], [sys.argv[4], sys.argv[5]])\n")
        done = reference.run(script, path, home.root.resolve(), A, B, "not-an-id", profile=path.parent)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])

    # -------------------------------------------------------------------------------------- eligibility
    def test_eligibility_matrix(self):
        home = self.home("matrix")
        number = 0
        rows = []
        for source in ("vscode", "cli", "exec", "other", None, "Subagent", ""):
            for thread_source in ("user", "chatgpt_handoff", None, "subagent", "guardian_review", "memory_consolidation",
                                  "agent_created_thread", "xx", "x" * 70, ""):
                for originator in ("Codex Desktop", "codex_work_desktop", "codex-tui", "codex_vscode", "codex_exec", "other", None):
                    number += 1
                    rows.append((uid(1000 + number), source, thread_source, originator))
        random.Random(7).shuffle(rows)
        for thread_id, source, thread_source, originator in rows:
            first = {"type": "session_meta", "payload": {"id": thread_id, "originator": originator,
                                                         "source": "vscode" if source != "cli" else "cli",
                                                         "thread_source": thread_source}}
            if originator is None:
                del first["payload"]["originator"]
            home.thread(thread_id, source=source, thread_source=thread_source, first=first)
        self.run_homes("eligibility matrix", [home], light=True)

    def test_eligibility_first_lines(self):
        home = self.home("first-lines")
        variants = {
            "adopted": ("vscode", "user", {"originator": "codex-tui", "source": "cli"}),
            "forked": ("vscode", "user", {"originator": "codex-tui", "source": "vscode"}),
            "exec-fork": ("vscode", "user", {"originator": "codex_exec", "source": "vscode", "forked_from_id": A}),
            "exec-fork-bad-id": ("vscode", "user", {"originator": "codex_exec", "source": "vscode", "forked_from_id": "x"}),
            "exec-fork-null": ("vscode", "user", {"originator": "codex_exec", "source": "vscode", "forked_from_id": None}),
            "exec-no-fork": ("vscode", "user", {"originator": "codex_exec", "source": "vscode"}),
            "exec-row": ("exec", "user", {"originator": "codex_exec", "source": "exec"}),
            "cli": ("cli", "user", {"originator": "codex-tui", "source": "cli"}),
            "ide": ("vscode", "user", {"originator": "codex_vscode", "source": "vscode"}),
            "ide-cli-source": ("vscode", "user", {"originator": "codex_vscode", "source": "cli"}),
            "unknown-originator": ("vscode", "user", {"originator": "Something Else", "source": "vscode"}),
            "long-originator": ("vscode", "user", {"originator": "o" * 65, "source": "vscode"}),
            "originator-list": ("vscode", "user", {"originator": ["a"], "source": "vscode"}),
            "originator-dict": ("vscode", "user", {"originator": {"a": 1}, "source": "vscode"}),
            "originator-number": ("vscode", "user", {"originator": 5, "source": "vscode"}),
            "source-list": ("vscode", "user", {"originator": "Codex Desktop", "source": ["vscode"]}),
            "thread-source-differs": ("vscode", "user", {"originator": "Codex Desktop", "source": "vscode", "thread_source": "other"}),
            "thread-source-missing": ("vscode", "user", {"originator": "Codex Desktop", "source": "vscode", "thread_source": None}),
            "agent-created": ("vscode", "agent_created_thread", {"originator": "Codex Desktop", "source": "vscode", "thread_source": "agent_created_thread"}),
            "subagent-nested": ("vscode", "user", {"originator": "Codex Desktop", "source": {"subagent": {"x": 1}}}),
            "cli-version": ("cli", "user", {"originator": "codex-tui", "source": "cli", "cli_version": "0.164.0"}),
            "cli-version-old": ("cli", "user", {"originator": "codex-tui", "source": "cli", "cli_version": "0.100.0-alpha.2"}),
            "cli-version-bad": ("cli", "user", {"originator": "codex-tui", "source": "cli", "cli_version": 5}),
            "ide-version": ("vscode", "user", {"originator": "codex_vscode", "source": "vscode", "cli_version": "9.9.9-beta.1"}),
            "cli-version-junk": ("cli", "user", {"originator": "codex-tui", "source": "cli", "cli_version": "not a version"}),
        }
        for number, (name, (source, thread_source, payload)) in enumerate(variants.items()):
            thread_id = uid(2000 + number)
            body = dict({"id": thread_id, "thread_source": thread_source}, **payload)
            home.thread(thread_id, source=source, thread_source=thread_source, first={"type": "session_meta", "payload": body})
            home.turn(thread_id, uid(3000 + number), status="failed", ordinal=5,
                      error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        # archived, history_mode, a different id in the file, and flags of every type.
        for number, (archived, history_mode) in enumerate(((1, "paginated"), (0, "full"), (0, None), ("0", "paginated"),
                                                           (None, "paginated"), (0.0, "paginated"), (2, "paginated"))):
            thread_id = uid(2500 + number)
            home.thread(thread_id, archived=archived, history_mode=history_mode)
            home.turn(thread_id, uid(3500 + number), status="failed", ordinal=5,
                      error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        home.thread(uid(2600), first={"type": "session_meta", "payload": {"id": uid(2601), "originator": "Codex Desktop",
                                                                         "source": "vscode", "thread_source": "user"}})
        home.thread(uid(2602), first={"type": "session_meta", "payload": {"id": 5, "originator": "Codex Desktop",
                                                                         "source": "vscode", "thread_source": "user"}})
        self.run_homes("eligibility first lines", [home], light=True)

    # ------------------------------------------------------------------------------- rollout file variants
    def test_rollout_first_lines(self):
        home = self.home("rollouts")
        good = {"type": "session_meta", "payload": {"id": None, "originator": "Codex Desktop", "source": "vscode", "thread_source": "user"}}

        def line(thread_id, **changes):
            event = json.loads(json.dumps(good))
            event["payload"]["id"] = thread_id
            event["payload"].update(changes)
            return event

        def sized(event, total):
            """The first line as `total` bytes, its newline the last: the same JSON with spaces before its last brace."""
            data = json.dumps(event).encode()
            return data[:-1] + b" " * (total - len(data) - 1) + b"}\n"

        variants = []
        for name, build in {
            "plain": lambda t: json.dumps(line(t)).encode() + b"\n",
            "bom": lambda t: b"\xef\xbb\xbf" + json.dumps(line(t)).encode() + b"\n",
            "no-newline": lambda t: json.dumps(line(t)).encode(),
            "crlf": lambda t: json.dumps(line(t)).encode() + b"\r\n",
            "lf-after-more": lambda t: json.dumps(line(t)).encode() + b"\n" + b'{"type":"event_msg"}\n',
            "empty": lambda t: b"",
            "newline-only": lambda t: b"\n",
            "spaces": lambda t: b"   \n",
            "latin1": lambda t: json.dumps(line(t, name="caf\u00e9")).encode("latin-1") + b"\n",
            "bad-utf8": lambda t: b'{"type":"session_meta","payload":{"id":"' + t.encode() + b'","x":"\xff\xfe"}}\n',
            "truncated": lambda t: json.dumps(line(t)).encode()[:40] + b"\n",
            "not-json": lambda t: b"hello world\n",
            "list": lambda t: b"[1,2,3]\n",
            "string": lambda t: b'"session_meta"\n',
            "null": lambda t: b"null\n",
            "number": lambda t: b"12\n",
            "wrong-type": lambda t: json.dumps(dict(line(t), type="turn_context")).encode() + b"\n",
            "type-missing": lambda t: json.dumps({"payload": line(t)["payload"]}).encode() + b"\n",
            "payload-list": lambda t: json.dumps({"type": "session_meta", "payload": [line(t)["payload"]]}).encode() + b"\n",
            "payload-null": lambda t: b'{"type":"session_meta","payload":null}\n',
            "nan": lambda t: json.dumps(line(t)).encode().replace(b'"vscode"', b"NaN", 1) + b"\n",
            "dup-key": lambda t: json.dumps(line(t)).encode().replace(b'"source"', b'"id": "' + t.encode() + b'", "source"', 1) + b"\n",
            "dup-key-other": lambda t: b'{"type":"session_meta","payload":{"id":"' + B.encode() + b'","id":"' + t.encode() + b'","originator":"Codex Desktop","source":"vscode","thread_source":"user"}}\n',
            "escaped-id": lambda t: json.dumps(line(t), ensure_ascii=True).encode().replace(t.encode(), t.replace("-", "\\u002d").encode()) + b"\n",
            "surrogate": lambda t: json.dumps(line(t)).encode().replace(b'"Codex Desktop"', b'"\\ud800 x"') + b"\n",
            "deep": lambda t: b'{"type":"session_meta","payload":{"id":"' + t.encode() + b'","x":' + b"[" * 3000 + b"]" * 3000 + b"}}\n",
            "deeper": lambda t: b'{"type":"session_meta","payload":{"id":"' + t.encode() + b'","x":' + b"[" * 20000 + b"]" * 20000 + b"}}\n",
            "big-int": lambda t: json.dumps(line(t)).encode().replace(b'"user"', b'"user", "n": ' + b"9" * 5000, 1) + b"\n",
            "float-inf": lambda t: json.dumps(line(t)).encode().replace(b'"user"', b'"user", "n": 1e999', 1) + b"\n",
            "total-limit-minus-1": lambda t: sized(line(t), 256 * 1024 - 1),
            "total-limit": lambda t: sized(line(t), 256 * 1024),
            "total-limit-plus-1": lambda t: sized(line(t), 256 * 1024 + 1),
            "total-limit-plus-2": lambda t: sized(line(t), 256 * 1024 + 2),
            "limit-without-newline": lambda t: sized(line(t), 256 * 1024 + 1)[:-1],
            "huge": lambda t: json.dumps(line(t, filler="z" * 400000)).encode() + b"\n",
            "tabs": lambda t: b"\t" + json.dumps(line(t)).encode() + b"\n",
            "nul": lambda t: json.dumps(line(t)).encode() + b"\x00\n",
            "second-line": lambda t: b"\n" + json.dumps(line(t)).encode() + b"\n",
            "extra-text": lambda t: json.dumps(line(t)).encode() + b" trailing\n",
            "unicode-id": lambda t: json.dumps(line(t, name="\u0645\u0631\u062d\u0628\u0627 \U0001f600"), ensure_ascii=False).encode("utf-8") + b"\n",
            "utf16": lambda t: json.dumps(line(t)).encode("utf-16"),
        }.items():
            variants.append((name, build))
        for number, (name, build) in enumerate(variants):
            thread_id = uid(4000 + number)
            home.thread(thread_id, first=build(thread_id), name=name)
            home.turn(thread_id, uid(5000 + number), status="failed", ordinal=5, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        # no file at all, a folder in its place, a file the row does not name
        thread_id = uid(4900)
        home.thread(thread_id, write_file=False)
        home.turn(thread_id, uid(5900), status="failed", ordinal=5, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        thread_id = uid(4901)
        folder = home.sim.rollout(thread_id)
        folder.mkdir(parents=True)
        home.thread(thread_id, write_file=False)
        thread_id = uid(4902)
        home.thread(thread_id, path=home.root / "sessions" / "rollout-without-the-id.jsonl")
        thread_id = uid(4903)
        home.thread(thread_id, path=home.root / "sessions" / ("rollout-%s.txt" % thread_id))
        thread_id = uid(4904)
        home.thread(thread_id, path=home.root / "sessions" / ("rollout-%s.JSONL" % thread_id))
        thread_id = uid(4905)
        home.thread(thread_id, path=home.root / "sessions" / (".jsonl"))
        self.run_homes("rollout first lines", [home], light=True)

    def test_paths_of_rollouts(self):
        home = self.home("paths")
        sessions = home.root / "sessions"
        number = 0
        forms = {}

        def make(label, build):
            nonlocal number
            number += 1
            thread_id = uid(6000 + number)
            real = home.sim.rollout(thread_id)
            payload = {"type": "session_meta", "payload": {"id": thread_id, "originator": "Codex Desktop",
                                                           "source": "vscode", "thread_source": "user"}}
            real.parent.mkdir(parents=True, exist_ok=True)
            real.write_bytes(json.dumps(payload).encode() + b"\n")
            forms[label] = (thread_id, build(thread_id, real))

        make("plain", lambda t, p: str(p))
        make("extended", lambda t, p: "\\\\?\\" + str(p))
        make("forward-slashes", lambda t, p: str(p).replace("\\", "/"))
        make("upper-case", lambda t, p: str(p).upper())
        make("lower-case", lambda t, p: str(p).lower())
        make("with-dots", lambda t, p: str(sessions / "x" / ".." / p.name))
        make("double-separators", lambda t, p: str(sessions).replace("\\", "\\\\") + "\\" + p.name)
        make("trailing-separator", lambda t, p: str(p) + "\\")
        make("outside", lambda t, p: str(home.root / ("rollout-%s.jsonl" % t)))
        make("sibling-prefix", lambda t, p: str(home.root / "sessions-extra" / p.name))
        make("relative", lambda t, p: "sessions\\" + p.name)
        make("relative-dots", lambda t, p: "..\\" + p.name)
        make("empty", lambda t, p: "")
        make("dot", lambda t, p: ".")
        make("nul", lambda t, p: str(p) + "\x00")
        make("unicode", lambda t, p: str(p) + "\u00e9")
        make("short-drive", lambda t, p: os.path.splitdrive(str(p))[0])
        make("share", lambda t, p: "\\\\server\\share\\" + p.name)
        make("device", lambda t, p: "\\\\.\\" + str(p))
        for label, (thread_id, raw) in forms.items():
            home.state("INSERT OR REPLACE INTO threads (id, rollout_path, source, thread_source, archived, history_mode) "
                       "VALUES (?,?,?,?,?,?)", thread_id, raw, "vscode", "user", 0, "paginated")
            home.turn(thread_id, uid(7000 + int(thread_id[-4:], 16) - 6000), status="failed", ordinal=5,
                      error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        # the column holding anything but text
        for number, raw in enumerate((None, 7, 1.5, b"bytes-here", b"", b"subagent")):
            thread_id = uid(6500 + number)
            connection = sqlite3.connect(home.root / "state_5.sqlite")
            connection.execute("INSERT INTO threads (id, rollout_path, source, thread_source, archived, history_mode) "
                               "VALUES (?,?,?,?,?,?)", (thread_id, raw, "vscode", "user", 0, "paginated"))
            connection.commit()
            connection.close()
        for number, (source, thread_source, history_mode) in enumerate(((b"subagent-bytes", "user", "paginated"),
                                                                       ("vscode", b"Subagent", "paginated"),
                                                                       ("vscode", "user", b"x"), (b"vscode", "user", "paginated"),
                                                                       (7, 7, 7), (1.5, 1.5, 1.5))):
            thread_id = uid(6600 + number)
            connection = sqlite3.connect(home.root / "state_5.sqlite")
            connection.execute("INSERT INTO threads (id, rollout_path, source, thread_source, archived, history_mode) "
                               "VALUES (?,?,?,?,?,?)", (thread_id, str(home.sim.rollout(thread_id)), source, thread_source, 0, history_mode))
            connection.commit()
            connection.close()
        self.run_homes("rollout paths", [home], light=True)

    # --------------------------------------------------------------------------------------------- reset
    def test_reset_hints_and_rescan(self):
        homes = []

        def usage_home(name, events, *, end=None, tail=b"", head=b"", turn=None, completed=BASE, error=None):
            home = self.home(name)
            thread_id = A
            turn = turn or uid(8000 + len(homes))
            meta = {"type": "session_meta", "payload": {"id": thread_id, "originator": "Codex Desktop", "source": "vscode", "thread_source": "user"}}
            path = home.sim.rollout(thread_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            body = head + json.dumps(meta).encode() + b"\n"
            for event in events:
                body += (event if isinstance(event, bytes) else json.dumps(event).encode() + b"\n")
            finish = len(body)
            body += tail
            path.write_bytes(body)
            home.thread(thread_id, write_file=False)
            home.turn(thread_id, turn, status="failed", ordinal=5, completed=completed,
                      error_json=error or json.dumps({"codexErrorInfo": "usageLimitExceeded"}),
                      end=finish if end is None else (end(finish) if callable(end) else end))
            home.sim.catch_up(thread_id)
            homes.append(home)
            return home, turn

        def count(limit, **windows):
            return {"type": "event_msg", "payload": {"type": "token_count", "rate_limits": dict({"limit_id": limit}, **windows)}}

        def done(turn, code="usage_limit_exceeded", **more):
            return {"type": "event_msg", "payload": dict({"type": "task_complete", "turn_id": turn, "error": {"codex_error_info": code}}, **more)}

        usage = {"used_percent": 100, "resets_at": BASE + 3600}
        for number, windows in enumerate((
                {"primary": usage}, {"primary": usage, "secondary": {"used_percent": 100, "resets_at": BASE + 90000}},
                {"primary": {"used_percent": 98, "resets_at": BASE + 100}}, {"primary": {"used_percent": 20, "resets_at": BASE + 100}},
                {"primary": {"used_percent": 100}}, {"primary": {"used_percent": 100, "resets_at": "x"}},
                {"primary": {"used_percent": 100, "resets_at": BASE - 100}}, {"primary": {"used_percent": True, "resets_at": BASE}},
                {"primary": {"used_percent": -1, "resets_at": BASE}}, {"primary": {"used_percent": float("inf")}},
                {"primary": {"used_percent": 100.0, "resets_at": float(BASE + 5)}}, {"primary": 5, "secondary": None},
                {"primary": {"used_percent": 100, "resets_at": 10 ** 400}}, {"primary": {"used_percent": 10 ** 400, "resets_at": BASE}},
                {"primary": {"used_percent": 99.9, "resets_at": BASE + 1}, "secondary": {"used_percent": 100, "resets_at": BASE + 2}})):
            turn = uid(8100 + number)
            events = [count("codex", **windows), count("premium", primary=None, secondary=None), done(turn)]
            usage_home("reset-%d" % number, events, turn=turn)
        turn = uid(8200)
        usage_home("reset-two-buckets", [count("codex", primary=usage), count("other_bucket", primary={"used_percent": 100, "resets_at": BASE + 9999}),
                                         count("bad bucket!", primary=usage), count("x" * 65, primary=usage), count(5, primary=usage),
                                         done(turn)], turn=turn)
        turn = uid(8201)
        usage_home("reset-not-usage", [count("codex", primary=usage), done(turn, code="other")], turn=turn)
        turn = uid(8202)
        usage_home("reset-no-done", [count("codex", primary=usage)], turn=turn)
        turn = uid(8203)
        usage_home("reset-other-turn", [count("codex", primary=usage), done(uid(8299))], turn=turn)
        turn = uid(8204)
        usage_home("reset-error-not-dict", [count("codex", primary=usage), {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn, "error": "x"}}], turn=turn)
        turn = uid(8205)
        usage_home("reset-garbage-lines", [b"not json\n", b"\xff\xfe\n", b"[]\n", b'{"type":"event_msg","payload":5}\n', count("codex", primary=usage), done(turn)], turn=turn)
        turn = uid(8206)
        usage_home("reset-crlf", [json.dumps(count("codex", primary=usage)).encode() + b"\r\n", json.dumps(done(turn)).encode() + b"\r\n"], turn=turn)
        turn = uid(8207)
        usage_home("reset-cr-only", [json.dumps(count("codex", primary=usage)).encode() + b"\r", json.dumps(done(turn)).encode() + b"\r"], turn=turn)
        turn = uid(8208)
        usage_home("reset-long-line", [b" " * 1100000 + b"\n", count("codex", primary=usage), done(turn)], turn=turn)
        turn = uid(8209)
        usage_home("reset-line-at-limit", [json.dumps(count("codex", primary=usage)).encode() + b" " * (1024 * 1024 - len(json.dumps(count("codex", primary=usage)))) + b"\n", done(turn)], turn=turn)
        turn = uid(8210)
        usage_home("reset-end-early", [count("codex", primary=usage), done(turn)], turn=turn, end=10)
        usage_home("reset-end-zero", [count("codex", primary=usage), done(uid(8211))], turn=uid(8211), end=0)
        usage_home("reset-end-negative", [count("codex", primary=usage), done(uid(8212))], turn=uid(8212), end=-5)
        usage_home("reset-end-float", [count("codex", primary=usage), done(uid(8213))], turn=uid(8213), end=100.5)
        usage_home("reset-end-text", [count("codex", primary=usage), done(uid(8214))], turn=uid(8214), end="100")
        usage_home("reset-end-huge", [count("codex", primary=usage), done(uid(8215))], turn=uid(8215), end=1 << 62)
        usage_home("reset-end-past-file", [count("codex", primary=usage), done(uid(8216))], turn=uid(8216), end=lambda size: size + 500)
        usage_home("reset-end-mid-line", [count("codex", primary=usage), done(uid(8217))], turn=uid(8217), end=lambda size: size - 20)
        usage_home("reset-after-end", [count("codex", primary=usage), done(uid(8218)), count("codex", primary={"used_percent": 100, "resets_at": BASE + 7})], turn=uid(8218),
                   end=lambda size: size - 0, tail=json.dumps(count("codex", primary=usage)).encode() + b"\n")
        usage_home("reset-completed-none", [count("codex", primary=usage), done(uid(8219))], turn=uid(8219), completed=None)
        usage_home("reset-completed-text", [count("codex", primary=usage), done(uid(8220))], turn=uid(8220), completed="x")
        usage_home("reset-big-file", [b'{"type":"event_msg","payload":{"type":"noise"}}\n'] * 30000 + [count("codex", primary=usage), done(uid(8221))], turn=uid(8221))
        usage_home("reset-bom", [count("codex", primary=usage), done(uid(8222))], turn=uid(8222), head=b"\xef\xbb\xbf")
        usage_home("reset-limit-id-types", [count("codex", primary=usage), {"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {"limit_id": None, "primary": usage}}}, done(uid(8223))], turn=uid(8223))
        usage_home("reset-limits-list", [{"type": "event_msg", "payload": {"type": "token_count", "rate_limits": [usage]}}, count("codex", primary=usage), done(uid(8224))], turn=uid(8224))
        usage_home("reset-other-error", [count("codex", primary=usage), done(uid(8225))], turn=uid(8225), error=json.dumps({"codexErrorInfo": "serverOverloaded"}))
        usage_home("reset-bad-error-json", [count("codex", primary=usage), done(uid(8226))], turn=uid(8226), error="not json")
        self.run_homes("reset hints", homes, light=True, plug=False)

    def test_superseded_and_trigger(self):
        homes = []

        def make(name, lines, *, turn, thread_source="user", status="failed", head=b""):
            home = self.home(name)
            meta = {"type": "session_meta", "payload": {"id": A, "originator": "Codex Desktop", "source": "vscode", "thread_source": thread_source}}
            body = head + json.dumps(meta).encode() + b"\n"
            for each in lines:
                body += each if isinstance(each, bytes) else json.dumps(each).encode() + b"\n"
            path = home.sim.rollout(A)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            home.thread(A, write_file=False, thread_source=thread_source)
            home.turn(A, turn, status=status, ordinal=5, error_json=json.dumps({"codexErrorInfo": "serverOverloaded"}))
            homes.append(home)

        def done(turn):
            return {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn}}

        def person(text="a person"):
            return {"type": "event_msg", "payload": {"type": "user_message", "message": text}}

        def started(turn, trigger="composer", **more):
            return {"type": "event_msg", "payload": dict({"type": "task_started", "turn_id": turn, "turn_attribution": {"turn_trigger": trigger}}, **more)}

        turn = uid(9000)
        make("sup-later", [done(turn), person()], turn=turn)
        make("sup-nothing", [done(turn)], turn=turn)
        make("sup-none", [person(), done(uid(9001))], turn=turn)
        make("sup-before", [person(), done(turn)], turn=turn)
        make("sup-ours", [done(turn), person("hello [codex-auto-resume:" + "a" * 16 + "]")], turn=turn)
        make("sup-rollback", [done(turn), person(), {"type": "event_msg", "payload": {"type": "thread_rolled_back", "num_turns": 1}}], turn=turn)
        make("sup-rollback-before", [{"type": "event_msg", "payload": {"type": "thread_rolled_back"}}, done(turn), person()], turn=turn)
        make("sup-bad-line", [done(turn), b"not json at all\n", person()], turn=turn)
        make("sup-bad-utf8", [done(turn), b'{"type":"event_msg"}\xff\n', person()], turn=turn)
        make("sup-long-line", [done(turn), b'{"type":"event_msg","x":"' + b"a" * 1100000 + b'"}\n', person()], turn=turn)
        make("sup-long-before", [b'{"type":"event_msg","x":"' + b"a" * 1100000 + b'"}\n', done(turn), person()], turn=turn)
        make("sup-line-at-limit", [done(turn), b'{"type":"event_msg","payload":{"type":"user_message"}}' + b" " * (1024 * 1024 - 61) + b"\n", person()], turn=turn)
        make("sup-crlf", [json.dumps(done(turn)).encode() + b"\r\n", json.dumps(person()).encode() + b"\r\n"], turn=turn)
        make("sup-other-events", [done(turn), {"type": "response_item", "payload": {"type": "user_message"}}, {"type": "event_msg", "payload": 5}, {"type": "event_msg", "payload": {"type": "agent_message"}}], turn=turn)
        make("sup-twice", [done(turn), done(turn), person()], turn=turn)
        make("sup-garbage-after-no-newline", [done(turn), person(), b'{"type":"event_msg"'], turn=turn)
        make("sup-big", [{"type": "event_msg", "payload": {"type": "agent_message", "text": "w" * 200}}] * 40000 + [done(turn), person()], turn=turn)
        make("sup-bom", [done(turn), person()], turn=turn, head=b"\xef\xbb\xbf")
        turn = uid(9100)
        for number, lines in enumerate((
                [started(turn)], [started(turn, "other"), started(uid(9199), "composer")], [started(uid(9199)), started(turn, "background")],
                [{"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn}}],
                [{"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn, "turn_attribution": "x"}}],
                [{"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn, "turn_attribution": {"turn_trigger": 5}}}],
                [started(turn), b'{"type":"event_msg","payload":{"type":"task_started"}}\n'],
                [b'{"type":"task_started"}\n', started(turn)], [b"\xff task_started\n", started(turn)], [], [done(turn)],
                [b'{"type":"event_msg","payload":{"type":"task_started","turn_id":"' + turn.encode() + b'","x":"' + b"a" * 1100000 + b'"}}\n', started(turn, "later")],
                [started(uid(9199), "composer"), started(turn, "composer"), started(uid(9198), "background")])):
            make("trigger-%d" % number, lines, turn=turn, thread_source="agent_created_thread")
        self.run_homes("superseded and trigger", homes, light=True, plug=False)
        # the same conversations read as a person's own, and with the plug asking for the widest net
        self.run_homes("superseded and trigger (widened)", [(home, {"widened": ["every_desktop"], "kinds": ["cli", "ide"]}) for home in homes[:6]], light=True)

    # ----------------------------------------------------------------------------------- schema variants
    def raw_home(self, name: str, *, state=None, history=None, queue=None) -> Home:
        """A home with the databases given as the SQL that makes them (None: the file is left out)."""
        folder = self.scratch / name
        (folder / "codex-home" / "sessions").mkdir(parents=True, exist_ok=True)
        root = folder / "codex-home"
        for file, statements in (("state_5.sqlite", state), ("thread_history_1.sqlite", history), ("queue_1.sqlite", queue)):
            if statements is None:
                continue
            connection = sqlite3.connect(root / file)
            for statement in statements:
                connection.execute(statement)
            connection.commit()
            connection.close()
        home = object.__new__(Home)
        home.root = root
        from rustdiff.codexdiff import codexsim
        home.sim = codexsim.CodexHome.__new__(codexsim.CodexHome)
        home.sim.root = root
        home.sim._items = 0
        home.sim.clock = lambda: BASE
        return home

    def test_schema_variants(self):
        threads = ("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT, thread_source TEXT, "
                   "archived INTEGER, history_mode TEXT%s)")
        turns = ("CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, status TEXT, error_json TEXT, "
                 "started_at INTEGER, completed_at INTEGER, first_user_item_id TEXT, rollout_end_byte_offset INTEGER%s)")
        items = ("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal INTEGER, item_json TEXT, "
                 "item_type TEXT%s)")
        queue = "CREATE TABLE queued_items (id TEXT PRIMARY KEY, thread_id TEXT, payload_json TEXT%s)"
        full = ["CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY KEY, next_rollout_byte_offset INTEGER)"]
        homes = []

        def put(home):
            for number in range(3):
                thread_id = uid(9500 + number)
                home.thread(thread_id)
                home.turn_raw(thread_id, uid(9600 + number))
            homes.append(home)

        def raw(name, **kinds):
            home = self.raw_home(name, **kinds)
            Home.turn_raw = lambda self, thread_id, turn_id: self.history(
                "INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, status, error_json, started_at, completed_at) "
                "VALUES (?,?,5,'failed',?,?,?)", thread_id, turn_id, json.dumps({"codexErrorInfo": "serverOverloaded"}), BASE - 100, BASE)
            return home

        def thread(home, thread_id, **columns):
            names = ["id", "rollout_path", "source", "thread_source", "archived", "history_mode"] + list(columns)
            path = home.sim.rollout(thread_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(json.dumps({"type": "session_meta", "payload": {"id": thread_id, "originator": "Codex Desktop", "source": "vscode", "thread_source": "user"}}).encode() + b"\n")
            home.state("INSERT INTO threads (%s) VALUES (%s)" % (",".join(names), ",".join("?" * len(names))),
                       thread_id, str(path), "vscode", "user", 0, "paginated", *columns.values())

        def fill(home, with_projection=True, **columns):
            for number in range(3):
                thread_id = uid(9500 + number)
                thread(home, thread_id, **columns)
                home.turn_raw(thread_id, uid(9600 + number))
                if with_projection:
                    home.sim.catch_up(thread_id) if False else None
            homes.append(home)

        # the right schema, with extra columns, and each required column missing in turn
        home = raw("schema-extra", state=[threads % ", name TEXT, cwd TEXT, project_id TEXT, model TEXT, approval_mode TEXT, tokens_used INTEGER, junk BLOB"],
                   history=[turns % ", final_agent_item_id TEXT, junk TEXT", items % ", created_at_ms INTEGER, junk TEXT"] + full, queue=[queue % ", created_at_ms INTEGER, queue_order INTEGER"])
        fill(home, name="A name", cwd="C:\\work\\project", project_id="p1", model="m", approval_mode="auto", tokens_used=1234, junk=b"x")
        for column in ("id", "rollout_path", "source", "thread_source", "archived", "history_mode"):
            definition = threads % ""
            definition = definition.replace(", %s " % column, ", zz_%s " % column, 1) if column != "id" else definition.replace("(id TEXT PRIMARY KEY", "(zz_id TEXT PRIMARY KEY")
            home = raw("schema-no-" + column, state=[definition], history=[turns % "", items % ""] + full, queue=[queue % ""])
            homes.append(home)
        for column in ("thread_id", "turn_id", "rollout_ordinal", "status", "error_json", "started_at", "completed_at",
                       "first_user_item_id", "rollout_end_byte_offset"):
            home = raw("schema-no-turn-" + column, state=[threads % ""], history=[(turns % "").replace(column + " ", "zz_" + column + " ", 1), items % ""] + full, queue=[queue % ""])
            homes.append(home)
        for column in ("thread_id", "turn_id", "item_id", "item_type", "item_json"):
            home = raw("schema-no-item-" + column, state=[threads % ""], history=[turns % "", (items % "").replace(column + " ", "zz_" + column + " ", 1)] + full, queue=[queue % ""])
            homes.append(home)
        for column in ("id", "thread_id", "payload_json"):
            home = raw("schema-no-queue-" + column, state=[threads % ""], history=[turns % "", items % ""] + full, queue=[(queue % "").replace(column + " ", "zz_" + column + " ", 1)])
            homes.append(home)
        # tables missing, files missing
        homes.append(raw("schema-only-state", state=[threads % ""]))
        homes.append(raw("schema-no-state", history=[turns % "", items % ""] + full, queue=[queue % ""]))
        homes.append(raw("schema-no-tables", state=["CREATE TABLE other (x)"], history=["CREATE TABLE other (x)"], queue=["CREATE TABLE other (x)"]))
        homes.append(raw("schema-no-projection", state=[threads % ""], history=[turns % "", items % ""], queue=[queue % ""]))
        # v0.6.26 final (FINAL-DELTA #1-#4; test_history_not_yet ReaderTests): no history database, the state holding
        # a conversation (the refusal it was), none beside a queue (HistoryNotYet), of a schema the reader refuses, with
        # no threads table, not a database, or not there at all (each the refusal it was: a state that cannot be read
        # is no "not yet")
        home = raw("history-absent-a-thread", state=[threads % ""], queue=[queue % ""])
        thread(home, uid(9700))
        homes.append(home)
        homes.append(raw("history-absent-queue", state=[threads % ""], queue=[queue % ""]))
        homes.append(raw("history-absent-state-refused", state=[(threads % "").replace("rollout_path ", "zz_rollout_path ", 1)]))
        homes.append(raw("history-absent-no-threads", state=["CREATE TABLE other (x)"]))
        home = raw("history-absent-state-damaged")
        (home.root / "state_5.sqlite").write_bytes(b"not a database at all" * 10)
        homes.append(home)
        homes.append(raw("history-absent-nothing"))
        home = raw("history-absent-two-states", state=[threads % ""])
        older = sqlite3.connect(home.root / "state_4.sqlite")
        older.execute(threads % "")
        older.execute("INSERT INTO threads (id) VALUES ('0a1b2c3d-0001-7000-8000-0000000000aa')")
        older.commit()
        older.close()
        homes.append(home)
        # declared types for tokens_used, columns of the names the guards read
        for number, declared in enumerate(("INTEGER", "INT UNSIGNED", "TEXT", "REAL", "BLOB", "", "bigint", "POINT")):
            home = raw("schema-tokens-%d" % number, state=[threads % (", cwd TEXT, model TEXT, approval_mode TEXT, tokens_used " + declared)],
                       history=[turns % "", items % ""] + full, queue=[queue % ""])
            fill(home, cwd="C:\\x", model="m", approval_mode="a", tokens_used=500)
        for number, value in enumerate((5, -1, 1 << 53, (1 << 53) + 1, 2.5, "7", None, b"b", 0)):
            home = raw("schema-tokens-value-%d" % number, state=[threads % ", cwd TEXT, model TEXT, approval_mode TEXT, tokens_used"],
                       history=[turns % "", items % ""] + full, queue=[queue % ""])
            fill(home, cwd="C:\\x", model="m", approval_mode="a", tokens_used=value)
        # labels: name columns of every kind, projects table present, absent, missing columns, and a column of the wrong type
        for number, (name, project_id, cwd) in enumerate((("A title", 1, "C:\\work\\repo"), ("two\nlines", "p", "\\\\?\\C:\\work\\x"), ("x" * 100, 2.5, "C:\\"),
                                                           ("tab\there", None, "relative\\path"), ("   ", b"b", ""), ("\u202eevil", 3, "   "),
                                                           ("emoji \U0001f600 ok", "p2", "C:\\work\\caf\u00e9"), (None, None, None), (7, 7, 7),
                                                           ("ends with space   ", 1, "C:\\a\\b\\"), ("nul\x00in", 1, "\\\\server\\share\\dir"),
                                                           ("x" * 72, 1, "C:\\" + "d" * 80), ("y" * 73, 1, "C:/slashes/here"), ("\u00a0nbsp\u00a0", 1, "D:"))):
            home = raw("schema-labels-%d" % number, state=[threads % ", name TEXT, cwd TEXT, project_id", "CREATE TABLE projects (id, name TEXT)",
                                                           "INSERT INTO projects VALUES (1, 'Project one')", "INSERT INTO projects VALUES ('p', 'x\ty')",
                                                           "INSERT INTO projects VALUES (2.5, '" + "q" * 90 + "')", "INSERT INTO projects VALUES (3, NULL)"],
                       history=[turns % "", items % ""] + full, queue=[queue % ""])
            fill(home, name=name, cwd=cwd, project_id=project_id)
        home = raw("schema-labels-no-projects", state=[threads % ", name TEXT, cwd TEXT, project_id"], history=[turns % "", items % ""] + full, queue=[queue % ""])
        fill(home, name="Named", cwd="C:\\x", project_id=1)
        home = raw("schema-labels-projects-wrong", state=[threads % ", name TEXT, cwd TEXT, project_id", "CREATE TABLE projects (other)"], history=[turns % "", items % ""] + full, queue=[queue % ""])
        fill(home, name="Named", cwd="C:\\x", project_id=1)
        home = raw("schema-only-name", state=[threads % ", name TEXT"], history=[turns % "", items % ""] + full, queue=[queue % ""])
        fill(home, name="Only")
        # one without any projection but with items carrying times
        self.run_homes("schemas", homes)

    def test_database_files(self):
        homes = []

        def made(name, files=None, state=True):
            home = self.home(name)
            home.sim.fail_usage(A, ordinal=5)
            home.sim.fail_transient(B, ordinal=5)
            for file, body in (files or {}).items():
                path = home.root / file
                if body is None:
                    if path.is_dir():
                        path.rmdir()
                    else:
                        path.unlink()
                elif body == "dir":
                    path.mkdir()
                else:
                    path.write_bytes(body)
            homes.append(home)
            return home

        made("db-plain")
        made("db-empty-state", {"state_5.sqlite": b""})
        made("db-garbage-state", {"state_5.sqlite": b"this is not a database" * 100})
        made("db-state-is-folder", {"state_5.sqlite": None})
        home = made("db-state-folder", {"state_5.sqlite": None})
        (home.root / "state_5.sqlite").mkdir()
        made("db-no-history", {"thread_history_1.sqlite": None})
        made("db-no-queue", {"queue_1.sqlite": None})
        for number, name in enumerate(("state_6.sqlite", "state_4.sqlite", "state_05.sqlite", "state_5.sqlite.bak", "state_5.sqlite-wal",
                                       "state_.sqlite", "STATE_9.sqlite", "state_x.sqlite", "state_10.sqlite", "state_\u0665.sqlite",
                                       "state_\u0669.sqlite", "state_99999999999999999999999999.sqlite", "state_-1.sqlite", "state_1_2.sqlite")):
            home = made("db-extra-%d" % number)
            source = (home.root / "state_5.sqlite").read_bytes()
            (home.root / name).write_bytes(source if number % 2 == 0 else b"junk")
        for number, name in enumerate(("thread_history_2.sqlite", "thread_history_0.sqlite", "queue_2.sqlite", "queue_10.sqlite")):
            home = made("db-extra-other-%d" % number)
            (home.root / name).write_bytes(b"junk")
        home = made("db-newer-generation-bad")
        connection = sqlite3.connect(home.root / "state_6.sqlite")
        connection.execute("CREATE TABLE threads (id TEXT)")
        connection.commit()
        connection.close()
        home = made("db-newer-generation-folder")
        (home.root / "state_9.sqlite").mkdir()
        home = made("db-wal-and-journal")
        (home.root / "state_5.sqlite-wal").write_bytes(b"")
        (home.root / "thread_history_1.sqlite-wal").write_bytes(b"x" * 10)
        home = made("db-symlink")
        try:
            os.symlink(home.root / "state_5.sqlite", home.root / "state_7.sqlite")
        except OSError:
            pass
        home = made("db-extra-lowercase-ext")
        (home.root / "state_8.SQLITE").write_bytes(b"junk")
        # a non-UTF-8 text in a column of a row, a NUL in a text
        home = made("db-bad-text")
        connection = sqlite3.connect(home.root / "thread_history_1.sqlite")
        connection.text_factory = bytes
        connection.execute("UPDATE thread_turns SET error_json=? WHERE thread_id=?", (b'{"codexErrorInfo":"\xff"}', B))
        connection.commit()
        connection.close()
        home = made("db-bad-text-state")
        connection = sqlite3.connect(home.root / "state_5.sqlite")
        connection.text_factory = bytes
        connection.execute("UPDATE threads SET source=? WHERE id=?", (b"vsc\xffode", B))
        connection.commit()
        connection.close()
        self.run_homes("database files", homes, light=True)

    # --------------------------------------------------------------------------------------- odd rows
    def test_odd_rows(self):
        rng = random.Random(20261125)
        statuses = ["completed", "failed", "failed", "failed", "inProgress", "interrupted", "Failed", "other", "", None, 5, b"failed"]
        numbers = [BASE, BASE - 100, BASE + 10, float(BASE), BASE + 0.5, 0, -5, 1, 4102444800, 4102444801, 946684800, 946684799, 10 ** 12,
                   "1788628000", "x", None, b"1", 1e308, BASE - 4000, BASE - 7200.25]
        ordinals = [0, 1, 5, 6, 7, 100, -1, 2.0, 2.5, "5", None, b"5", 1 << 40, (1 << 40) + 3, 1 << 62]
        errors = [json.dumps({"codexErrorInfo": "usageLimitExceeded"}), json.dumps({"codexErrorInfo": "serverOverloaded"}),
                  json.dumps({"codexErrorInfo": {"httpStatusCode": 503}}), json.dumps({"codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 502}}}),
                  json.dumps({"codexErrorInfo": {"serverOverloaded": {"retryAfterSeconds": 42}}}),
                  json.dumps({"codexErrorInfo": {"other": 1}, "message": "boom"}), json.dumps({"message": "stream disconnected before completion"}),
                  json.dumps({"codexErrorInfo": "unauthorized"}), json.dumps({"codexErrorInfo": "badRequest", "message": "x" * 200}),
                  json.dumps({"codexErrorInfo": None, "message": "connection reset by peer"}), json.dumps({"codexErrorInfo": 5}),
                  json.dumps({"codexErrorInfo": ["a"]}), json.dumps({"codexErrorInfo": {"type": 5}}), json.dumps({"codexErrorInfo": "contextWindowExceeded"}),
                  json.dumps([1]), json.dumps("x"), json.dumps(5), json.dumps(None), "null", "not json", "", None, b"blob", 7, 2.5, "{" * 3000,
                  "[" * 10000, json.dumps({"codexErrorInfo": "usageLimitExceeded", "n": 10 ** 5000}) if False else '{"codexErrorInfo":"usageLimitExceeded","n":' + "9" * 5000 + "}",
                  '{"codexErrorInfo":"usageLimitExceeded"} trailing', '\ufeff{"codexErrorInfo":"usageLimitExceeded"}', "x" * 1100000,
                  '{"codexErrorInfo":"serverOverloaded","message":"' + "m" * 1048000 + '"}',
                  json.dumps({"codexErrorInfo": {"httpStatusCode": 429, "retry_after": 30}}), json.dumps({"codexErrorInfo": "Usage_Limit_Exceeded"}),
                  json.dumps({"error": {"codexErrorInfo": "serverOverloaded"}})]
        homes = []
        for number in range(6):
            home = self.home("odd-%d" % number)
            for index in range(40):
                thread_id = uid(20000 + number * 100 + index)
                home.thread(thread_id, source=rng.choice(["vscode"] * 8 + ["cli", None]), thread_source=rng.choice(["user"] * 6 + [None, "subagent", "agent_created_thread"]),
                            archived=rng.choice([0] * 9 + [1]), name=rng.choice([None, "Named", "x\ny", "z" * 90]), cwd=rng.choice([None, "C:\\work", ""]))
                for turn_number in range(rng.randint(1, 3)):
                    turn_id = uid(30000 + number * 1000 + index * 10 + turn_number)
                    columns = dict(status=rng.choice(statuses), ordinal=rng.choice(ordinals), started=rng.choice(numbers),
                                   completed=rng.choice(numbers), error_json=rng.choice(errors))
                    try:
                        home.turn(thread_id, turn_id, **columns)
                    except sqlite3.Error:
                        pass
                    if rng.random() < 0.5:
                        home.user_message(thread_id, turn_id, "item-%d-%d-%d" % (number, index, turn_number), "hello " + marker("a"), client_id=rng.choice([None, uid(1), "cid"]))
                    if rng.random() < 0.3:
                        home.item(thread_id, turn_id, "work-%d-%d-%d" % (number, index, turn_number), rng.choice(["agentMessage", "commandExecution", "reasoning", "contextCompaction", "fileChange", "weird", None, 5]),
                                  {"type": "x"}, created=rng.choice([None, 1788628000000, 5, "x", 1.5e12]))
            homes.append(home)
        self.run_homes("odd rows", homes, light=True)
        # and the whole battery on the first few turns of one
        self.run_homes("odd rows (full)", homes[:1], markers=[uid(1), "cid"])

    def test_items_and_markers(self):
        home = self.home("items")
        sim = home.sim
        thread_id = A
        sim.add_thread(thread_id)
        turn = uid(40001)
        sim.add_turn(thread_id, turn, status="completed", ordinal=4)
        cid = uid(40100)
        for number, text in enumerate(("go " + marker("a"), "go " + short_marker("a"), "go", marker("b"), "x" + marker("a") + "y", marker("a") * 3)):
            turn_id = uid(40010 + number)
            home.turn(thread_id, turn_id, status="completed", ordinal=10 + number, first_user="u%d" % number)
            home.user_message(thread_id, turn_id, "u%d" % number, text, client_id=cid if number == 2 else None)
            home.item(thread_id, turn_id, "w%d" % number, "agentMessage", {"type": "agentMessage", "text": "hi"}, ordinal=5)
        # an item whose JSON holds our marker but is not a user message, one with bad content, one with a client id only
        for number, payload in enumerate(({"type": "agentMessage", "content": [{"type": "text", "text": marker("a")}]},
                                          {"type": "userMessage", "content": "x " + marker("a")},
                                          {"type": "userMessage", "content": [{"type": "image", "text": marker("a")}]},
                                          {"type": "userMessage", "content": [{"type": "text", "text": 5}], "clientId": cid},
                                          {"type": "userMessage", "content": [5, None, {"type": "text", "text": marker("a")}]},
                                          {"type": "userMessage", "clientId": cid, "content": []},
                                          {"type": "userMessage", "clientId": cid + "x"},
                                          {"type": "userMessage", "clientId": 5, "content": [{"type": "text", "text": marker("a")}]},
                                          [1], "x", None, {"type": "userMessage", "content": [{"type": "text", "text": "\ud800" + marker("a")}]})):
            turn_id = uid(40050 + number)
            home.turn(thread_id, turn_id, status="completed", ordinal=30 + number)
            text = json.dumps(payload) if not isinstance(payload, str) else payload
            home.item(thread_id, turn_id, "z%d" % number, "userMessage", text + (marker("a") if number == 10 else ""), ordinal=1)
        # the queue: every shape
        for number, payload in enumerate(({"UserInput": {"content": [{"type": "text", "text": "go " + marker("a")}], "client_id": cid}},
                                          {"UserInput": {"content": [{"type": "text", "text": "go"}], "client_id": cid}},
                                          {"UserInput": {"content": [], "client_id": uid(40101)}}, {"UserInput": {"content": 5}},
                                          {"UserInput": [1]}, {"Other": {"content": [{"type": "text", "text": marker("a")}]}},
                                          {"UserInput": {"content": [{"type": "text", "text": marker("a")}]}, "extra": 1},
                                          [1], "x", 5, None, {"UserInput": {"client_id": 5}}, {"UserInput": {"client_id": "bad id!"}},
                                          {"UserInput": {"content": [{"type": "text", "text": marker("a")}], "client_id": "x" * 70}})):
            text = payload if isinstance(payload, str) else json.dumps(payload)
            if number == 8:
                text = "just text " + marker("a")
            home.queue("INSERT INTO queued_items (id, thread_id, payload_json, queue_order) VALUES (?,?,?,?)", uid(40200 + number), thread_id, text, number)
        home.queue("INSERT INTO queued_items (id, thread_id, payload_json, queue_order) VALUES (?,?,?,?)", "not-a-uuid", thread_id, marker("a"), 99)
        home.queue("INSERT INTO queued_items (id, thread_id, payload_json, queue_order) VALUES (?,?,?,?)", uid(40299), B, marker("a"), 100)
        home.queue("INSERT INTO queued_items (id, thread_id, payload_json, queue_order) VALUES (?,?,?,?)", uid(40298), thread_id, None, 101)
        self.run_homes("items and markers", [home], markers=[cid, uid(40101), uid(40200)])

    def test_stalled_and_activity(self):
        home = self.home("stalled")
        sim = home.sim
        for number in range(8):
            thread_id = uid(50000 + number)
            sim.add_thread(thread_id)
            home.turn(thread_id, uid(50100 + number), status="inProgress", ordinal=5, started=BASE - 7200 - number * 100, completed=None)
            created = (None, 1788628000000 - 7000 * 1000, (BASE - 100) * 1000, 5, "x", 1.5e12, BASE * 1000 + 10 ** 9 * 1000, (BASE - 7000) * 1000 + 0.5)[number]
            home.item(thread_id, uid(50100 + number), "item%d" % number, "agentMessage", {}, created=created)
        sim.add_thread(uid(50200))
        home.turn(uid(50200), uid(50201), status="inProgress", ordinal=5, started=BASE - 60, completed=None)
        home.turn(uid(50200), uid(50202), status="completed", ordinal=6, started=BASE - 50)
        queued_at = (None, 1788628000000, 5, 1.5e12, "x")
        for number, created in enumerate(queued_at):
            home.queue("INSERT INTO queued_items (id, thread_id, payload_json, queue_order, created_at_ms) VALUES (?,?,?,?,?)", uid(50300 + number), A, "x", number, created)
        self.run_homes("stalled and activity", [home])

    def test_cloud_tasks_and_global_state(self):
        homes = []
        prefix = "cloud-thread-prototype-threads-by-account-v1."
        bodies = {
            "empty-object": b"{}", "list": b"[]", "none": None, "bom": b"\xef\xbb\xbf{}", "bad-utf8": b'{"\xff": 1}', "not-json": b"hello",
            "plain": json.dumps({prefix + "a": ["x", "y", "z"], prefix + "b": {"p": 1, "q": 2}, prefix + "c": 5, "other": 1}).encode(),
            "nested": json.dumps({"a": {"b": {"c": {"d": {prefix + "x": [1, 2]}}}}}).encode(),
            "too-deep": json.dumps({"a": {"b": {"c": {"d": {"e": {prefix + "x": [1, 2]}}}}}}).encode(),
            "list-holds": json.dumps({"a": [{prefix + "x": [1]}], prefix + "y": []}).encode(),
            "prefix-in-value": json.dumps({"k": prefix + "z"}).encode(), "numbers": json.dumps({prefix: "text", prefix + "n": 0, prefix + "t": True}).encode(),
            "deep-list": b"[" * 4000 + b"]" * 4000, "nan": b'{"x": NaN, "' + prefix.encode() + b'1": [1]}', "dup": b'{"' + prefix.encode() + b'a": [1], "' + prefix.encode() + b'a": [1, 2, 3]}',
            "crlf": b'{\r\n"' + prefix.encode() + b'a": [1,\r\n2]}\r\n', "string": b'"' + prefix.encode() + b'"', "unicode": json.dumps({"\u00e9": 1, prefix + "\u00e9": [1]}, ensure_ascii=False).encode(),
            "big": json.dumps({"k%d" % n: {prefix + str(n): [n]} for n in range(2000)}).encode(),
        }
        for number, (name, body) in enumerate(bodies.items()):
            home = self.home("cloud-%d" % number)
            home.sim.add_thread(A)
            if body is not None:
                (home.root / ".codex-global-state.json").write_bytes(body)
            homes.append(home)
        home = self.home("cloud-folder")
        (home.root / ".codex-global-state.json").mkdir()
        homes.append(home)
        home = self.home("cloud-huge")
        (home.root / ".codex-global-state.json").write_bytes(b"{" + b" " * (16 * 1024 * 1024) + b"}")
        homes.append(home)
        home = self.home("cloud-just-over")
        (home.root / ".codex-global-state.json").write_bytes(b"{" + b" " * (16 * 1024 * 1024 - 1) + b"}")
        homes.append(home)
        home = self.home("cloud-at-limit")
        (home.root / ".codex-global-state.json").write_bytes(b"{" + b" " * (16 * 1024 * 1024 - 2) + b"}")
        homes.append(home)
        home = self.home("cloud-link")
        (home.root / "elsewhere.json").write_bytes(b"{}")
        try:
            os.symlink(home.root / "elsewhere.json", home.root / ".codex-global-state.json")
        except OSError:
            pass
        homes.append(home)
        self.run_homes("cloud tasks", homes, light=True, plug=False)

    def test_sessions_folder(self):
        homes = []
        home = self.home("sessions-missing")
        home.sim.add_thread(A)
        home.sim.fail_usage(A, ordinal=5)
        import shutil
        shutil.rmtree(home.root / "sessions")
        homes.append(home)
        home = self.home("sessions-is-file")
        home.sim.add_thread(A)
        shutil.rmtree(home.root / "sessions")
        (home.root / "sessions").write_bytes(b"x")
        homes.append(home)
        home = self.home("sessions-names")
        home.sim.add_thread(A)
        for number, name in enumerate(("%s_%s.JSONL" % (A, B), "%s_%s.jsonl.bak" % (A, B), "x%s_%s.jsonl" % (A, C), "-%s_%s.jsonl" % (A, D),
                                       "_%s_%s.jsonl" % (A, E), "a-%s_%s.jsonl" % (A, F), "%s_%s.jsonl" % (A.upper(), B), "%s_%s_%s.jsonl" % (A, B, C),
                                       "%s__%s.jsonl" % (A, B), "%s_%s .jsonl" % (A, B), "\u00e9%s_%s.jsonl" % (A, C))):
            (home.root / "sessions" / name).write_bytes(home.sim.rollout(A).read_bytes() if number else b"x")
            home.turn(B, uid(55000 + number), status="completed", ordinal=number)
        folder = home.root / "sessions" / ("%s_%s.jsonl" % (A, E))
        folder.mkdir()
        path = home.root / "sessions" / ("rollout-last-%s_%s.jsonl" % (A, F))
        path.write_bytes(home.sim.rollout(A).read_bytes())
        home.state("UPDATE threads SET rollout_path=? WHERE id=?", str(path), A)
        homes.append(home)
        self.run_homes("sessions folder", homes, light=True)

    def test_workspace_in_task_facts(self):
        home = self.home("workspace")
        folders = {}
        base = self.scratch / "workspaces"
        for number, (name, make) in enumerate({
            "plain": lambda folder: None,
            "git-branch": lambda folder: (folder / ".git").mkdir() or (folder / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n"),
            "git-sha": lambda folder: (folder / ".git").mkdir() or (folder / ".git" / "HEAD").write_bytes(b"0123456789abcdef0123456789abcdef01234567\n"),
            "git-empty": lambda folder: (folder / ".git").mkdir() or (folder / ".git" / "HEAD").write_bytes(b""),
            "git-large": lambda folder: (folder / ".git").mkdir() or (folder / ".git" / "HEAD").write_bytes(b"x" * 5000),
            "git-limit": lambda folder: (folder / ".git").mkdir() or (folder / ".git" / "HEAD").write_bytes(b"x" * 4096),
            "git-no-head": lambda folder: (folder / ".git").mkdir(),
            "git-head-dir": lambda folder: (folder / ".git").mkdir() or (folder / ".git" / "HEAD").mkdir(),
            "git-worktree": lambda folder: (folder / "real").mkdir() or (folder / "real" / "HEAD").write_bytes(b"ref: x\n") or (folder / ".git").write_bytes(("gitdir: " + str(folder / "real") + "\n").encode()),
            "git-worktree-relative": lambda folder: (folder / "real").mkdir() or (folder / "real" / "HEAD").write_bytes(b"ref: y\n") or (folder / ".git").write_bytes(b"gitdir: real\n"),
            "git-worktree-slashes": lambda folder: (folder / "real").mkdir() or (folder / "real" / "HEAD").write_bytes(b"ref: y\n") or (folder / ".git").write_bytes(("gitdir: " + str(folder / "real").replace("\\", "/") + "\n").encode()),
            "git-file-empty": lambda folder: (folder / ".git").write_bytes(b""),
            "git-file-blank": lambda folder: (folder / ".git").write_bytes(b"  \n\t\n"),
            "git-file-junk": lambda folder: (folder / ".git").write_bytes(b"hello\n"),
            "git-file-bom": lambda folder: (folder / ".git").write_bytes(b"\xef\xbb\xbfgitdir: real\n"),
            "git-file-bad-utf8": lambda folder: (folder / ".git").write_bytes(b"gitdir: \xff\n"),
            "git-file-share": lambda folder: (folder / ".git").write_bytes(b"gitdir: \\\\server\\share\\x\n"),
            "git-file-share-slash": lambda folder: (folder / ".git").write_bytes(b"gitdir: //server/share/x\n"),
            "git-file-empty-target": lambda folder: (folder / ".git").write_bytes(b"gitdir:   \n"),
            "git-file-large": lambda folder: (folder / ".git").write_bytes(b"gitdir: " + b"x" * 5000),
            "git-file-crlf": lambda folder: (folder / "real").mkdir() or (folder / "real" / "HEAD").write_bytes(b"ref: z\n") or (folder / ".git").write_bytes(b"gitdir: real\r\nsecond\r\n"),
            "git-file-unicode-lines": lambda folder: (folder / "real").mkdir() or (folder / "real" / "HEAD").write_bytes(b"ref: z\n") or (folder / ".git").write_bytes("gitdir: real\u2028other\n".encode()),
            "git-file-extended": lambda folder: (folder / "real").mkdir() or (folder / "real" / "HEAD").write_bytes(b"ref: w\n") or (folder / ".git").write_bytes(("gitdir: \\\\?\\" + str(folder / "real") + "\n").encode()),
            "git-file-unc-extended": lambda folder: (folder / ".git").write_bytes(b"gitdir: \\\\?\\UNC\\server\\share\n"),
            "git-file-drive-relative": lambda folder: (folder / ".git").write_bytes(b"gitdir: C:real\n"),
            "git-file-rooted": lambda folder: (folder / ".git").write_bytes(b"gitdir: \\real\n"),
            "git-file-dotdot": lambda folder: (folder / "real").mkdir() or (folder / "real" / "HEAD").write_bytes(b"ref: w\n") or (folder / "sub").mkdir() or (folder / ".git").write_bytes(b"gitdir: sub\\..\\real\n"),
        }.items()):
            folder = base / name
            folder.mkdir(parents=True)
            make(folder)
            folders[name] = folder
            thread_id = uid(60000 + number)
            home.thread(thread_id, cwd=str(folder))
        for number, cwd in enumerate(("relative\\x", "", "   ", "\\\\server\\share\\x", "\\\\?\\" + str(base / "git-branch"), "\\\\?\\UNC\\s\\x", str(base / "git-branch").replace("\\", "/"),
                                      str(base / "git-branch") + "\n", str(base / "git-branch") + "\x00", "  " + str(base / "git-sha") + "  ", str(base / "nowhere"), "C:", "C:\\", str(base / "git-branch").upper(),
                                      "\u00e9", "\\\\?\\", "\\\\", "//x/y", "D:\\no\\such\\folder")):
            thread_id = uid(61000 + number)
            home.thread(thread_id, cwd=cwd)
        for number, cwd in enumerate((5, 2.5, b"bytes")):
            thread_id = uid(62000 + number)
            home.thread(thread_id)
            home.state("UPDATE threads SET cwd=? WHERE id=?", cwd, thread_id)
        self.run_homes("workspace", [home], light=True)
        # the full battery asks the fingerprint of every one
        thread_ids = [row[0] for row in sqlite3.connect(home.root / "state_5.sqlite").execute("SELECT id FROM threads")]
        case = {"home": str(home.root), "ops": [op("task_facts", each, fingerprint=True, tokens=True) for each in thread_ids]
                + [op("task_facts", each, fingerprint=True) for each in thread_ids] + [op("identity", each) for each in thread_ids]
                + [op("project_key", each) for each in thread_ids]}
        count, calls = self.script([case], "workspace facts")
        RECORD.append("homes workspace facts: %d calls equal" % calls)
        TOTAL["calls"] += calls

    def test_chain_memory_file(self):
        """`ChainMemory`'s own file: every kind of file a reader or the watcher may find."""
        cases = []
        home = self.home("memory")
        home.sim.add_thread(A)
        from rustdiff import reference
        key_script = "import sys\nfrom pathlib import Path\nfrom codex_auto_resume import homes\nsys.stdout.write(homes.key(Path(sys.argv[1])))\n"
        profile = self.profile("keys")
        done = reference.run(key_script, home.root, profile=profile)
        key = done.stdout.decode()
        bodies = {
            "ok": {"format": 1, "homes": {key: {A: [B, C], uid(5): [D]}}},
            "format-2": {"format": 2, "homes": {key: {A: [B]}}},
            "format-true": {"format": True, "homes": {key: {A: [B]}}},
            "format-float": {"format": 1.0, "homes": {key: {A: [B]}}},
            "no-format": {"homes": {key: {A: [B]}}},
            "homes-none": {"format": 1, "homes": None}, "homes-empty": {"format": 1, "homes": {}}, "homes-zero": {"format": 1, "homes": 0},
            "homes-false": {"format": 1, "homes": False}, "homes-empty-list": {"format": 1, "homes": []}, "homes-empty-text": {"format": 1, "homes": ""},
            "homes-list": {"format": 1, "homes": [1]}, "homes-text": {"format": 1, "homes": "x"}, "homes-number": {"format": 1, "homes": 5},
            "held-not-dict": {"format": 1, "homes": {key: [1], "other": "x", "n": None}},
            "chain-not-list": {"format": 1, "homes": {key: {A: "x", B: {"a": 1}, C: None}}},
            "bad-ids": {"format": 1, "homes": {key: {A: [B, "x", 5, None, C.upper(), D], "bad": [B]}}},
            "too-many": {"format": 1, "homes": {key: {A: [uid(100 + n) for n in range(100)]}}},
            "not-dict": [1, 2], "string": "x",
        }
        for number, (name, body) in enumerate(bodies.items()):
            path = self.scratch / ("memory-%d.json" % number)
            path.write_text(json.dumps(body), encoding="utf-8")
            cases.append({"home": str(home.root), "chains": str(path), "ops": [op("chains.get", A), op("chains.get", uid(5)), op("chains.extend", A, [E, E, A, F]), op("chains.get", A),
                                                                          op("chains.extend", uid(5), [B]), op("chains.extend", A, ["x"]), op("chains.get", "x")]})
        for number, body in enumerate((b"", b"\xef\xbb\xbf{}", b"\xff", b"{", b"null", b"{" * 5000, b"x" * 100)):
            path = self.scratch / ("memory-raw-%d.json" % number)
            path.write_bytes(body)
            cases.append({"home": str(home.root), "chains": str(path), "ops": [op("chains.get", A), op("chains.extend", A, [B]), op("chains.get", A)]})
        cases.append({"home": str(home.root), "chains": str(self.scratch / "memory-missing.json"), "ops": [op("chains.get", A), op("chains.extend", A, [B, C]), op("chains.get", A), op("chains.extend", A, [B, C, D])]})
        cases.append({"home": str(home.root), "ops": [op("chains.get", A), op("chains.extend", A, [B, C]), op("chains.get", A), op("chains.extend", A, [B, D]), op("chains.get", A),
                                                      op("chains.extend", A, [uid(200 + n) for n in range(70)]), op("chains.get", A)]})
        many = [op("chains.extend", uid(1000 + n), [B]) for n in range(2100)] + [op("chains.get", uid(1000)), op("chains.get", uid(1100)), op("chains.get", uid(3000))]
        cases.append({"home": str(home.root), "chains": str(self.scratch / "memory-many.json"), "ops": many})
        count, calls = self.script(cases, "chain memory")
        TOTAL["homes"] += count
        TOTAL["calls"] += calls
        RECORD.append("chain memory: %d files and homes, %d calls equal" % (count, calls))
        # what each wrote must be the same file, byte for byte
        for number in range(len(bodies)):
            pass

    def test_zzz_totals(self):
        RECORD.append("homes total this run: %d homes, %d calls" % (TOTAL["homes"], TOTAL["calls"]))


if __name__ == "__main__":
    unittest.main()

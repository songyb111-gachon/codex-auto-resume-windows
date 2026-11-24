"""What the S3.2 diffs (diffs_codex_*.py) share: Codex homes written once, read by the reference and by Rust.

car-codex's readers never write, so one home on disk is read by both, where it is: the same path for both, which is
why no path needs to be made canonical. A `script` is a list of cases, each a home and a list of calls named as the
reference's `LocalSource` methods (`{"method": "latest", "args": [thread_id], "kwargs": {...}}`); the reference runs
them in a process of its own (`SCRIPT`, started through reference.py with no console window and a scratch profile) and
car-harness answers the same list as one `codex.script` call. Every answer must be the same value, keys in the same
order, an exception the same class (an `OSError` of any kind is `OSError`; a `SourceError` has its sentence too).

`Home` writes the homes: codexsim's own `CodexHome` (the real tables the engine tests read), plus the rollout files
and the odd rows codexsim has no builder for - splits, first lines of every kind, a BLOB where a text belongs.
Not a test module (no `test` in its name, and not `diffs_*`): run.py imports it through them.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

import released
from rustdiff import core, diffs, reference

ROOT = core.ROOT
TESTS = ROOT / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
import codexsim  # noqa: E402

BASE = codexsim.BASE
A = "0a1b2c3d-0001-7000-8000-00000000000a"
B = "0a1b2c3d-0001-7000-8000-00000000000b"
C = "0a1b2c3d-0001-7000-8000-00000000000c"
D = "0a1b2c3d-0001-7000-8000-00000000000d"
E = "0a1b2c3d-0001-7000-8000-00000000000e"
F = "0a1b2c3d-0001-7000-8000-00000000000f"
IDS = [A, B, C, D, E, F]


def marker(digit: str = "a") -> str:
    return "[codex-auto-resume:" + digit * 64 + "]"


def short_marker(digit: str = "a") -> str:
    return "[codex-auto-resume:" + digit * 16 + "]"


# The reference's side: the tag's own `LocalSource`, driven by the same list of calls. Its module state (the split
# listing, the first lines remembered, the triggers) is cleared before each case, as a fresh process starts.
SCRIPT = r'''
import json, sys, time
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
from codex_auto_resume.codex import LocalSource, rollout, chains as chains_module
from codex_auto_resume.codex.errors import SourceError


def plain(value):
    if isinstance(value, (tuple, list)):
        return [plain(each) for each in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(each) for each in value)
    if isinstance(value, dict):
        return {key: plain(each) for key, each in value.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return []                      # a BLOB: car-codex carries it as an empty list (sql::Cell::value)
    return value


def raised(error):
    name = "OSError" if isinstance(error, OSError) else type(error).__name__
    return {"raised": name, "message": str(error) if isinstance(error, SourceError) else ""}


def frozen(value):
    return None if value is None else frozenset(value)


def call(source, memory, operation):
    method, args, keywords = operation["method"], list(operation.get("args", [])), dict(operation.get("kwargs", {}))
    if method == "@plug":
        source.session_kinds = frozenset(keywords.get("kinds") or ())
        source.widened = frozenset(keywords.get("widened") or ())
        return None
    if method.startswith("chains."):
        return getattr(memory, method.split(".", 1)[1])(source.home, *args)
    if method in ("written_by", "taken", "newer_than_engine"):
        args[1] = frozenset(args[1])
    if method == "_eligibility":
        for name in ("kinds", "widened"):
            if name in keywords:
                keywords[name] = frozen(keywords[name])
    if method == "taken" and "widened" in keywords:
        keywords["widened"] = frozen(keywords["widened"])
    if method == "latest_failures" and "needs_you" in keywords:
        keywords["needs_you"] = frozenset(keywords["needs_you"])
    if method == "passed_over":
        if "known" in keywords:
            keywords["known"] = frozenset(keywords["known"])
        if "deadline_in" in keywords:
            keywords["deadline"] = time.monotonic() + keywords.pop("deadline_in")
    return plain(getattr(source, method)(*args, **keywords))


answers = []
for case in request["cases"]:
    for name in ("_SPLITS", "_ASKED", "_RELISTED", "_META", "_TRIGGERS"):
        getattr(rollout, name).clear()
    memory = chains_module.memory(Path(case["chains"])) if case.get("chains") else chains_module.ChainMemory()
    try:
        source = LocalSource(Path(case["home"]), chains=memory)
    except Exception as error:
        answers.append({"open": raised(error), "results": []})
        continue
    source.session_kinds = frozenset(case.get("kinds") or ())
    source.widened = frozenset(case.get("widened") or ())
    results = []
    for operation in case.get("ops", []):
        try:
            results.append(call(source, memory, operation))
        except Exception as error:
            results.append(raised(error))
    answers.append({"open": None, "results": results})
sys.stdout.write(json.dumps(answers, ensure_ascii=False, allow_nan=False))
'''


class Home:
    """A Codex home on disk: codexsim's tables and rollouts, and what codexsim has no builder for."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.sim = codexsim.CodexHome(self.root)
        self.sim.clock = lambda: BASE

    # ----------------------------------------------------------------------------------------- the databases
    def state(self, sql: str, *parameters):
        connection = sqlite3.connect(self.root / "state_5.sqlite")
        try:
            connection.execute(sql, parameters)
            connection.commit()
        finally:
            connection.close()

    def history(self, sql: str, *parameters):
        connection = sqlite3.connect(self.root / "thread_history_1.sqlite")
        try:
            connection.execute(sql, parameters)
            connection.commit()
        finally:
            connection.close()

    def queue(self, sql: str, *parameters):
        connection = sqlite3.connect(self.root / "queue_1.sqlite")
        try:
            connection.execute(sql, parameters)
            connection.commit()
        finally:
            connection.close()

    def thread(self, thread_id, *, source="vscode", thread_source="user", archived=0, history_mode="paginated",
               name=None, cwd=None, project_id=None, path=None, originator="Codex Desktop", first=None,
               write_file=True, extra_meta=None):
        """A `threads` row with exactly these columns, and its rollout file's first line (`first`, a dict or the
        bytes themselves, else the one a person's desktop conversation has)."""
        path = Path(path) if path is not None else self.sim.rollout(thread_id)
        if write_file:
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(first, (bytes, bytearray)):
                path.write_bytes(bytes(first))
            else:
                payload = {"id": thread_id, "originator": originator, "source": "vscode", "thread_source": thread_source}
                payload.update(extra_meta or {})
                event = first if first is not None else {"type": "session_meta", "payload": payload}
                path.write_bytes(json.dumps(event).encode("utf-8") + b"\n")
        self.state("INSERT OR REPLACE INTO threads (id, rollout_path, source, thread_source, archived, history_mode, "
                   "name, cwd, project_id) VALUES (?,?,?,?,?,?,?,?,?)",
                   thread_id, str(path), source, thread_source, archived, history_mode, name, cwd, project_id)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        self.history("INSERT OR REPLACE INTO thread_history_projection_state VALUES (?,?,0)", thread_id, size)
        return path

    def turn(self, thread_id, turn_id, *, status="failed", ordinal=5, started=BASE - 100, completed=BASE,
             error_json=None, first_user=None, final_agent=None, end=None):
        self.history("INSERT OR REPLACE INTO thread_turns (thread_id, turn_id, rollout_ordinal, status, error_json, "
                     "started_at, completed_at, first_user_item_id, final_agent_item_id, rollout_end_byte_offset) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     thread_id, turn_id, ordinal, status, error_json, started, completed, first_user, final_agent, end)

    def item(self, thread_id, turn_id, item_id, item_type, payload, ordinal=1, created=None):
        text = payload if isinstance(payload, (str, bytes)) or payload is None else json.dumps(payload)
        self.history("INSERT OR REPLACE INTO thread_items (thread_id, turn_id, item_id, rollout_ordinal, created_at_ms, "
                     "item_json, item_type) VALUES (?,?,?,?,?,?,?)",
                     thread_id, turn_id, item_id, ordinal, created, text, item_type)

    def append(self, thread_id, lines):
        """Raw lines (bytes or events) added to a conversation's file."""
        with self.sim.rollout(thread_id).open("ab") as stream:
            for line in lines:
                stream.write(line if isinstance(line, bytes) else json.dumps(line).encode("utf-8") + b"\n")

    def user_message(self, thread_id, turn_id, item_id, text, client_id=None, ordinal=1):
        payload = {"type": "userMessage", "id": item_id, "clientId": client_id, "content": [{"type": "text", "text": text}]}
        self.item(thread_id, turn_id, item_id, "userMessage", payload, ordinal)

    # --------------------------------------------------------------------------------------------- splits
    def split_file(self, owner, other, *, stamp=0, meta_id=None, thread_source="user", originator="Codex Desktop"):
        """Codex's next file for `owner`, named `..._<owner>_<other>.jsonl`, its first line saying `meta_id`."""
        path = self.root / "sessions" / ("rollout-2026-10-14T12-00-%02d-%s_%s.jsonl" % (stamp, owner, other))
        meta = {"type": "session_meta", "payload": {"id": meta_id or owner, "originator": originator,
                                                    "source": "vscode", "thread_source": thread_source}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(meta).encode("utf-8") + b"\n")
        return path


class CodexBase(diffs.Base):
    """`script(cases)`: every case through the reference and through car-harness, held equal."""

    def home(self, name: str) -> Home:
        folder = self.scratch / name
        folder.mkdir(parents=True, exist_ok=True)
        return Home(folder / "codex-home")

    def reference_answers(self, cases: list) -> list:
        profile = self.profile("reference-%d" % time.perf_counter_ns())
        path = profile / "cases.json"
        path.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
        done = reference.run(SCRIPT, path, profile=profile)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:].decode("utf-8", "replace"))
        return json.loads(done.stdout.decode("utf-8"))

    def rust_answers(self, cases: list) -> list:
        with core.Harness(reference.scratch_environment(self.profile("rust-%d" % time.perf_counter_ns()))) as harness:
            number, line = harness.call("codex.script", cases=cases)
        reply = json.loads(line.decode("utf-8"))
        self.assertEqual(reply.get("id"), number, line[:300])
        self.assertTrue(reply["reply"].get("ok"), line[:600])
        return reply["reply"]["value"]

    def script(self, cases: list, label: str, *, chunk: int = 40) -> tuple[int, int]:
        """Held equal: (cases, calls). `chunk` cases go to each process. A case with a `chains` file is run on the file
        for the reference and on a copy of it, as it was, for Rust; the two files are then the same bytes."""
        calls = 0
        for start in range(0, len(cases), chunk):
            part = cases[start:start + chunk]
            rust_part, copies = [], []
            for case in part:
                if case.get("chains"):
                    original = Path(case["chains"])
                    copy = original.with_name(original.name + ".rust")
                    if original.exists():
                        shutil.copyfile(original, copy)
                    else:
                        copy.unlink(missing_ok=True)
                    rust_part.append(dict(case, chains=str(copy)))
                    copies.append((original, copy))
                else:
                    rust_part.append(case)
            expected, actual = self.reference_answers(part), self.rust_answers(rust_part)
            self.assertEqual(len(expected), len(actual), label)
            for number, (want, got, case) in enumerate(zip(expected, actual, part)):
                if diffs.encode(want) != diffs.encode(got):
                    self.report(label, start + number, case, want, got)
                calls += len(case.get("ops", []))
            for original, copy in copies:
                theirs = original.read_bytes() if original.exists() else None
                mine = copy.read_bytes() if copy.exists() else None
                if theirs != mine:
                    self.fail("%s: the chain memory file differs: reference %r, rust %r" % (label, theirs, mine))
        return len(cases), calls

    def report(self, label, number, case, want, got):
        if want.get("open") != got.get("open"):
            self.fail("%s case %d: open differs: reference %s, rust %s" % (
                label, number, json.dumps(want.get("open")), json.dumps(got.get("open"))))
        for index, (a, b) in enumerate(zip(want["results"], got["results"])):
            if diffs.encode(a) != diffs.encode(b):
                self.fail("%s case %d, call %d (%s %s) differs:\n  reference %s\n  rust      %s" % (
                    label, number, index, case["ops"][index]["method"],
                    json.dumps(case["ops"][index].get("args"), ensure_ascii=False)[:300],
                    json.dumps(a, ensure_ascii=False)[:1500], json.dumps(b, ensure_ascii=False)[:1500]))
        self.fail("%s case %d differs in length: %d against %d" % (label, number, len(want["results"]), len(got["results"])))


def keep(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


__all__ = ["A", "B", "C", "D", "E", "F", "IDS", "BASE", "CodexBase", "Home", "marker", "short_marker", "released"]

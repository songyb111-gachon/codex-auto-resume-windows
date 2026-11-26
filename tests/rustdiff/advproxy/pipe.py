"""The pipe to `advserve` (car-adv's example, advanced/rust/crates/car-adv/examples/advserve/): one process per test
process, a JSON line each way, a session per object a test made (a `Runtime`, an `AdvancedState`).

A request goes out as `{"id", "call", "session", ...}`; while it waits, car-adv asks the test back (`{"ask": kind,
...}`): each question is answered here by the session's own object (`Session.answer`) - which may call car-adv again,
nested, before its answer is written (a code that reads its `Scoped`, an errand that sends). The reply `{"id",
"reply"}` ends the wait: its value, or a raise re-raised as the reference's own class (`Session.raised`).

Values cross as JSON: an enum as its value, a tuple or a set as a list, a dict whose keys are not all text as
`{"__pairs__": [[key, value], ...]}`, bytes as a list of numbers (car-adv `state::calls`'s rule, the advstore runner's).
"""
from __future__ import annotations

import enum
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import weakref

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT / "advanced" / "rust"


def executable() -> Path:
    """CODEX_AR_ADVSERVE_EXE, else the advanced workspace's release build, else its debug build."""
    named = os.environ.get("CODEX_AR_ADVSERVE_EXE")
    if named:
        return Path(named)
    target = Path(os.environ.get("CARGO_TARGET_DIR") or WORKSPACE / "target")
    release = target / "release" / "examples" / "advserve.exe"
    debug = target / "debug" / "examples" / "advserve.exe"
    if not release.is_file() and debug.is_file():
        return debug
    return release


def plain(value):
    """A Python value as car-adv reads it."""
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, enum.Enum):
            return value.value
        return value
    if isinstance(value, enum.Enum):
        return plain(value.value)
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    if isinstance(value, sqlite3.Row):
        value = dict(value)
    if isinstance(value, dict):
        if all(isinstance(name, str) for name in value):
            return {(name.value if isinstance(name, enum.Enum) else name): plain(item) for name, item in value.items()}
        return {"__pairs__": [[plain(name), plain(item)] for name, item in value.items()]}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((plain(item) for item in value), key=lambda item: (str(type(item)), repr(item)))
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {name: plain(getattr(value, name)) for name in value.__dataclass_fields__}
    return repr(value)


class Exited(RuntimeError):
    """advserve ended while a call was waiting for it."""


class Pipe:
    """The one `advserve` of this process. One lock, re-entered by the thread that holds it (a nested call); a session
    let go is closed at the next request, never from the collector's thread."""

    def __init__(self):
        self.lock, self.process, self.next_session, self.next_id, self.depth = threading.RLock(), None, 0, 0, 0
        self.sessions = weakref.WeakValueDictionary()
        self.gone = []
        # Every call made, by its kind: what the ledger reads to tell a file that reached car-adv from one that did not
        # (CODEX_AR_ADVPROXY_COUNT names a file each process appends its counts to as it ends).
        self.counts = {}

    def start(self):
        if self.process is None or self.process.poll() is not None:
            path = executable()
            if not path.is_file():
                raise Exited("advserve is not built: cargo build --release -p car-adv --example advserve "
                             "(in advanced/rust)")
            self.process = subprocess.Popen([str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, cwd=str(ROOT))
        return self.process

    def session(self, owner) -> int:
        with self.lock:
            self.next_session += 1
            self.sessions[self.next_session] = owner
            weakref.finalize(owner, self.gone.append, self.next_session)
            return self.next_session

    def write(self, message):
        process = self.start()
        process.stdin.write((json.dumps(message, ensure_ascii=True, allow_nan=True) + "\n").encode("utf-8"))
        process.stdin.flush()

    def read(self):
        line = self.process.stdout.readline()
        if not line:
            raise Exited("advserve ended (exit %s)" % self.process.poll())
        return json.loads(line)

    def request(self, session: int, call: str, **fields):
        """`call` for `session`: its value, or the reference's own raise."""
        with self.lock:
            self.depth += 1
            try:
                if self.depth == 1 and self.gone:
                    closing, self.gone[:] = list(self.gone), []
                    self.next_id += 1
                    self.write({"id": self.next_id, "call": "close", "session": 0, "sessions": closing})
                    self.pump()
                self.next_id += 1
                self.counts[call] = self.counts.get(call, 0) + 1
                self.write(dict(fields, id=self.next_id, call=call, session=session))
                reply = self.pump()
            finally:
                self.depth -= 1
        if "raised" in reply:
            owner = self.sessions.get(session)
            raise (owner.raised(reply) if owner is not None else RuntimeError(reply.get("raised")))
        return reply.get("ok")

    def pump(self):
        """Read until this request's reply, answering every question asked meanwhile."""
        while True:
            line = self.read()
            if "reply" in line:
                return line["reply"]
            owner = self.sessions.get(line.get("session"))
            try:
                if owner is None:
                    raise RuntimeError("no such session")
                answer = {"answer": owner.answer(line)}
            except BaseException as error:     # noqa: BLE001 - every raise is the test's answer, said by class
                answer = raised_answer(error)
            self.write(answer)


def raised_answer(error) -> dict:
    """What a hook (or a source) raised, as car-adv's `Raised`: the class, the class it came from, and the advanced
    edition's frames it passed (`runtime._said_raised`'s words)."""
    import traceback
    cause = getattr(error, "__cause__", None) or getattr(error, "__context__", None)
    said = ""
    try:
        import codex_auto_resume_advanced
        package = os.path.normcase(os.path.dirname(os.path.abspath(codex_auto_resume_advanced.__file__))) + os.sep
        frames = [frame for frame in traceback.extract_tb(error.__traceback__)
                  if os.path.normcase(os.path.abspath(frame.filename)).startswith(package)]
        said = " < ".join("%s:%s %s" % (os.path.basename(frame.filename), frame.lineno, frame.name)
                          for frame in reversed(frames[-6:]))
    except Exception:
        pass
    return {"raise": type(error).__name__, "cause": type(cause).__name__ if cause is not None else None,
            "at": said or None}


PIPE = Pipe()


def _say_counts():
    named = os.environ.get("CODEX_AR_ADVPROXY_COUNT")
    if named and PIPE.counts:
        with open(named, "a", encoding="utf-8") as out:
            out.write(json.dumps({"pid": os.getpid(), "counts": PIPE.counts}) + "\n")


import atexit  # noqa: E402
atexit.register(_say_counts)

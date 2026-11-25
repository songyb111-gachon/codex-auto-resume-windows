"""What the advanced store's diffs share (seat S7.1a): the reference runner, the Rust harness, the dump.

One request - a scratch home, a pinned clock, the registry, a token counter and a list of operations - runs through
the reference tag's own `codex_auto_resume_advanced` (advreference.py: the tag's core and advanced trees, the
advanced lane's path and CODEX_AR_EDITION=advanced) and through car-adv's `advstore` example
(advanced/rust/crates/car-adv/examples/advstore.rs), each on its own copy of the home; both write one JSON line per
operation, and every file they leave is dumped in a stable order (`dump_home`). `secrets.token_hex` is a counter in
both, the only randomness the store has.

Not loaded by run.py on its own (no `diffs_` prefix): diffs_advstore.py is.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.parse

from rustdiff import advreference

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "advanced" / "rust"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CLOCK = 1_764_000_000.0
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER = "0a1b2c3d-0001-7000-8000-000000000002"
# Answers whose sentence is the store's own (a static reason), compared word for word; any other exception by class.
OWN = {"StateError", "StaleGeneration", "Refused", "SteerRefused", "ProfileError", "Locked", "PutBackWaits",
       "ImageRefused", "AuthFileError"}


def key(index: int) -> str:
    """An interruption or record id: 64 hex digits."""
    return "%064x" % (0xA11CE000 + index)


def thread(index: int) -> str:
    return "0a1b2c3d-0001-7000-8000-%012d" % index


def binary() -> Path:
    named = os.environ.get("CODEX_AR_ADVSTORE_EXE")
    if named:
        return Path(named)
    target = Path(os.environ.get("CARGO_TARGET_DIR") or WORKSPACE / "target")
    return target / "release" / "examples" / "advstore.exe"


def build() -> None:
    """`cargo build --release --locked -p car-adv --example advstore` in the advanced workspace."""
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "2")
    subprocess.run(["cargo", "build", "--release", "--locked", "-p", "car-adv", "--example", "advstore"],
                   cwd=str(WORKSPACE), env=environment, check=True, creationflags=NO_WINDOW, timeout=3600)


RUNNER = r'''
import enum, json, sqlite3, sys, time, types
from pathlib import Path
request = json.loads(open(sys.argv[1], encoding="utf-8").read())
counter = [request.get("tokens", 0)]
import secrets
def token_hex(nbytes=32):
    counter[0] += 1
    return format(counter[0], "0%dx" % (2 * nbytes))
secrets.token_hex = token_hex
from codex_auto_resume import config
from codex_auto_resume.domain.plug import DEFER
from codex_auto_resume_advanced import state as state_package
from codex_auto_resume_advanced.registry import REGISTRY, Registry
clock = [request.get("clock", 0.0)]
home = Path(request["home"])
paths = config.Paths(str(home))
registry = Registry(()) if request.get("registry") == "none" else REGISTRY
state = state_package.AdvancedState(paths, registry=registry, clock=lambda: clock[0])
BYTES = {"data", "auth", "put_in", "previous"}

def canon(value):
    if value is DEFER:
        return "DEFER"
    if isinstance(value, enum.Enum):
        value = value.value
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    if isinstance(value, sqlite3.Row):
        value = dict(value)
    if isinstance(value, dict):
        if all(isinstance(name, str) for name in value):
            return {str(name): canon(item) for name, item in value.items()}
        return {"__pairs__": [[canon(name), canon(item)] for name, item in value.items()]}
    if isinstance(value, (list, tuple)):
        return [canon(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(canon(item) for item in value)
    return repr(value)

def raised(exc):
    word = getattr(exc, "refusal", None)
    if word is None:
        word = getattr(exc, "reason", None)
    return {"raised": type(exc).__name__, "message": str(exc), "word": None if word is None else str(word)}

def bytes_in(arguments, keywords):
    arguments = [bytes(item) if isinstance(item, list) and all(isinstance(x, int) for x in item) else item
                 for item in arguments]
    keywords = {name: bytes(item) if name in BYTES and isinstance(item, list) else item
                for name, item in keywords.items()}
    return arguments, keywords

def operate(op):
    args, kwargs = op.get("args", []), op.get("kwargs", {})
    if "clock" in op:
        clock[0] = op["clock"]
        return None
    if "method" in op:
        name = op["method"]
        if name.startswith("fn."):
            from codex_auto_resume_advanced.state import choices
            return getattr(choices, name[3:])(*args, **kwargs)
        return getattr(state, name)(*args, **kwargs)
    if "scoped" in op:
        view = op["scoped"]
        on = view.get("on")
        verdict = view.get("verdict")
        armed = view.get("armed")
        scoped = state.scoped(view["capability"], on=None if on is None else (lambda: on),
                              verdict=None if verdict is None else (lambda measurement: verdict.get(measurement)),
                              armed=None if armed is None else (lambda other: armed.get(other) is True))
        target = scoped
        for part in op["name"].split("."):
            target = getattr(target, part)
        return target(*args, **kwargs)
    if "ledger" in op:
        from codex_auto_resume_advanced.ledger import ClaimLedger
        connection = sqlite3.connect(str(home / "config" / "state.sqlite"), timeout=10, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                ledger = ClaimLedger(state)
                if op["ledger"] == "record":
                    found = ledger.record(connection, op.get("record"), op["now"])
                else:
                    acted = op.get("acted") or ()
                    if isinstance(acted, dict):
                        acted = {name: frozenset(words) for name, words in acted.items()}
                    found = ledger.claim(connection, op.get("record"), op["now"], acted=acted,
                                         verified=frozenset(op.get("verified") or ()),
                                         unvouched=op.get("unvouched") is True)
                connection.execute("ROLLBACK" if op.get("end") == "rollback" else "COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        finally:
            connection.close()
        return "DEFER" if found is DEFER else str(found)
    if "profiles" in op:
        from codex_auto_resume_advanced import profiles
        if op["profiles"].startswith("fn."):
            from codex_auto_resume_advanced.codex.account import mask
            fn = {"fn.reading": profiles.reading, "fn.mask": mask,
                  "fn.is_id": lambda text: bool(isinstance(text, str) and profiles._ID.match(text))}[op["profiles"]]
            return fn(*args, **kwargs)
        import contextlib
        store = profiles.Profiles(home, seal=lambda data: b"SEALED:" + bytes(data),
                                  open_=lambda blob: blob[len(b"SEALED:"):] if blob.startswith(b"SEALED:")
                                  else (_ for _ in ()).throw(OSError("not sealed")),
                                  clock=lambda: clock[0], lock=lambda directory, seconds: contextlib.nullcontext())
        args, kwargs = bytes_in(args, kwargs)
        name = op["profiles"]
        if name == "state":
            return store.state(*args, **kwargs)
        return getattr(store, name)(*args, **kwargs)
    if "images" in op:
        from codex_auto_resume_advanced import images
        args, kwargs = bytes_in(args, kwargs)
        name = op["images"]
        if name in ("read", "kind"):
            return getattr(images, name)(*args, **kwargs)
        return getattr(images, name)(paths, *args, **kwargs)
    if "watchlog" in op:
        from codex_auto_resume_advanced import watchlog
        runtime = types.SimpleNamespace(registry=registry, state=state, clock=lambda: clock[0])
        if op["watchlog"] == "view":
            return watchlog.view(runtime, *args, **kwargs)
        return watchlog.exported(runtime)
    raise AttributeError("no such operation")

ready, go = request.get("ready"), request.get("go")
if ready and go:
    state.exists()
    Path(ready).write_text("ready")
    started = time.time()
    while not Path(go).exists() and time.time() - started < 60:
        time.sleep(0.005)
lines = []
for op in request.get("ops", []):
    try:
        lines.append({"ok": canon(operate(op))})
    except Exception as exc:
        lines.append(raised(exc))
state.close()
sys.stdout.write("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines))
'''


def _request_file(folder: Path, request: dict) -> Path:
    path = folder / ("request-%d.json" % len(list(folder.glob("request-*.json"))))
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def run_reference(home: Path, request: dict, *, tag: str | None = None) -> list:
    """The reference's answers to `request` on `home` (one dict per operation)."""
    request = dict(request, home=str(home))
    path = _request_file(home.parent, request)
    done = advreference.run(RUNNER, str(path), profile=home.parent / "profile", tag=tag)
    if done.returncode != 0:
        raise AssertionError("the reference failed:\n%s" % done.stderr.decode("utf-8", "replace")[-3000:])
    return [json.loads(line) for line in done.stdout.decode("utf-8").splitlines() if line.strip()]


def run_rust(home: Path, request: dict) -> list:
    """car-adv's answers to `request` on `home`."""
    request = dict(request, home=str(home))
    path = _request_file(home.parent, request)
    environment = advreference.reference.scratch_environment(home.parent / "profile")
    done = subprocess.run([str(binary()), str(path)], capture_output=True, env=environment,
                          creationflags=NO_WINDOW, timeout=600)
    if done.returncode != 0:
        raise AssertionError("advstore failed:\n%s" % done.stderr.decode("utf-8", "replace")[-3000:])
    return [json.loads(line) for line in done.stdout.decode("utf-8").splitlines() if line.strip()]


def popen_reference(home: Path, request: dict) -> subprocess.Popen:
    request = dict(request, home=str(home))
    path = _request_file(home.parent, request)
    (home.parent / "profile").mkdir(exist_ok=True)
    return advreference.popen(RUNNER, str(path), profile=home.parent / "profile")


def popen_rust(home: Path, request: dict) -> subprocess.Popen:
    request = dict(request, home=str(home))
    path = _request_file(home.parent, request)
    environment = advreference.reference.scratch_environment(home.parent / "profile")
    return subprocess.Popen([str(binary()), str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=environment, creationflags=NO_WINDOW)


def comparable(answer: dict) -> str:
    """An answer as it is compared: a value whole (keys sorted, a dict's key order being Python's set order in
    places), an exception by class - and by its sentence and word where the sentence is the store's own."""
    if "raised" in answer:
        kept = {"raised": answer["raised"], "word": answer.get("word")}
        if answer["raised"] in OWN:
            kept["message"] = answer["message"]
        return json.dumps(kept, sort_keys=True)
    return json.dumps(answer, sort_keys=True, ensure_ascii=False)


# A file another seat's crate writes, with a difference that is that crate's: car-config's Paths.ensure() writes the
# marker without Python's text-mode line end (LF, where `write_text` writes CRLF on Windows) - reported, not hidden
# elsewhere: only its line ends are folded here.
KNOWN = {"config/.owned-by-codex-auto-resume", "logs/.owned-by-codex-auto-resume"}


def _typed(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, float):
        return ["float", repr(value)]
    return [type(value).__name__, value]


def dump(path: Path) -> dict:
    """A SQLite file's shape and contents in a stable order."""
    uri = "file:%s?mode=ro" % urllib.parse.quote(Path(path).as_posix(), safe="/:")
    connection = sqlite3.connect(uri, uri=True)
    try:
        answer = {name: connection.execute("PRAGMA %s" % name).fetchone()[0]
                  for name in ("user_version", "application_id", "journal_mode", "page_size", "encoding")}
        schema = sorted(list(row) for row in connection.execute(
            "SELECT type, name, tbl_name, coalesce(sql, '') FROM sqlite_master"))
        answer["schema"] = schema
        tables = {}
        for kind, name, _table, _sql in schema:
            if kind != "table":
                continue
            columns = [row[1] for row in connection.execute('PRAGMA table_info("%s")' % name)]
            tables[name] = {"columns": columns, "rows": [
                [_typed(value) for value in row]
                for row in connection.execute('SELECT * FROM "%s" ORDER BY rowid' % name)]}
        answer["tables"] = tables
        answer["integrity"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return answer
    finally:
        connection.close()


def dump_home(home: Path) -> dict:
    """Every file the store left under `home`: SQLite files dumped, the saved accounts unsealed (never compared as
    sealed bytes), everything else by its bytes' digest; names relative to the home, the transient journal left out."""
    import hashlib
    found = {}
    for path in sorted(home.rglob("*")):
        relative = path.relative_to(home).as_posix()
        if path.is_dir():
            found[relative] = "folder"
            continue
        if path.name.endswith("-journal"):
            continue
        data = path.read_bytes()
        if relative in KNOWN:
            data = data.replace(b"\r\n", b"\n")
        if data.startswith(b"SQLite format 3\x00"):
            found[relative] = dump(path)
        elif data.startswith(b"SEALED:"):
            try:
                found[relative] = {"unsealed": json.loads(data[len(b"SEALED:"):].decode("utf-8"))}
            except ValueError:
                found[relative] = {"unsealed bytes": data[len(b"SEALED:"):].hex()}
        else:
            found[relative] = hashlib.sha256(data).hexdigest()
    return found


class Twin:
    """One case's two homes - the reference's and Rust's - made from one setup, in a scratch folder of its own."""

    def __init__(self, setup=None):
        self.folder = Path(tempfile.mkdtemp(prefix="advstore-"))
        self.source = self.folder / "source" / "home"
        self.source.mkdir(parents=True)
        (self.folder / "source" / "profile").mkdir()
        if setup is not None:
            setup(self.source)
        self.python = self.folder / "python" / "home"
        self.rust = self.folder / "rust" / "home"
        for target in (self.python, self.rust):
            shutil.copytree(self.source, target)
            (target.parent / "profile").mkdir(exist_ok=True)

    def close(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def run(self, request: dict) -> tuple:
        return (homeless(run_reference(self.python, request), self.python),
                homeless(run_rust(self.rust, request), self.rust))


def homeless(answers: list, home: Path) -> list:
    """`answers` with the home's own path written `<home>` (a picture's copy is answered by its path)."""
    text = json.dumps(answers, ensure_ascii=False)
    for form in {str(home), str(home.resolve()), os.path.realpath(str(home))}:
        text = text.replace(json.dumps(form)[1:-1], "<home>")
    return json.loads(text)

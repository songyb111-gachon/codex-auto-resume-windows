"""A tagged release's whole package, run in a process of its own.

From v0.6.10-alpha the store is a package, so an older release's store can no longer be loaded as
one file the way `tests/test_control_v3.py` loads v0.5's. Here the tag's `src/codex_auto_resume`
is taken out of git into a temporary folder, once per tag, and a short script runs against it in
a separate Python - so the release's modules never meet this checkout's in one interpreter, and
what the script prints (one JSON value) is the answer.

Temporary folders only: every home a release could look for - the profile, AppData, Codex's and
this product's - points into one, so nothing real is read or written, and the process is started
with no console window (tests/test_no_console_windows.py).

Skipped where the tag is not in the checkout, except on CI, which fetches the tags: there a
missing tag is a failure, not a quiet skip.

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import atexit
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_EXTRACTED: dict = {}


def package(tag: str) -> Path:
    """The `src` folder holding `tag`'s `codex_auto_resume`, taken out of git once - with the plugin
    manifest beside it, where the release reads its own version, so it knows which one it is."""
    if tag in _EXTRACTED:
        return _EXTRACTED[tag]
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", tag, "src/codex_auto_resume",
                              ".codex-plugin/plugin.json"],
                             capture_output=True, creationflags=NO_WINDOW)
    if archive.returncode != 0:
        if os.environ.get("CI"):
            raise AssertionError("%s is not in this checkout; CI must fetch the tags" % tag)
        raise unittest.SkipTest("%s is not in this checkout" % tag)
    folder = Path(tempfile.mkdtemp(prefix="released-%s-" % tag))
    atexit.register(shutil.rmtree, folder, True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(folder, filter="data")
    _EXTRACTED[tag] = folder / "src"
    return _EXTRACTED[tag]


def run(tag: str, script: str, *arguments):
    """Run `script` under `tag`'s package with `arguments` as sys.argv[1:], and return the one
    JSON value it prints. A script that fails fails the test, with the end of what it said."""
    source = package(tag)
    with tempfile.TemporaryDirectory(prefix="released-home-") as home:
        environment = dict(os.environ, PYTHONPATH=str(source), **{name: home for name in (
            "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "CODEX_HOME", "CODEX_AUTO_RESUME_HOME")})
        done = subprocess.run([sys.executable, "-c", script, *map(str, arguments)], capture_output=True,
                              text=True, encoding="utf-8", env=environment, cwd=home,
                              creationflags=NO_WINDOW, timeout=300)
    if done.returncode != 0:
        raise AssertionError("%s's script failed:\n%s" % (tag, done.stderr[-3000:]))
    return json.loads(done.stdout)


# ------------------------------------------------------------------------ v0.6.10's own state
V0610 = "v0.6.10"
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER = "0a1b2c3d-0001-7000-8000-000000000002"


def turn(index: int) -> str:
    return "0a1b2c3d-0002-7000-8000-%012d" % index


def key(index: int) -> str:
    """A record's interruption id whose first 16 hex digits are its own: `ab` repeated, say."""
    return ("%02x" % (index + 1)) * 32


# One record in each state the store knows, on THREAD, and OTHER switched off - written through
# the release's own store, and the states set the way `tests/test_downgrade.py` sets them.
_WRITE_STATE = r'''
import json, sqlite3, sys
from pathlib import Path
from codex_auto_resume import machine
from codex_auto_resume.store import Store
root, thread, other = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
turn = lambda index: "0a1b2c3d-0002-7000-8000-%012d" % index
key = lambda index: ("%02x" % (index + 1)) * 32
states = sorted(machine.STATES)
with Store(root) as store:
    store.set_enabled(True, 100.0)
    for index, state in enumerate(states):
        store.register({"thread_id": thread, "turn_id": turn(index), "completed_at": 110.0,
                        "started_at": 105.0, "ordinal": index, "interruption_id": key(index),
                        "reset_at": None, "limit_type": "x", "uncertain": False,
                        "category": "server_5xx"}, 100.0)
    store.set_thread_enabled(other, False)
db = sqlite3.connect(root / "state.sqlite")
for index, state in enumerate(states):
    db.execute("UPDATE interruptions SET state=?, submitted_at=?, recovery_turn_id=?, withdraw_reason=?, "
               "withdrawn_at=?, cancel_requested=? WHERE interruption_id=?",
               (state, None if state in machine.WAITING else 101.0,
                None if state in machine.WAITING else turn(100 + index),
                "cancel" if state == "withdrawn_unconfirmed" else None,
                101.0 if state == "withdrawn_unconfirmed" else None,
                1 if state == "cancelled" else 0, key(index)))
db.commit()
db.close()
with Store(root) as store:
    print(json.dumps({"version": store.schema_version(),
                      "states": {row["interruption_id"]: row["state"] for row in store.all_records()}}))
'''

# What the release's store makes of a state: whether it opens it, every record's state, marker and
# schedule, the switches, and - for the keys named - what a claim of each is answered at `now`.
_READ_STATE = r'''
import json, sys
from pathlib import Path
from codex_auto_resume.store import Store
root, now, claims = Path(sys.argv[1]), float(sys.argv[2]), [k for k in sys.argv[3].split(",") if k]
try:
    store = Store(root)
except Exception as exc:
    print(json.dumps({"refused": type(exc).__name__}))
    raise SystemExit(0)
with store:
    answer = {"version": store.schema_version(), "settings": store.settings(),
              "disabled": sorted(store.disabled_threads()),
              "records": {row["interruption_id"]: {name: row[name] for name in (
                  "state", "marker", "next_retry_at", "queue_id", "last_error", "cancel_requested")}
                  for row in store.all_records()}}
    answer["claims"] = {k: list(store.reserve_detailed(k, now)) for k in claims}
print(json.dumps(answer))
'''


def write_v3_state(root) -> dict:
    """A state as v0.6.10 writes it, in `root`: {"version": 3, "states": {key: state}}."""
    return run(V0610, _WRITE_STATE, root, THREAD, OTHER)


def read_state(root, now=None, claims=()) -> dict:
    """What v0.6.10's store makes of the state in `root` (see _READ_STATE)."""
    return run(V0610, _READ_STATE, root, 4102444800.0 if now is None else now, ",".join(claims))

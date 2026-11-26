"""What the courier's diffs share (seat S7.3b): the reference's fakes and the Rust example `advcourier`.

A family is a script run under the reference tag's own advanced edition (`advref.run` through `advreport.ReportDiff`):
it asks the tag's courier the question of each case and records the answer; the same cases go to car-adv's example
`advcourier` (advanced/rust/crates/car-adv/examples/advcourier), and every answer must equal the tag's, as the wire
writes it. A case with a home names the reference's scratch home; the Rust side makes its own beside it (`<home>-rust`),
and `same_states` holds the two advanced.sqlite files equal table by table.

No network: every opener is a scripted fake that records the request exactly as urllib's `Request` holds it (address,
method, capitalised headers, body, timeout); every secret is a dict on one side and car-platform's memory backend on the
other; the loopback server binds 127.0.0.1 on a port of its own and is spoken to with raw bytes; every token, address
and chat id is made up (the shapes of real ones, never real ones).

Not loaded by run.py on its own (no `diffs_` prefix): diffs_advcourier_*.py are.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from rustdiff import advreport

# Prepended to every family's script, after advreport.PRELUDE.
FAKES = r'''
import builtins, io, socket, ssl, threading, types, urllib.error
import codex_auto_resume_advanced as _package
from codex_auto_resume import config
from codex_auto_resume_advanced.registry import REGISTRY
from codex_auto_resume_advanced import state as state_package
from codex_auto_resume_advanced.courier import address, keep, feed, outbox, channels, http, telegram, api, page
from codex_auto_resume_advanced.control import remote
from codex_auto_resume_advanced.engine import push
from codex_auto_resume_advanced.vocabulary import ArmingState, OptionKey, Actor
LOCALES = str(Path(_package.__file__).parent / "locales")

def home_of(name):
    found = Path(SCRATCH) / name
    found.mkdir(parents=True, exist_ok=True)
    return str(found)

class Probe:
    def __init__(self, home, now, states):
        self.paths = config.Paths(home)
        self.registry = REGISTRY
        self.now = [now]
        self.state = state_package.AdvancedState(self.paths, registry=REGISTRY, clock=lambda: self.now[0])
        self._states = {key: ArmingState(value) for key, value in (states or {}).items()}
        self._unreadable = False
        self.trips = []
        self.arming = types.SimpleNamespace(trip=lambda capability, reason: self.trips.append([capability, str(reason)]) or True)

    def clock(self):
        return self.now[0]

    def states(self, fresh=False):
        return dict(self._states)

class Secrets:
    def __init__(self, kept):
        self.kept = dict(kept)

    def read(self, capability, name):
        return self.kept.get(name)

    def write(self, capability, name, secret):
        self.kept[name] = secret

    def delete(self, capability, name):
        return self.kept.pop(name, None) is not None

class Reply:
    def __init__(self, script):
        self.script = script
        self.status = script.get("status")
        self.body = bytes(script.get("body") or [])
        if script.get("expired"):
            whole = http._Whole(1000)
            whole.cancel()
            whole.expired = True
            self.whole = whole

    def read(self, n):
        kind = self.script.get("read_raise")
        if kind == "timeout":
            raise socket.timeout()
        if kind:
            raise getattr(builtins, kind)()
        return self.body[:n]

    def close(self):
        pass

class Opener:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def open(self, request, timeout=None):
        self.seen.append({"url": request.full_url, "method": request.get_method(),
                          "headers": [list(item) for item in request.header_items()],
                          "body": list(request.data) if request.data is not None else None, "timeout": timeout})
        if not self.replies:
            raise urllib.error.URLError("no reply")
        script = self.replies.pop(0)
        kind = script.get("raise")
        if kind == "HTTPError":
            raise urllib.error.HTTPError(request.full_url, script.get("code"), "refused", {}, None)
        if kind == "URLError_ssl":
            raise urllib.error.URLError(ssl.SSLError())
        if kind == "URLError":
            raise urllib.error.URLError("no way there")
        if kind == "timeout":
            raise socket.timeout()
        if kind == "OSError":
            raise OSError()
        if kind:
            raise getattr(builtins, kind)()
        return Reply(script)

def failure(error):
    return {"error": type(error).__name__, "word": getattr(error, "word", None)}

class Layer:
    """The tests' control layer: its rows, and every act asked of it."""
    def __init__(self, rows):
        self.rows = rows
        self.asked = []

class _Open:
    def __init__(self, rows):
        self.rows = rows
    def __enter__(self):
        return types.SimpleNamespace(pending=lambda: list(self.rows))
    def __exit__(self, *unused):
        return False

def layer_of(rows):
    made = Layer(rows)
    made._open = lambda legacy_ok=False: _Open(rows)
    made.set_enabled = lambda enabled: made.asked.append(["set_enabled", enabled]) or {"enabled": enabled}
    made.cancel_interruption = lambda key, actor=None: made.asked.append(["cancel", key, actor]) or {"changed": True}
    made.release_hold = lambda key, thread, actor=None: made.asked.append(["release", key, thread, actor])
    return made
'''


def dump(home: Path) -> dict:
    """Every table of the advanced state under `home`, rows in their order."""
    found = list(Path(home).rglob("advanced.sqlite"))
    if not found:
        return {}
    connection = sqlite3.connect(str(found[0]))
    try:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {table: [list(row) for row in connection.execute("SELECT * FROM %s ORDER BY rowid" % table)]
                for table in tables}
    finally:
        connection.close()


class CourierDiff(advreport.ReportDiff):
    """A diff of the courier: `family(FAKES + script)` in the tag and the same cases in `advcourier`."""

    EXAMPLE = "advcourier"

    def courier(self, script: str, *, label: str, expect_cases: int = 1, homes=()) -> dict:
        done = self.family(FAKES + script, label=label, expect_cases=expect_cases)
        for name in homes:
            self.same_states(done["folder"], name)
        return done

    def same_states(self, folder: Path, name: str) -> None:
        reference, rust = dump(folder / name), dump(Path(str(folder / name) + "-rust"))
        self.assertTrue(reference, "%s: the reference wrote no state" % name)
        self.assertEqual(sorted(reference), sorted(rust), name)
        for table in reference:
            self.assertEqual(rust[table], reference[table], "%s: table %s differs" % (name, table))

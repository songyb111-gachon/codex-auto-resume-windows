"""What the S6.0 diffs (diffs_surface_*.py) share: car-surface's cases, run through the reference and through Rust.

A family is a script that runs under the reference tag's own Python and prints the cases it made and what the tag
answered (`leaves.PRELUDE`'s `finish`); the same cases go to `car-harness serve` as `surface.batch` calls, and every
answer must be the same bytes. `SURFACE` is what each family script adds to the prelude: the stand-ins both sides
use, written once here and once in rust/crates/car-harness/src/surface.rs, so the two see the same world.

* No toast, no window, no registration: `notify.show`'s PowerShell is a recorder of the argv, the argument
  variables, the creation flags, the streams and the timeout it would have been given (`pwsh.subprocess` replaced;
  Rust: a recording `Starter` under car-platform's own `pwsh::run`); `open_in_codex`'s explorer.exe is a recorder
  (`codex_link.subprocess` replaced; Rust: a recording `Launch`); the presence probes are the case's answers; the
  card host's wake is the case's script; nothing reaches `notice_presence.snapshot`.
* The language is the case's (`l10n.set_preference(locale)`; Rust: `Speech { locale }`), and Windows' preferred
  languages are `["en-US"]` on both sides, so `system` reads the same everywhere.
* The local clock is this PC's on both sides (`time.localtime`; Rust: car-policy's `Crt`, the C runtime CPython
  calls), as diffs_classify_policy's zone `"local"` is.
* `measure` is the renderer's stand-in: a width of 7 per ASCII character and 13 per other, scaled by the role's
  size, and a height of lines times the role's line, wrapping where a line is wider than it may be.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from rustdiff import core, reference
from rustdiff.leaves import PRELUDE, Leaves

SURFACE = r'''
import dataclasses, os, subprocess as _real_subprocess, types
from codex_auto_resume import l10n
l10n._windows_preferred = lambda: ["en-US"]

def speak(locale):
    l10n.set_preference(locale)

def notice_out(notice):
    if notice is None:
        return None
    return {field.name: getattr(notice, field.name) for field in dataclasses.fields(notice)}

SIZES = {"label": 14, "chip": 12, "name": 15, "body": 14, "small": 12, "button": 14}

def measure(role, text, width, wrap):
    size = SIZES.get(role, 13)
    w = sum(7 if ord(c) < 128 else 13 for c in str(text)) * size // 10
    lines = 1
    if wrap and width > 0 and w > width:
        lines = -(-w // width)
        w = width
    return (w, lines * (size + 6))

class Raised(Exception):
    pass

BUILTIN = {"OSError": OSError, "ValueError": ValueError, "KeyError": KeyError, "TypeError": TypeError,
           "PermissionError": PermissionError, "FileNotFoundError": FileNotFoundError, "RuntimeError": RuntimeError}

def raiser(spec):
    """{"raise": class name, "code": code}: an exception of that class's name carrying the code (when given), as the
    control layer's refusals are."""
    name = spec["raise"]
    error = (BUILTIN.get(name) or type(name, (Exception,), {}))("refused")
    if "code" in spec:
        error.code = spec["code"]
    return error

def answer(spec):
    """A stand-in's answer: the value, or the exception a {"raise": ...} spec names."""
    if isinstance(spec, dict) and "raise" in spec:
        raise raiser(spec)
    return spec

class Recorder:
    """subprocess as pwsh and codex_link use it, recording what would have been started."""
    DEVNULL = _real_subprocess.DEVNULL
    SubprocessError = _real_subprocess.SubprocessError
    TimeoutExpired = _real_subprocess.TimeoutExpired
    CREATE_NO_WINDOW = _real_subprocess.CREATE_NO_WINDOW

    def __init__(self):
        self.calls, self.outcome = [], 0

    def _stream(self, value):
        return "null" if value == self.DEVNULL else "inherit" if value is None else "other"

    def run(self, args, env=None, stdin=None, stdout=None, stderr=None, timeout=None, shell=None, creationflags=0):
        self.calls.append({"argv": list(args),
                           "env": [[k, v] for k, v in (env or {}).items() if k.upper().startswith("CODEX_AUTO_RESUME_ARG_")],
                           "flags": creationflags, "timeout": timeout,
                           "streams": [self._stream(stdin), self._stream(stdout), self._stream(stderr)]})
        if self.outcome == "oserror":
            raise OSError("not started")
        if self.outcome == "timeout":
            raise _real_subprocess.TimeoutExpired(args, timeout)
        return types.SimpleNamespace(returncode=self.outcome)

    def Popen(self, args, close_fds=False, creationflags=0, **rest):
        self.calls.append({"argv": list(args), "flags": creationflags, "close_fds": close_fds})
        if self.outcome == "oserror":
            raise OSError("not started")
        return types.SimpleNamespace(pid=0)
'''


class Surface(Leaves):
    """A diff of car-surface: `family(script)` runs the script in the reference and the same cases in Rust."""

    def family(self, script: str, *arguments, label: str, expect_ops: int = 1, chunk: int = 2000) -> dict:
        profile = self.profile("reference-%s" % label)
        made = reference.run(PRELUDE + SURFACE + script, *arguments, profile=profile)
        self.assertEqual(made.returncode, 0, made.stderr[-3000:].decode("utf-8", "replace"))
        done = json.loads(made.stdout.decode("utf-8"))
        cases, expected = done["cases"], done["results"]
        self.assertGreaterEqual(len(cases), expect_ops, label)
        actual = []
        with core.Harness(reference.scratch_environment(self.profile("rust-%s" % label))) as harness:
            for start in range(0, len(cases), chunk):
                number, line = harness.call("surface.batch", cases=cases[start:start + chunk],
                                            scratch=str(profile))
                reply = json.loads(line.decode("utf-8"))
                self.assertEqual(reply.get("id"), number, line[:300])
                self.assertTrue(reply["reply"].get("ok"), line[:600])
                actual += reply["reply"]["value"]
        self.assertEqual(len(actual), len(expected))
        # Both sides' answers are already in the channel's form (the reference's tagged by `finish`, Rust's by
        # car-harness), so they are compared as the JSON they are.
        for index, (want, got) in enumerate(zip(expected, actual)):
            wanted, gotten = (json.dumps(each, ensure_ascii=False, allow_nan=False) for each in (want, got))
            if wanted != gotten:
                dump = os.environ.get("CAR_SURFACE_DUMP")
                if dump:
                    Path(dump).write_text(json.dumps({"case": cases[index], "reference": want, "rust": got},
                                                     ensure_ascii=False), encoding="utf-8")
                at = next((i for i, (p, q) in enumerate(zip(wanted, gotten)) if p != q), min(len(wanted), len(gotten)))
                start = max(0, at - 300)
                self.fail("%s: case %d differs at character %d\n  case      %s\n  reference ...%s\n  rust      ...%s" % (
                    label, index, at, json.dumps(cases[index], ensure_ascii=False)[:600], wanted[start:at + 300],
                    gotten[start:at + 300]))
        return {"cases": cases, "results": expected}


def counted(done: dict, prefix: str) -> int:
    """How many cases of a family name an op starting with `prefix`."""
    return sum(1 for case in done["cases"] if str(case[0]).startswith(prefix))

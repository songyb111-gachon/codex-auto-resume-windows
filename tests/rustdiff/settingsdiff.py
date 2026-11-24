"""What the S2.2 diffs (diffs_settings_*.py) share: a family of cases run through the reference and through Rust.

Like leaves.py, but for car-policy's settings and plug: a family is a script that runs under the reference tag's own
Python and prints `{"cases": [[op, arg, ...], ...], "results": [...]}`, each result `{"ok": value}` or
`{"error": class, ...}` with what the exception carries (a settings refusal's sentence, an Unreadable's reason and
whether it is transient, a ConfigError's or a KindError's sentence). The same cases go to `car-harness serve` as
`policy.batch` calls, and every answer must be the same value, keys in the same order.

The cases travel as Python's `json` writes them with `ensure_ascii` - a NaN, an int of any size and half of a
surrogate pair included - and car-harness reads that line as `json.loads` does (`policy.rs`), because the settings
files hold all three. Not a test module (no `test` in its name, and not `diffs_*`): run.py imports it through them.
"""
from __future__ import annotations

import json

from rustdiff import core, diffs, reference

PRELUDE = r'''
import json, os, random, sys, tempfile, shutil, stat, ctypes
from pathlib import Path

def norm(value):
    if isinstance(value, (set, frozenset)):
        return sorted(norm(each) for each in value)
    if isinstance(value, (tuple, list)):
        return [norm(each) for each in value]
    if isinstance(value, dict):
        return {key: norm(each) for key, each in value.items()}
    return value

MESSAGES = ("SettingsError", "Unreadable", "ConfigError", "KindError")
WITH_MESSAGE = set()

def failure(op, error):
    out = {"error": type(error).__name__}
    names = [kind.__name__ for kind in type(error).__mro__]
    if any(name in MESSAGES for name in names) or op in WITH_MESSAGE:
        out["message"] = str(error)
    if type(error).__name__ == "Unreadable":
        out["reason"], out["transient"] = error.reason, error.transient
    return out

def run(cases, ops):
    results = []
    for case in cases:
        try:
            results.append({"ok": norm(ops[case[0]](*case[1:]))})
        except Exception as error:
            results.append(failure(case[0], error))
    return results

def finish(cases, ops):
    sys.stdout.write(json.dumps({"cases": cases, "results": run(cases, ops)}, ensure_ascii=True))

# ---- files: one scratch folder per case, the same layout and the same look afterwards as car-harness's policy.rs
GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel.CreateFileW.restype = ctypes.c_void_p
_kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                ctypes.c_uint32, ctypes.c_void_p]
_kernel.CloseHandle.argtypes = [ctypes.c_void_p]

def lay(target, setup):
    kind = setup.get("kind") if isinstance(setup, dict) else None
    if kind in ("bytes", "locked", "readonly"):
        target.write_bytes(bytes.fromhex(setup.get("hex", "")))
        if kind == "readonly":
            os.chmod(target, stat.S_IREAD)
        if kind == "locked":
            return _kernel.CreateFileW(str(target), GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
    elif kind == "dir":
        target.mkdir(parents=True, exist_ok=True)
    return None

def after(target):
    if target.is_file():
        if not os.access(target, os.W_OK):
            os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
        try:
            found = target.read_bytes().hex()
        except OSError:
            found = "unreadable"
    elif target.is_dir():
        found = "dir"
    else:
        found = None
    others = sorted(name for name in os.listdir(target.parent) if name != target.name)
    return {"file": found, "others": others}

def in_scratch(relative, setup, call):
    folder = Path(tempfile.mkdtemp(prefix="car-policy-ref-"))
    try:
        target = folder.joinpath(*relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = lay(target, setup)
        try:
            try:
                result = {"ok": norm(call(target, folder))}
            except Exception as error:
                result = failure("", error)
        finally:
            if handle:
                _kernel.CloseHandle(handle)
        return {"result": result, "after": after(target)}
    finally:
        shutil.rmtree(folder, ignore_errors=True)
'''


def same(want, got) -> bool:
    """Equal values, keys in the same order (a NaN equal to a NaN): compared as Python writes them."""
    return json.dumps(want, ensure_ascii=True) == json.dumps(got, ensure_ascii=True)


class Family(diffs.Base):
    """A diff of car-policy (S2.2): `family(script)` runs the script in the reference and the same cases in Rust."""

    def family(self, script: str, *arguments, label: str, expect: int = 1, chunk: int = 2000,
               stdin: bytes | None = None) -> dict:
        profile = self.profile("reference-%s" % label)
        made = reference.run(PRELUDE + script, *arguments, profile=profile, **({"stdin": stdin} if stdin else {}))
        self.assertEqual(made.returncode, 0, made.stderr[-3000:].decode("utf-8", "replace"))
        done = json.loads(made.stdout.decode("utf-8"))
        cases, expected = done["cases"], done["results"]
        self.assertGreaterEqual(len(cases), expect, label)
        actual = []
        with core.Harness(reference.scratch_environment(self.profile("rust-%s" % label))) as harness:
            for start in range(0, len(cases), chunk):
                harness.next_id += 1
                request = {"cases": cases[start:start + chunk], "id": harness.next_id, "call": "policy.batch"}
                harness.process.stdin.write((json.dumps(request, ensure_ascii=True) + "\n").encode("ascii"))
                harness.process.stdin.flush()
                line = harness.process.stdout.readline()
                reply = json.loads(line.decode("utf-8"))
                self.assertEqual(reply.get("id"), harness.next_id, line[:300])
                self.assertTrue(reply["reply"].get("ok"), line[:600])
                actual += reply["reply"]["value"]
        self.assertEqual(len(actual), len(expected))
        for index, (want, got) in enumerate(zip(expected, actual)):
            if not same(want, got):
                self.fail("%s: case %d differs\n  case      %s\n  reference %s\n  rust      %s" % (
                    label, index, json.dumps(cases[index], ensure_ascii=True)[:900],
                    json.dumps(want, ensure_ascii=True)[:900], json.dumps(got, ensure_ascii=True)[:900]))
        return {"cases": cases, "results": expected}

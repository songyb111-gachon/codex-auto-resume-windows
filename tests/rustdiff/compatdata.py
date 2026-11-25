"""Every compatibility data sequence and report count file the repository holds, for the S3.3 registry diffs.

`documents()`: the bundled data at every commit that changed it (git history of src/codex_auto_resume/data/
codex_compat.json), the frozen fixture, the advanced edition's data, the community fixtures, and documents made from
them that break one rule each (a sequence, a date, an expiry, a range, a state). `reported_files()`: the report counts
at every commit, the frozen fixtures and broken copies. Written into a scratch folder; nothing of the checkout moves.
Not a test module: the diffs import it.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from rustdiff import core

ROOT = core.ROOT
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def history(relative: str) -> list[tuple[str, bytes]]:
    """(commit, bytes) of every version of a file in the checkout's history, oldest first."""
    listed = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%h", "--", relative], capture_output=True,
                            check=True, creationflags=NO_WINDOW).stdout.decode().split()
    found = []
    for commit in reversed(listed):
        shown = subprocess.run(["git", "-C", str(ROOT), "show", "%s:%s" % (commit, relative)], capture_output=True,
                               creationflags=NO_WINDOW)
        if shown.returncode == 0:
            found.append((commit, shown.stdout))
    return found


def broken(document: dict) -> list[tuple[str, dict]]:
    """Copies of a valid document that each differ in one thing a reader judges."""
    out = []
    def copy(**changes):
        made = json.loads(json.dumps(document))
        made.update(changes)
        return made
    out.append(("sequence+1", copy(sequence=document.get("sequence", 0) + 1)))
    out.append(("sequence+101", copy(sequence=document.get("sequence", 0) + 101)))
    out.append(("sequence 0", copy(sequence=0)))
    out.append(("no expiry", {k: v for k, v in document.items() if k != "expires_at"}))
    out.append(("expired", copy(expires_at="2026-01-01T00:00:00Z")))
    out.append(("from the future", copy(published_at="2031-01-01T00:00:00Z", expires_at="2031-06-01T00:00:00Z")))
    out.append(("newer product", copy(min_product="9.0.0")))
    out.append(("product 0.6.27", copy(min_product="0.6.27")))
    engines = json.loads(json.dumps(document.get("engines", [])))
    for each in engines[:2]:
        for name, claim in list(each.get("capabilities", {}).items())[:3]:
            claim["state"] = "INCOMPATIBLE"
            claim["reason"] = "protocol_changed"
            claim.pop("verified_at", None)
    out.append(("incompatible claims", copy(engines=engines)))
    advisories = [{"id": "CAR-2026-0001", "affects": {"low": "codex-cli 0.150.0", "high": "codex-cli 0.160.0"},
                   "capabilities": ["exact_thread_recovery", "usage_probe", "nonsense"], "reason": "schema_changed"},
                  {"id": "CAR-2026-0002", "affects": {"low": "codex-cli 0.171.0"}, "capabilities": ["engine_present"],
                   "reason": "unknown_reason_word"}]
    out.append(("advisories", copy(advisories=advisories)))
    out.append(("an advisory with no range", copy(advisories=[{"id": "CAR-2026-0003", "affects": {},
                                                               "capabilities": ["queue_withdraw"],
                                                               "reason": "delivery_unverified"}])))
    return out


def documents(folder: Path) -> list[tuple[str, Path]]:
    """(name, path) of every document, written under `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    found = []
    for commit, data in history("src/codex_auto_resume/data/codex_compat.json"):
        path = folder / ("data-%s.json" % commit)
        path.write_bytes(data)
        found.append(("data at %s" % commit, path))
    for relative in ("tests/fixtures/codex_compat_frozen.json", "advanced/compat/codex_compat_advanced.json"):
        source = ROOT / relative
        if source.is_file():
            path = folder / (source.stem + ".json")
            path.write_bytes(source.read_bytes())
            found.append((relative, path))
    community = ROOT / "tests" / "fixtures" / "community"
    for source in sorted(community.glob("*.json")):
        path = folder / ("community-" + source.name)
        path.write_bytes(source.read_bytes())
        found.append(("community " + source.name, path))
    newest = json.loads((ROOT / "src/codex_auto_resume/data/codex_compat.json").read_text(encoding="utf-8"))
    for name, made in broken(newest):
        path = folder / ("broken-%s.json" % name.replace(" ", "-").replace("+", "plus"))
        path.write_text(json.dumps(made), encoding="utf-8")
        found.append(("newest, " + name, path))
    for name, data in (("empty", b""), ("not json", b"{"), ("a list", b"[]"), ("duplicate", b'{"a": 1, "a": 2}'),
                       ("nan", b'{"format": "codex-auto-resume-compat/1", "sequence": NaN}'),
                       ("signature", json.dumps(dict(newest, requires_signature=True)).encode()),
                       ("too large", b" " * (256 * 1024 + 1)), ("bom", b"\xef\xbb\xbf" + json.dumps(newest).encode())):
        path = folder / ("bad-%s.json" % name.replace(" ", "-"))
        path.write_bytes(data)
        found.append(("bad " + name, path))
    return found


def reported_files(folder: Path) -> list[tuple[str, Path]]:
    folder.mkdir(parents=True, exist_ok=True)
    found = []
    for commit, data in history("src/codex_auto_resume/data/reported.json"):
        path = folder / ("reported-%s.json" % commit)
        path.write_bytes(data)
        found.append(("reported at %s" % commit, path))
    frozen = ROOT / "tests" / "fixtures" / "reported_frozen.json"
    base = json.loads(frozen.read_text(encoding="utf-8")) if frozen.is_file() else {
        "format": "codex-auto-resume-reported/1", "versions": []}
    path = folder / "reported-frozen.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    found.append(("reported_frozen.json", path))
    entry = {"version": "codex-cli 0.171.0", "reports": 3, "worked": 2, "failed": 1, "neither": 0, "both": 0}

    def write(name, value):
        made = folder / ("reported-%s.json" % name)
        made.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        found.append(("reported " + name, made))

    good = {"format": "codex-auto-resume-reported/1", "versions": [entry]}
    write("good", good)
    write("comment", dict(good, _comment=["a", "b" * 200]))
    write("comment too long", dict(good, _comment=["b" * 201]))
    write("comment not text", dict(good, _comment=[1]))
    write("comment many", dict(good, _comment=["x"] * 41))
    write("other key", dict(good, extra=1))
    write("no versions", {"format": "codex-auto-resume-reported/1"})
    write("wrong format", dict(good, format="codex-auto-resume-reported/2"))
    write("versions not list", dict(good, versions={}))
    write("too many", dict(good, versions=[dict(entry, version="codex-cli 0.%d.0" % n) for n in range(501)]))
    write("five hundred", dict(good, versions=[dict(entry, version="codex-cli 0.%d.0" % n) for n in range(500)]))
    for name, change in (("both", dict(entry, worked=2, failed=2, both=1)), ("bad sum", dict(entry, both=1)),
                         ("bool", dict(entry, reports=True)), ("negative", dict(entry, neither=-1)),
                         ("huge", dict(entry, reports=100001)), ("zero", dict(entry, reports=0, worked=0, failed=0)),
                         ("not a version", dict(entry, version="0.171.0")), ("no prefix", dict(entry, version="x")),
                         ("extra key", dict(entry, extra=1)), ("float", dict(entry, worked=2.0)),
                         # the sum holds and `both` passes min(worked, failed): only that rule refuses it
                         ("both past the smaller", dict(entry, reports=1, worked=1, failed=0, neither=1, both=1))):
        write(name, dict(good, versions=[change]))
    write("duplicate version", dict(good, versions=[entry, entry]))
    write("duplicate key", '{"format": "codex-auto-resume-reported/1", "versions": [], "versions": []}')
    write("not json", "{")
    write("list", "[]")
    write("big", " " * (128 * 1024 + 1))
    return found

"""The profile-path scan of check_rebuild.sh: no shipped binary may carry the builder's Windows user name or a scratch path.

    python profile_scan.py WORK USER        scan WORK's target/release binaries; exit 1 on any hit
    python profile_scan.py --self-test      plant every case below in memory; exit 1 if one is judged wrongly

One allowance, and only one: the publisher's GitHub handle `songyb111-gachon`, which the binaries carry as their
publisher and which is public by the owner's choice (the release's own privacy scan, car-release's privacy_scan.py, allows
the handle the same way). A needle found inside an occurrence of that literal handle (UTF-8 or UTF-16LE, ASCII case
ignored) does not count; the same needle anywhere else - `C:\\Users\\<name>\\`, the name alone, the handle's first part
without the rest - still does. Stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ALLOWED = ("songyb111-gachon",)


def _spans(data: bytes, blob: bytes) -> list:
    """Every (start, end) of `blob` in `data`, ASCII case ignored."""
    found, low, needle, start = [], data.lower(), blob.lower(), 0
    while needle:
        at = low.find(needle, start)
        if at < 0:
            break
        found.append((at, at + len(needle)))
        start = at + 1
    return found


def hits(data: bytes, needle: str) -> list:
    """(form, offset) of every occurrence of `needle` in `data` that is not inside an allowed handle."""
    out = []
    for form, codec in (("utf-8", "utf-8"), ("utf-16", "utf-16-le")):
        allowed = [span for handle in ALLOWED for span in _spans(data, handle.encode(codec))]
        for start, end in _spans(data, needle.encode(codec)):
            if not any(low <= start and end <= high for low, high in allowed):
                out.append((form, start))
    return out


def needles_for(work: Path, user: str) -> set:
    found = {user, str(work), work.as_posix(), work.as_posix().replace("/", "\\"), "scratchpad"}
    found |= {part for part in work.parts if len(part) > 8 and part != "/"}
    return {each for each in found if each}


def scan(work: Path, user: str) -> int:
    needles = needles_for(work, user)
    bad = 0
    for path in sorted(work.rglob("*")):
        # target/release/build/ holds the build scripts' own programs (build_script_build.exe), which run once on the
        # builder's PC and ship nowhere; libsqlite3-sys's carries its CARGO_MANIFEST_DIR, which --remap-path-prefix does
        # not reach. Every binary that can ship - target/release/*.exe|*.dll and their copies in deps/ - is still scanned.
        parts = [part.lower() for part in path.parts]
        if "release" in parts and parts[parts.index("release") + 1:parts.index("release") + 2] == ["build"]:
            continue
        if path.suffix.lower() in (".exe", ".dll", ".pdb") and "target" in path.parts and "release" in path.parts:
            data = path.read_bytes()
            for needle in sorted(needles):
                for form in sorted({form for form, _ in hits(data, needle)}):
                    print("PROFILE PATH %r (%s) in %s" % (needle, form, path.relative_to(work)))
                    bad = 1
    print("profile-path scan: %s" % ("FOUND" if bad else "none in any .exe, .dll or .pdb"))
    return bad


# (what is planted, the user name scanned for, whether it must be found). The user is a fixture that, like the real
# one, sits inside the handle (here its last part, so no part of a real user name is written here).
PLANTED = (
    (b"publisher songyb111-gachon\x00", "gachon", False),
    ("publisher songyb111-gachon".encode("utf-16-le"), "gachon", False),
    (b"SongYB111-Gachon", "gachon", False),
    (b"C:\\Users\\gachon\\.cargo\\registry", "gachon", True),
    ("C:\\Users\\gachon\\AppData".encode("utf-16-le"), "gachon", True),
    (b"songyb111-gachon then C:\\Users\\gachon\\x", "gachon", True),
    (b"gachon alone", "gachon", True),
    (b"songyb111_gachon, a near handle", "gachon", True),
    (b"gachon-songyb111, the parts swapped", "gachon", True),
    (b"C:\\Users\\ExampleUser\\x", "ExampleUser", True),
)


def self_test() -> int:
    wrong = 0
    for data, user, expected in PLANTED:
        found = bool(hits(data, user))
        if found != expected:
            print("profile-path self-test: %r scanned for %r was %s" % (data, user, "found" if found else "passed"))
            wrong = 1
    print("profile-path self-test: %s" % ("WRONG" if wrong else "%d planted cases judged as they must be" % len(PLANTED)))
    return wrong


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    if len(sys.argv) != 3:
        sys.exit("usage: profile_scan.py WORK USER | --self-test")
    sys.exit(scan(Path(sys.argv[1]), sys.argv[2]))

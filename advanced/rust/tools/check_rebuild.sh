#!/usr/bin/env bash
# The standard binaries must not depend on whether the advanced folder exists (PLAN.md 1.1, the edition audit's check (e)).
#
#     bash advanced/rust/tools/check_rebuild.sh [REF]      # from inside the repository; REF defaults to HEAD
#
# Builds the standard workspace's release binaries twice from REF, in two different folders of a scratch directory:
# once from an archive that holds both workspaces (the advanced one is built there too), once from an archive that
# holds only rust/. Then compares every .exe and .dll byte for byte, and counts the profile path in each (the Windows
# user name, the scratch folders, the cargo and rustup homes). Exit 0 only if they are identical and clean.
# CAR_REBUILD_DIR names the scratch directory (default: a new temporary one); it is left in place for a scan.
set -euo pipefail
ref="${1:-HEAD}"
repo="$(git rev-parse --show-toplevel)"
work="${CAR_REBUILD_DIR:-$(mktemp -d)}"
rm -rf "$work/with" "$work/without"
mkdir -p "$work/with" "$work/without"
git -C "$repo" archive "$ref" rust advanced | tar -x -C "$work/with"
git -C "$repo" archive "$ref" rust | tar -x -C "$work/without"
test -d "$work/with/advanced/rust" && ! test -e "$work/without/advanced"

build() {
    (cd "$1" && . tools/rustflags.sh release && cargo build --release --locked --jobs "${CARGO_BUILD_JOBS:-4}")
}
build "$work/with/rust"
build "$work/with/advanced/rust"
build "$work/without/rust"

status=0
names="$(cd "$work/with/rust/target/release" && ls *.exe *.dll)"
for name in $names; do
    a="$(sha256sum "$work/with/rust/target/release/$name" | cut -d' ' -f1)"
    b="$(sha256sum "$work/without/rust/target/release/$name" | cut -d' ' -f1)"
    if [ "$a" = "$b" ]; then echo "same      $a  $name"; else echo "DIFFERENT $name: $a vs $b"; status=1; fi
done
python - "$work" "$(basename "${USERPROFILE:-$HOME}")" <<'PY' || status=1
import sys
from pathlib import Path
work, user = Path(sys.argv[1]), sys.argv[2]
needles = {user, str(work), work.as_posix(), work.as_posix().replace("/", "\\"), "scratchpad"}
needles |= {part for part in work.parts if len(part) > 8 and part != "/"}
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
            for form, blob in (("utf-8", needle.encode()), ("utf-16", needle.encode("utf-16-le"))):
                if blob.lower() in data.lower():
                    print("PROFILE PATH %r (%s) in %s" % (needle, form, path.relative_to(work)))
                    bad = 1
print("profile-path scan: %s" % ("FOUND" if bad else "none in any .exe, .dll or .pdb"))
sys.exit(bad)
PY
echo "scratch: $work"
exit $status

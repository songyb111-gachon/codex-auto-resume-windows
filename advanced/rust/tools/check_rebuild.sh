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
    (cd "$1" && . tools/rustflags.sh && cargo build --release --locked --jobs "${CARGO_BUILD_JOBS:-4}")
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
user="$(basename "${USERPROFILE:-$HOME}")"
for file in $(find "$work/with" "$work/without" -path '*/target/release/*' -type f \( -name '*.exe' -o -name '*.dll' -o -name '*.pdb' \)); do
    hits=$(LC_ALL=C grep -c -a -i -e "$user" -e 'scratchpad' "$file" || true)
    wide=$(LC_ALL=C grep -c -a -i -P "$(printf '%s' "$user" | sed 's/./&\x00/g')" "$file" || true)
    if [ "$hits" != "0" ] || [ "$wide" != "0" ]; then echo "PROFILE PATH in $file ($hits narrow, $wide wide lines)"; status=1; fi
done
echo "scratch: $work"
exit $status

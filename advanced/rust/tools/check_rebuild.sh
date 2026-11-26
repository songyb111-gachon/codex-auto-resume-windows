#!/usr/bin/env bash
# The standard binaries must not depend on whether the advanced folder exists (PLAN.md 1.1, the edition audit's check (e)).
#
#     bash advanced/rust/tools/check_rebuild.sh [--keep] [REF]      # from inside the repository; REF defaults to HEAD
#
# Builds the standard workspace's release binaries twice from REF, in two different folders of a scratch directory:
# once from an archive that holds both workspaces (the advanced one is built there too), once from an archive that
# holds only rust/. Then compares every .exe and .dll byte for byte, and counts the profile path in each (the Windows
# user name, the scratch folders, the cargo and rustup homes; tools/profile_scan.py, whose one allowance is the publisher
# handle `songyb111-gachon` and which proves its own rules on planted cases first). Exit 0 only if they are identical and
# clean.
# CAR_REBUILD_DIR names the scratch directory (default: a new temporary one). What this script made goes when it exits,
# passed, failed or stopped: the temporary folder it made, or under CAR_REBUILD_DIR only the with/ and without/ it made
# (the named folder itself and anything else in it stay). --keep leaves them for a scan. Nothing else is ever removed.
set -euo pipefail
keep=0
ref=HEAD
for argument in "$@"; do
    case $argument in
        --keep) keep=1 ;;
        -*) echo "check_rebuild.sh: unknown option $argument" >&2; exit 2 ;;
        *) ref=$argument ;;
    esac
done
repo="$(git rev-parse --show-toplevel)"
python "$repo/advanced/rust/tools/profile_scan.py" --self-test
made=""
if [ -n "${CAR_REBUILD_DIR:-}" ]; then
    work=$CAR_REBUILD_DIR
else
    work="$(mktemp -d)"
    made=$work
fi
cleanup() {
    if [ "$keep" = 1 ]; then
        echo "scratch kept (--keep): $work"
    elif [ -n "$made" ]; then
        rm -rf -- "$made"
    else
        rm -rf -- "$work/with" "$work/without"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
echo "scratch: $work ($([ "$keep" = 1 ] && echo "kept: --keep" || echo "removed when this script exits"))"
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
python "$repo/advanced/rust/tools/profile_scan.py" "$work" "$(basename "${USERPROFILE:-$HOME}")" || status=1
exit $status

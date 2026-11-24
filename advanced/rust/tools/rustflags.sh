# Source this before a build that is checked for its bytes or its paths (PLAN.md 2, toolchain-check.md section 4):
#
#     . tools/rustflags.sh             # from the workspace folder; sets RUSTFLAGS
#     . tools/rustflags.sh release     # the same, and no PDB at all (see below)
#
# .cargo/config.toml holds the flags that need no path (/Brepro, /PDBALTPATH). The `--remap-path-prefix` flags need the
# absolute path of this checkout, of CARGO_HOME (where a dependency's source is read from, and so what its panic
# locations record) and of RUSTUP_HOME, and a config file cannot name those. RUSTFLAGS replaces the config's rustflags
# whole, so this script repeats them; tests/ on the Rust branch holds the two lists to each other.
#
# `release`: a PDB records the linker's command line, the object files' folders and the toolchain's natvis paths - the
# builder's profile path, whatever is remapped - and PLAN.md 6.6 ships none. A build whose binaries are shipped or
# compared (the edition rebuild check, the release build) links with /DEBUG:NONE, so there is no PDB to leak or to ship.
# Ordinary builds keep their PDB for the debugger.
#
# The workspace is the folder that holds this tools/ folder; it is remapped to /build, so two checkouts in different
# folders build the same bytes (a path under the checkout is recorded relative to it by cargo already, a dependency's is not).
_car_win() { local p bs; bs='\'; p="$(cd "$1" 2>/dev/null && pwd -W)"; printf '%s' "${p//\//$bs}"; }
_car_ws="$(_car_win "$(dirname "${BASH_SOURCE[0]}")/..")"
_car_cargo="$(_car_win "${CARGO_HOME:-$HOME/.cargo}")"
_car_rustup="$(_car_win "${RUSTUP_HOME:-$HOME/.rustup}")"
export RUSTFLAGS="--remap-path-prefix=${_car_ws}=/build --remap-path-prefix=${_car_cargo}=/cargo --remap-path-prefix=${_car_rustup}=/rustup -C link-arg=/Brepro -C link-arg=/PDBALTPATH:%_PDB%"
if [ "${1:-}" = "release" ]; then export RUSTFLAGS="$RUSTFLAGS -C link-arg=/DEBUG:NONE"; fi
unset _car_ws _car_cargo _car_rustup

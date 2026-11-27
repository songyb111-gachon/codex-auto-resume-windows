# Groundwork (seat S0.1): what is here, and the proof

Branch `car-v0627-ws`, cut from dev `e17cccf2f`. Nothing in this step ports behaviour: every crate is an empty
`lib.rs` or `main.rs`. It exists so that the seats after it build on a graph cargo already enforces. Written
2026-11-24/25; commands were run in this worktree on this PC (Windows 11, rustc 1.100.0, cargo 1.100.0, MSVC 14.44
`link.exe`), builds with `CARGO_BUILD_JOBS=4`.

## What is here

| Path | What |
|---|---|
| `rust/Cargo.toml`, `rust/Cargo.lock` | the standard workspace: `members = ["crates/*"]`, resolver 3, edition 2024, profiles |
| `rust/crates/*` | the 17 crates of PLAN 1.2 |
| `advanced/rust/Cargo.toml`, `Cargo.lock` | the advanced workspace; its 3 crates are members, the standard crates it reaches come in by `path = "../../../../rust/crates/<crate>"` and are not members |
| `advanced/rust/crates/{car-adv,car-adv-bin,car-adv-host}` | the advanced crates (D19: one library crate in the alpha) |
| `{rust,advanced/rust}/rust-toolchain.toml` | channel 1.100.0, rustfmt + clippy, target `x86_64-pc-windows-msvc`, profile minimal |
| `{rust,advanced/rust}/.cargo/config.toml` | the link flags `/Brepro` and `/PDBALTPATH:%_PDB%` |
| `{rust,advanced/rust}/tools/rustflags.sh` | the whole `RUSTFLAGS`: the config's flags plus the `--remap-path-prefix` flags; `release` adds `/DEBUG:NONE` |
| `{rust,advanced/rust}/deny.toml` | cargo-deny: licences, bans, sources, advisories (D7, blocking) |
| `rust/tools/check_groundwork.py` | holds the two workspaces' shared files, the flags, the crate graph and the locks to what PLAN 1.1-1.3 say |
| `advanced/rust/tools/check_rebuild.sh` | the edition-rebuild check below |
| `.github/workflows/rust.yml` | the Rust CI job (see below) |
| `.gitignore`, `.gitattributes` | `rust/target/`, `advanced/rust/target/` ignored; `rust/**` and `advanced/rust/**` checked out with LF |

The standard workspace never names the other one (`check_groundwork.py` greps every `.toml`, `.rs`, `.sh` and `.lock` under
`rust/`). `advanced/rust/` depends on `rust/` by path only.

## The crate graph

`tests/test_stack.py` `EDGES` read as crates, minus the cuts C1-C6 of PLAN 1.3. `EXPECTED` in `check_groundwork.py` holds the
same table and is compared with `cargo metadata` both ways. Cargo itself refuses a cycle (proved: adding
`car-watcher` to `car-machine`'s dependencies gives `error: cyclic package dependency`).

```
car-machine    -                         car-words      machine
car-brand      -                         car-config     machine
car-platform   machine                   car-policy     machine words
car-store      machine policy            car-scheduler  machine policy
car-codex      config machine platform policy
car-engine     codex machine policy scheduler words
car-surface    brand machine platform policy words
car-control    brand codex config machine platform policy store surface words
car-watcher    codex config control engine machine platform policy store surface words
car-bin        control watcher           car-host       control watcher
car-legacy     platform                  car-harness    -
car-adv        every standard library crate (the superset the plug may reach; S7 seats trim it)
car-adv-bin    car-adv car-bin           car-adv-host   car-adv car-host
```

`[workspace.lints.cargo] unused_dependencies = "allow"`: the edges are declared ahead of the code, and cargo 1.100 would
warn on every one of them until a seat fills the crate.

Binaries: `car-bin` builds `codex-auto-resume.exe` (console), `car-legacy` builds `python.exe` (console) and
`pythonw.exe` (`#![windows_subsystem = "windows"]`, PLAN 1.7), `car-harness` builds `car-harness.exe`, `car-host` builds
`car_core.dll` (cdylib; a DLL has no subsystem), `car-adv-bin` builds `codex-auto-resume.exe` and `car-adv-host` builds
`car_core.dll` of the advanced edition. Profiles (both roots, equal): `panic = "unwind"` (D15); release `opt-level = 3`,
`lto = "fat"`, `codegen-units = 1`, `strip = "symbols"` (PLAN 6.6).

## Done-checks (PLAN 5.3, row S0.1)

### 1. fmt, clippy `-D warnings`, test green in both workspaces

`. tools/rustflags.sh` first, in each workspace folder:

```
## rust
$ cargo fmt --check                                         rc=0
$ cargo clippy --locked --all-targets -- -D warnings        Finished `dev` profile ... rc=0
$ cargo test --locked                                       34 x "test result: ok. 0 passed; 0 failed", rc=0
$ cargo deny --locked check                                 advisories ok, bans ok, licenses ok, sources ok
## advanced/rust
$ cargo fmt --check                                         rc=0
$ cargo clippy --locked --all-targets -- -D warnings        Finished `dev` profile ... rc=0
$ cargo test --locked                                       4 x "test result: ok. 0 passed", rc=0
$ cargo deny --locked check                                 advisories ok, bans ok, licenses ok, sources ok
```

There are no tests yet: "green" is a build and an empty run. cargo-deny prints `license-not-encountered` warnings for the
allow-list entries nothing uses yet; it is warn, not fail. A banned crate fails: `tokio = "=1.40.0"` added to a crate gave
`error[banned]: crate 'tokio = 1.40.0' is explicitly banned`. cargo-deny 0.22.0 (installed by
`cargo install --locked cargo-deny`). cargo-vet is not installed and not run: D7 makes it advisory until v0.6.28, so
there is no `supply-chain/` folder yet; the first seat to add a third-party crate runs `cargo vet init` and puts the
check in CI as `continue-on-error`.

### 2. The standard binaries rebuilt with `advanced/` deleted are byte-identical

`bash advanced/rust/tools/check_rebuild.sh HEAD` (committed HEAD `dfd87a057`): `git archive` of `rust advanced` into
`<scratch>/with`, of `rust` alone into `<scratch>/without` (so `without/advanced` does not exist); `. tools/rustflags.sh
release; cargo build --release --locked` in `with/rust`, `with/advanced/rust` (the dummy advanced crates in place) and
`without/rust`. Two different folders, none of them this worktree. Output:

```
same      3cc68fcd5ce8801de1fb3678c55248847dd0558e8d47487ef11840a7028b3f10  car-harness.exe
same      e2d58f23c7000d7aede52c674463484a53780a8ee9aaf66bc3abbbe0ab3abc12  car_core.dll
same      3cc68fcd5ce8801de1fb3678c55248847dd0558e8d47487ef11840a7028b3f10  codex-auto-resume.exe
same      3cc68fcd5ce8801de1fb3678c55248847dd0558e8d47487ef11840a7028b3f10  python.exe
same      d0104e1b1b0c951641ce5a5713433c9bd23a12c3078238091eb6dab1e85d41bb  pythonw.exe
profile-path scan: none in any .exe, .dll or .pdb
rc=0
```

The empty `main` programs hash alike by construction; the check's value is that the workflow, the flags and the
two-folder rebuild are in place for the crates that follow. A weaker run, a registry dependency (serde_json) built in two folders with
only `tools/rustflags.sh`, also gave one hash and no user name; without the remaps a dependency's panic location carried
the builder's `.cargo
egistry` path (measured in a scratch copy, deleted).

### 3. No profile path and no Windows user name in a built binary

The same run, scanned two ways:

* the release skill's `privacy_scan.py` on every `.exe` and `.dll` of `with/rust`,
  `with/advanced/rust` and `without/rust` (the cargo `build/*/out/*` copies as well): each line `clean ... (looked for 3
  names; no profile paths written: none)`.
* the check script's own scan, and a second one by hand, over the bytes in UTF-8 and UTF-16LE for the Windows user name, the scratch
  folder's path and each of its parts, and the owner's real name: none.

What made it clean, and what did not:

* `/Brepro` and `/PDBALTPATH:%_PDB%` keep the link timestamp and the PDB path out of the PE (toolchain-check.md section 4).
* `--remap-path-prefix` for the checkout, `CARGO_HOME` and `RUSTUP_HOME` is needed as soon as a dependency has a panic
  location; a config file cannot name absolute paths and `profile.trim-paths` is nightly-only in cargo 1.100
  (`feature trim-paths is required ... not stabilized`), so `tools/rustflags.sh` builds the flags.
* A PDB cannot be made clean. The first run failed here: every `.pdb` held the linker command line (`/OUT:` and a path in the builder's profile), the
  object files' folders and the toolchain's natvis paths. The release build therefore links with `/DEBUG:NONE` (`tools/rustflags.sh release`):
  no PDB exists, and PLAN 6.6 ships none. Ordinary (dev) builds keep their PDB for the debugger and carry the builder's paths in it.

### 4. Nothing the Python product ships changes

No file under `src/`, `advanced/src/`, `gui/`, `build/`, `scripts/` or `docs/` is touched; the diff against dev is
`rust/`, `advanced/rust/`, `.github/workflows/rust.yml`, `.gitignore` and `.gitattributes`. The tests that read the tracked tree or the
workflows (listed below) were run in the standard lane through `wait_quiet.sh`:

Standard lane (`CODEX_AR_EDITION` unset, `PYTHONPATH="src;tests"`), each run detached through `wait_quiet.sh`, logs outside
the worktree:

* Run 1, 24 modules, 602 tests, 2003 s: `test_srcscan test_repo_hygiene test_privacy_claims test_privacy_bare_hosts
  test_edition test_edition_audit test_edition_build test_workflow_pins test_workflow_privilege test_build_tooling_audit
  test_brand test_feature_matrix test_listing_scan test_korean test_split_runs test_structural_invariants
  test_durations_refresh test_stack test_layers test_sizes test_no_console_windows test_surface_properties
  test_release_size test_reproducible`. Two failures, both a test that names every workflow or every document:
  `test_workflow_privilege.test_every_workflow_is_known` (its `KNOWN` list lacked `rust.yml`) and
  `test_korean.MappingTests.test_every_human_facing_document_is_classified` (`rust/GROUNDWORK.md` was in neither list).
* Fixed at the tests' view only: `tests/test_workflow_privilege.py` `KNOWN` gains `"rust.yml"` (the new workflow passed every
  other privilege test unchanged: no top-level grant, `persist-credentials: false`, no `pull_request_target`);
  `advanced/ko_branch.json` `intentionally_english` gains `rust/GROUNDWORK.md` with its reason. It is that file and not
  `scripts/ko_branch.json` because `scripts/` ships in the standard archive and nothing the product ships may change;
  any Markdown a Rust seat adds under `rust/` needs an entry beside it.
* Run 2, 9 modules, 175 tests, 734 s: `test_workflow_privilege test_korean test_repo_hygiene test_privacy_claims
  test_privacy_bare_hosts test_workflow_pins test_listing_scan test_edition_audit test_srcscan`. One failure,
  `test_repo_hygiene.test_no_real_windows_home_directory`, which read this very file (a prose example that looked like
  a profile path); the example was reworded.
* Run 3, 7 modules, 128 tests, 91 s: `test_repo_hygiene test_privacy_claims test_privacy_bare_hosts test_listing_scan
  test_korean test_workflow_privilege test_workflow_pins`: OK, 2 skipped.
* Run 4, 17 modules, 441 tests, 806 s: `test_reproducible test_release_size test_edition test_edition_build
  test_build_tooling_audit test_brand test_feature_matrix test_stack test_layers test_sizes test_no_console_windows
  test_surface_properties test_structural_invariants test_durations_refresh test_split_runs test_srcscan
  test_privacy_bare_hosts`: OK, 1 skipped.
* Skips, all unrelated to this change: `test_workflow_privilege.YamlShapeTests.test_every_workflow_parses` (PyYAML is not
  installed here; GitHub validates `rust.yml` on push, which this step may not do), `test_korean.BranchTests.test_the_branch_holds_the_languages_it_should`
  (CI names no branch), `test_release_size.TrimmedRuntimeTests...` (the pinned runtime is not in `build/cache`).
* Tree scanners that now see `rust/` (every one reads `git ls-files`, so none needed a change): `test_repo_hygiene`,
  `test_privacy_claims`, `test_privacy_bare_hosts`, `test_listing_scan`, `test_brand`, `test_feature_matrix`,
  `test_srcscan` (it lists `src` only), `test_edition` and `test_edition_audit` (they list `advanced/src` and `src`).
  `test_korean` is the one that did need the entry above.

## CI (`.github/workflows/rust.yml`)

Runs on push to `car-v0627-*` and `wip/rust*` only (never dev, main or a pull request). Job `rust`, a matrix over `rust` and
`advanced/rust` on `windows-latest`: `rustup toolchain install` (reads the pin), cache, `cargo install --locked cargo-deny
--version 0.22.0` when missing, `. tools/rustflags.sh` into `$GITHUB_ENV`, `cargo fmt --check`, `cargo clippy --locked
--all-targets -- -D warnings`, `cargo test --locked`, `cargo deny --locked check`, and (rust only) `python rust/tools/check_groundwork.py`.
Job `rebuild`: `advanced/rust/tools/check_rebuild.sh HEAD`. The new workflow was not run on GitHub (no push, brief rule 2);
its steps were run here one by one and `tests/test_workflow_pins.py` accepts its action pins (`actions/checkout` v7.0.1,
`actions/cache` v6.1.0, the commits the other workflows and the GitHub API give).

## What the plan did not say

* **`car-bin` and `car-host` need a library half.** PLAN 1.2 lists them as `bin` and `cdylib`, but `car-adv-bin` and
  `car-adv-host` must reuse their code, and a binary crate cannot be a dependency. `car-bin` is a `lib` (`car_bin`) plus the
  `codex-auto-resume` bin; `car-host` is a `cdylib` named `car_core` (so `car_core.dll`). The advanced host's library is
  also `car_core`, so it names its dependency `car_host_lib = { package = "car-host", ... }`.
* **`car-legacy` is two binaries**, `python.exe` (console) and `pythonw.exe` (GUI subsystem), because the old Run value
  started `pythonw.exe`.
* **The config cannot hold the path remaps** (above); the script is the flag source for checked builds, and
  `check_groundwork.py` holds the config's list inside the script's.
* **`rust-toolchain.toml` and `deny.toml` are in each workspace folder**, not at the repository root, so that each workspace is
  self-contained and the standard one builds from an archive of `rust/` alone.
* The advanced crate's edges (`car-adv` to all 13 library crates) are a superset: PLAN 1.4 does not list them.

## Integration (branch `car-v0627-rust`, 2026-11-25)

The four P0 seats on one branch, cut from the groundwork (`car-v0627-ws`). The seats were cut from dev before the groundwork, so
each merge met the groundwork's files; commits of the seats are untouched (`git merge --no-ff`, in this order):

1. `car-v0627-json` (S0.2): `rust/crates/car-machine` with `src/json/`, its tests, its own `Cargo.lock`. Conflicts: `car-machine/Cargo.toml`
   and `src/lib.rs` (both sides had made the crate). Resolved to the workspace's inheritance (`version/edition/license.workspace`,
   `[lints] workspace`) plus S0.2's dependencies exactly; `pub mod json;` replaces the placeholder line; the crate-local lock and
   `.gitignore` are gone.
2. `car-v0627-harness` (S0.4): `rust/crates/car-harness`, `tests/rustdiff/`, the shim in `tests/sitecustomize.py` and
   `scripts/test_parts.py`. Conflicts: `car-harness/Cargo.toml` and `src/main.rs`, resolved the same way (the seat's code, the
   workspace's inheritance); the crate-local lock and `.gitignore` are gone.
3. `car-v0627-vocab` (S0.3): `build/vocab_export.py`, `advanced/tests/test_advanced_stack.py`, `test_advanced_vocab_export.py`,
   `tests/test_vocab_export.py`. No conflict.

After the merges (own commits): one workspace and one lock; `car-harness` writes through `car-machine::json` and `src/pyjson.rs`
is deleted; `check_groundwork.py` EXPECTED gains `car-harness -> car-machine`; `tests/rustdiff` builds into `rust/target`.

### One lock

`rust/Cargo.lock` is regenerated by cargo from the two members (48 packages: 17 workspace crates, 31 from crates.io); `cargo ... --locked` is valid in both workspaces.
`advanced/rust/Cargo.lock` gained the same `serde_json`, `serde`, `serde_core`, `serde_derive`, `indexmap`, `itoa`, `memchr`, `zmij`,
`hashbrown`, `foldhash`, `equivalent`, `proc-macro2`, `quote`, `syn`, `unicode-ident` at the same versions (car-adv reaches car-machine),
and none of the SQLite packages (car-harness is not in it); `check_groundwork.py` compares the two locks and passes.

| crate | version | from |
|---|---|---|
| serde_json | 1.0.154, features `std`, `preserve_order`, `arbitrary_precision` (car-machine); the harness asks for `1` with default features, so the one build has all of them | both seats resolved 1.0.154: nothing to choose |
| indexmap | 2.14.2 | car-machine |
| rusqlite | 0.43.0, `bundled` (libsqlite3-sys 0.40.0, SQLite 3.54.1) | car-harness |

No version conflict arose. `deny.toml` is unchanged: `cargo deny check` accepts every crate in both locks under the licences the list already
allows, and every source is crates.io (D7's policy needed no addition).

### Checks (commands run from `rust/` after `. tools/rustflags.sh`, `CARGO_BUILD_JOBS=4`)

```
## rust
cargo fmt --check                                   rc=0
cargo clippy --locked --all-targets -- -D warnings  rc=0
cargo test --locked                                 car-machine: 3 unit, json_edges 12, json_goldens 1, json_reference 1 (20,000 values x 15 option sets = 300,000 writes, all equal); the rest 0 tests; rc=0
CAR_JSON_COUNT=200000 cargo test --locked -p car-machine --test json_reference
                                                    200,000 values x 15 = 3,000,000 writes, 3,000,000 equal, 0 differ; 59 s
cargo deny --locked check                           advisories ok, bans ok, licenses ok, sources ok
python -X utf8 tools/check_groundwork.py            rust groundwork: OK (17 standard crates, 3 advanced crates)
## advanced/rust
cargo fmt --check / clippy -D warnings / test --locked / deny --locked check: rc=0, 4 x "0 passed", all four ok
## the differential harness (repository root)
python -X utf8 tests/rustdiff/run.py --build -v     4 tests OK; defaults 2098-byte reply and 2244-byte settings.json identical to
                                                    v0.6.26-beta.2 and to the golden; the state fixture's 27 records, 29 values equal
```

The rebuild identity check `bash advanced/rust/tools/check_rebuild.sh HEAD`: all six binaries `same` between the with-advanced and the
without-advanced tree (`car-core-stub.exe`, `car-harness.exe`, `car_core.dll`, `codex-auto-resume.exe`, `python.exe`, `pythonw.exe`).
The release skill's `privacy_scan.py` on every `.exe` and `.dll` of `with/rust`, `with/advanced/rust` and `without/rust`: `clean`.
**One finding is open and is not papered over:** the script's own profile-path scan reports `PROFILE PATH` (the Windows user name,
utf-8) in `target/release/build/libsqlite3-sys-<hash>/.../build_script_build.exe` in both trees, so the script exits 1. It is a
build-time tool that runs on the builder's PC and ships nowhere; it carries `<CARGO_HOME>\registry\src\...\libsqlite3-sys-0.40.0/`,
the value of `env!("CARGO_MANIFEST_DIR")` in that crate's `build.rs`, which `--remap-path-prefix` does not touch. No shipped file or PDB
has a path. Whether the scan should name build scripts as exempt (only the files `build_script_*.exe` below `build/`) or the build should
avoid the string is the caller's call, and CI's `rebuild` job fails until then.

Python, standard lane through `wait_quiet.sh` (`PYTHONPATH="src;tests"`, 2026-11-25, 864 s): `test_korean test_workflow_privilege
test_repo_hygiene test_srcscan test_structural_invariants test_stack test_layers test_edition_audit test_vocab_export test_split_runs
test_privacy_claims test_privacy_bare_hosts`: Ran 273, OK (skipped=2).
Advanced lane (`CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;advanced/tests;tests"`, 66 s): `test_advanced_stack
test_advanced_vocab_export`: Ran 18, OK.

### What the merge itself needed

* `car-machine`'s reference test started `python` with `Command::new`, which on this PC finds the Microsoft Store stub (it prints
  nothing and exits), so the writer's one test failed with "failed to fill whole buffer". It now tries `python`, `python3`, `py` and
  uses the first that writes `1` through `json.dumps`; `CAR_JSON_PYTHON` still wins.
* `tests/rustdiff` looked for the build in the harness crate's own `target/`; with one workspace it is `rust/target`.
* `advanced/rust/Cargo.lock` had to learn `car-machine`'s dependencies.

### For the next seats

* P1 (car-machine, car-config, car-words, car-brand, car-store): `car-machine::json` has no `Value` conversions for the domain yet;
  the harness's `defaults.rs` and `state.rs` are marked TO BE REPLACED by car-policy (S2.2) and car-store (S1.2). A seat that adds a
  dependency touches both locks (`advanced/rust/Cargo.lock` too: `cargo check --workspace` there, without `--locked`) and
  `check_groundwork.py` EXPECTED.
* S3.1 car-platform: nothing from this integration; it still reaches only car-machine.
* `tests/rustdiff/README.md` is classified English-only in `scripts/ko_branch.json` (the harness seat's entry); `rust/GROUNDWORK.md`
  keeps its entry in `advanced/ko_branch.json`.

- **2026-11-25, main session:** check_rebuild.sh no longer scans `target/release/build/`. That folder holds the build scripts' own programs, which run once on the builder's PC and ship nowhere. libsqlite3-sys's `build_script_build.exe` carries its `CARGO_MANIFEST_DIR`, which `--remap-path-prefix` does not reach. Every binary that can ship is still scanned: `target/release/*.exe|*.dll` and their copies in `deps/`. After this change: rc=0, all 6 binaries the same with and without advanced/, and "profile-path scan: none in any .exe, .dll or .pdb".

## Integration 2 (branch `car-v0627-rust`, 2026-11-25)

The three P1/P3 seats on the branch, merged with `git merge --no-ff` in this order, then four commits of their own.

| Merge | Seat | What came in |
|---|---|---|
| `Merge car-v0627-leaves` | S1.1 | car-machine's domain and vocabularies, car-words, car-config, car-brand, `tests/rustdiff/leaves.py` and `diffs_leaves_*.py` |
| `Merge car-v0627-store` (`4679ac1c5`) | S1.2 | car-store, car-harness's `store.rs` (its `state.rs` stand-in is gone), `diffs_store.py` |
| `Merge car-v0627-platform` (`a7796596d`) | S3.1 | car-platform, `platform_*diffs.py`, the `windows` 0.62 crates in both locks |

Conflicts, all in files two seats had edited: `rust/Cargo.lock` and `check_groundwork.py` EXPECTED (car-harness now reaches brand, config, machine,
store and words), `car-harness`'s `lib.rs` and `main.rs` (both `leaves.batch` and the `store.*` calls are served; the match is on `(call, home)` and
`leaves.batch` takes no home), `tests/rustdiff/README.md` (both seats' sections), `tests/rustdiff/run.py` (it loads `diffs.py`, then every
`diffs_*.py` of S1.1 and S1.2, then every `*_diffs.py` of S3.1, and prints each `RECORD` line once) and `advanced/rust/Cargo.lock`, which cargo
regenerated (`cargo check --workspace --offline` in `advanced/rust`) from the standard side.

### The seams, replaced

| Seam | Now |
|---|---|
| car-store `seam/vocab.rs` (states, public words, usage keys, engine states, `PLAIN_MOVES`) | car-machine's generated lists, read through `car-store/src/machine.rs`; 23 of the 34 lists are gone from the seam |
| car-store `seam/ids.rs`, `seam/usage.rs` | deleted: `car_machine::domain::{ids, usage}`; the store's `machine::ids` only maps `uuid_problem`'s word to its own enum |
| car-store `seam/mod.rs`: `epoch_store`, `may_be_queued`, `plain_move_allowed`, `waiting_state`, `event_code`, `reason_code`, `actor_code`, `turn_status`, `hold_for_tier`, `own_postponement` | `car_machine::domain::{states, public}`; the adapters in `machine.rs` build the dict and the `Value`s and turn the Python exception class a car-machine function names into `Error::Python` (`raised`) |
| car-platform `seams.rs` (`AdapterError`, `StateAccess`) | `car_machine::domain::errors::AdapterError`, `car_machine::vocab_gen::domain_vocabulary::StateAccess`; the file is deleted |
| car-store `seam/gates.rs`, the policy's lists (`CATEGORIES`, `NOTICE_KINDS`, the gates' words, `WATCHER_ENDS`, `EARLY_STATES`), `is_recoverable`, `reset_verified`, `postponement_problem`, `KEEP_SECONDS`, `CAPACITY_MAX_SECONDS`, `USAGE_LIMIT` | **kept**: they wait for car-policy (S2.1). `seam/python.rs` (CPython's own text readings) is the store's and stays |

`SeamVocabularyDiff` now holds the 11 lists left in the seam to the tag's, and fails if any of the 23 car-machine lists is copied back.

### The junction rule: one probe, in car-platform

The reference asks two questions about a link. `Path.is_symlink()` is true for a real symbolic link and false for a junction; `config.is_link` is true for any
reparse point. It uses the first for car-store's "State paths must not be symbolic links" and, in `config.py`, for `Paths.ensure()`, `claim_home()`,
`owns_home()` (the home and `runtime.json`) and `candidate_codex_exes()`; the second for `owns()`, the owned file lists and the walks.

* `car-platform/src/links.rs` (`links::is_symlink`, `reparse_tag`): the tag as CPython's `os.lstat` reads it (`CreateFileW` with `FILE_FLAG_OPEN_REPARSE_POINT`,
  `GetFileInformationByHandleEx(FileAttributeTagInfo)`, `FindFirstFileW` where the file cannot be opened), through the `windows` crate. Only `IO_REPARSE_TAG_SYMLINK` is a link.
  `car-platform/tests/links.rs` proves a junction, a folder, a file, a missing path and, where the account may make one, a symbolic link.
* car-store defines `session::Links` and takes it (`Options.links`, `Store::open(dir, links)`, `LegacyStore::open(dir, &links)`, `downgrade_state*(.., &links)`, and `open::Windows::links()`
  for `open_state`); car-config defines `Links` and holds it in `Os` (`Os::here(long_paths, links)`). Neither depends on car-platform; the harness's `links.rs` implements both
  traits over `car_platform::links::is_symlink`, and the entry points will. car-harness gains the edge to car-platform (EXPECTED).
* car-store's `seam/links.rs`, with its three hand-declared kernel32 functions, is deleted: no Windows call is left in car-store.
* car-config: `Paths.ensure()`, `claim_home()`, `owns_home()` and `candidate_codex_exes()` ask `Links::is_symlink`; `is_link` (any reparse point) keeps its own questions. A junction inside the home passes
  `ensure()` as in the reference. The diff is `OwnedDiff` (`diffs_leaves_config.py`): `ensure()` and `claim_home()` on five scratch homes, the two junction homes among them (`junction`: `config/` a
  junction out of the home, refused both ways; `junction in`: `config/` a junction to a folder inside the home, passed both ways), and an assertion that Rust's answer for `junction in` is `None`. The leaves
  seat's "one stricter answer" is gone. Beside it car-store's `JunctionDiff` (a state folder and a usage-checks folder that are junctions) runs over the same probe. With the harness's probe swapped for
  std's `FileType::is_symlink()` (which counts a junction) both fail ("case 21 differs at /ok/ensure: None != {'config_error': ...}", "a junction home: open differs: reference None, rust {'raised':
  'StoreError', ...}"); restored, both pass.
* What the reference does that the audit should judge is in `plans/v0627-rust/AUDIT-v0628.md`.

### `check_standard_never_names_advanced`

Before: it failed on any line of a `.toml`, `.rs`, `.sh` or `.lock` under `rust/` holding the word "advanced" in any case: 25 lines, all legitimate (the tier "advanced" of the compatibility
vocabulary in car-machine and car-config, the logbook's sentences, the comment of `gui/Brand.cs` as car-brand generates it).

After: it reads the names the Python edition audit looks for (`build/edition_audit.py`, `check_names`, `check_executables`, `check_binaries`) from that module - `PACKAGE`, `SKILL` and `SENTINEL`, as substrings -
and adds the two ways Rust names the advanced edition: a crate `car-adv*` (`car_adv*` in code) and the folder `advanced/`. The word alone is not a name. In a scratch copy of `rust/` (a `git archive` in the
scratchpad, never this worktree):

```
untouched copy                                                                       0 findings
`use car_adv::plug::AdvancedPlug;` in car-store's lib.rs                             rust/crates/car-store/src/lib.rs:59 names advanced (car_adv)
car-adv = { path = ".../advanced/rust/crates/car-adv" } in car-store's Cargo.toml    names advanced (car-adv)
codex_auto_resume_advanced = "1" in car-store's Cargo.toml                           names advanced (codex_auto_resume_advanced)
a workspace member "../advanced/rust/crates/car-adv" in rust/Cargo.toml              rust/Cargo.toml:5 names advanced (advanced/)
```

### Checks (`CARGO_BUILD_JOBS=2`, `. tools/rustflags.sh` first; HEAD `74777f7cb`; the Python lanes below ran on the tree with this section)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked rc=0 (every test result ok); cargo deny --locked check: advisories ok, bans ok, licenses ok, sources ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0 (4 x 0 tests); cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates), rc=0
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0: car-core-stub.exe, car-harness.exe, car_core.dll, codex-auto-resume.exe, python.exe, pythonw.exe the same with and without advanced/;
                                                     "profile-path scan: none in any .exe, .dll or .pdb"
privacy_scan.py on every .exe and .dll under target/release of with/rust, with/advanced/rust and without/rust (14 files; the build scripts' own programs left out): all "clean"
python -X utf8 tests/rustdiff/run.py --build -v      Ran 73 tests, OK (a first run of 73 had one failure, the leaves seat's old assertion of the stricter ensure(), which I had edited under the running process)
```

The 73 diffs, by seat: harness (S0.4) 4; S1.1 27 (brand 8, codex 1, config 2, domain 4, log 2, machine 5, words 5); S1.2 15; S3.1 27 (names 6, live 12, registry 9).

Python, standard lane through `wait_quiet.sh` (`PYTHONPATH="src;tests"`, 486 s): `test_korean test_workflow_privilege test_repo_hygiene test_srcscan test_structural_invariants test_stack
test_layers test_edition_audit test_vocab_export test_split_runs test_privacy_claims test_privacy_bare_hosts`: Ran 273, OK (skipped=2). Advanced lane
(`CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;advanced/tests;tests"`, 33 s): `test_advanced_stack test_advanced_vocab_export`: Ran 18, OK.

### For the next seats

* P2 (car-policy S2.1/S2.2): take what is left in `car-store/src/seam/` (`gates.rs`, `vocab.rs`, `mod.rs`: `is_recoverable`, `reset_verified`, `postponement_problem`, the three constants) and delete the folder
  but `python.rs`, which is the store's own; `CATEGORIES`, `NOTICE_KINDS` and the gates' words come from car-policy's generated vocabulary. car-store already has the edge to car-policy.
* S3.2/S3.3 and the entry points: construct `car_platform::links` behind both `Links` traits (the harness's `links.rs` is the model) and pass it to `Os::here` and `Store::open`/`Options`; `open::Windows::links()` has one more method for car-platform's `Windows` to answer.
* The harness's calls with no Python counterpart yet are unchanged: `store.*`, `leaves.batch`, `sqlite.version`; the platform diffs still use car-platform's own `probe` example, not `car-harness`.

## Integration 3 (branch `car-v0627-rust`, 2026-11-25)

The two P2 seats on the branch, merged with `git merge --no-ff` in this order, then two commits that replace their cross seams.

| Merge | Seat | What came in |
|---|---|---|
| `Merge car-v0627-classify` (`dcbdd01e9`) | S2.1 | `car-policy/src/classify/` (failures, reasons, gates, guards, ladder, quiet, projects, needsyou, power, continuation, permits, selfcheck, the generated vocabulary and text tables), car-store's policy seam moved into car-policy (`seam/vocab.rs` gone), car-harness's `classify.rs`, `pyval::compare`'s fix in car-machine, `diffs_classify_*.py`, `rediff_classify.py` |
| `Merge car-v0627-settings` (`ebd84afc0`) | S2.2 | `car-policy/src/settings/` and `src/plug/`, car-harness's `policy.rs`, car-platform's `widepath.rs` and the REG_QWORD fix, car-machine's loose-reader int fix, check_groundwork's allowance for `plug/edition.rs`, `diffs_settings_*.py`, `settingsdiff.py` |

Conflicts, all in files both seats had edited, each resolved keeping both seats' code: `car-policy/src/lib.rs` (`pub mod classify; pub mod plug; pub mod settings;`),
`tests/rustdiff/README.md` (both sections), and `tests/rustdiff/gen_policy.py`, which both seats had added under the same name for different files: one script now
makes the five generated files (S2.1's `classify/vocab_gen.rs` and `text_tables.rs`; S2.2's `settings/vocab_gen.rs`, `plug/vocab_gen.rs` and `settings/unicode_gen.rs`),
and `--check` says whether any of them differs from the tag. `rust/Cargo.lock`, `advanced/rust/Cargo.lock` and check_groundwork's EXPECTED merged without a conflict;
both seats had added the same `car-policy` dependency to `car-harness/Cargo.toml`, and the merge listed it twice, which cargo refuses: one line is gone.

### The seams, replaced

| Seam | Now |
|---|---|
| S2.1's `classify/seam.rs`: `Own`, `amount`, `canonical`, `coerce`, `spell` (a copy of `ownvalues.py`) | `settings::ownvalues`. A clock is its `Minute` and a set of days its mask (`Measured::days()`); `Measured::number()` answers a clock's minute too. `guards::OWN_CONTEXT` carries the prefix and the label S2.2's published schema needs |
| S2.1's `classify/seam.rs`: `TAKE_UP`, `PACED_AS`, `Alternative`, `FailureForm` | `plug::vocab_gen::domain_plug::TAKE_UP`, `plug::paced_as`, `plug::{Alternative, FailureForm}` (the enums; `failures` compares their `as_str()`) |
| S2.2's `settings/seam.rs`: continuation (styles, modes, placeholders, `validate_custom`, `fold_style`, `coerce_by_thread`), ladder (timings, presets, waits, steps, ceilings, `choices_for`, `previews`), guards, power, needsyou, quiet, projects, `tag_shape`, `blank` | the classify modules by name: `settings` takes `crate::classify::{continuation, guards, ladder, needsyou, power, projects, quiet, failures, text}`; `power` gained `AWAKE_CAPS` and `SLEEP_WAITS` as `power.py` has them (with the vocabulary test the seam held); the ladder's three `Own`s and the quiet clock and days are `pub` |
| `continuation::coerce_by_thread` (S2.1) | keeps a conversation's message as written, a lone surrogate included; it had turned the text into a `String` first, which Python never does. No S2.1 diff held a surrogate there; the settings diff does |

Both `seam.rs` files are deleted; no module of car-policy is named seam. car-store's `seam/` keeps `python.rs`, which is the store's own.

**`homefind.coerce_dismissed`** was in `settings/seam.rs` and in neither seat's list. Ported as the reference has it: `settings/homefind.rs` (`SWITCH`, `DISMISSED`,
`DISMISSED_MAX`, `coerce_dismissed`), with a diff of its own, `diffs_settings_homefind.py` (1,596 cases straight to the function, besides the `DISMISSED` candidates
every settings field already takes through `settings.coerce`). The rest of `homefind.py` (looking for homes in the registry and the Codex app's file, `dismissed_with`) is
the watcher's and stays Python until its seat.

### Checks (`CARGO_BUILD_JOBS=2`, `. tools/rustflags.sh` first; code at `f703f1f8a`; the Python lanes ran on the tree with this section's code)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked rc=0 (car-brand 1, car-config 6, car-machine 19 + json 12/1/1, car-platform 12/1/1/1,
                   car-policy 1, car-store 5 + 4, car-words 8; the rest 0); cargo deny --locked check: advisories ok, bans ok, licenses ok, sources ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0 (4 x 0 tests); cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates), rc=0
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0: car-core-stub.exe, car-harness.exe, car_core.dll, codex-auto-resume.exe, python.exe, pythonw.exe the same with and without advanced/;
                                                     "profile-path scan: none in any .exe, .dll or .pdb"
privacy_scan.py on every .exe and .dll under target/release of with/rust, with/advanced/rust and without/rust (14 files): all "clean"
python -X utf8 tests/rustdiff/run.py --build -v      Ran 97 tests, OK (96 in the full run; the 97th, homefind, failed in it because the new file's first copy had its backslashes halved, and passed alone once they were right: 1,596 cases equal)
python -X utf8 tests/rustdiff/rediff_classify.py --reference v0.6.26-beta.2    "ported files changed from v0.6.26-beta.2 to v0.6.26-beta.2: none"; generated files current, diffs equal (14 tests), rc=0
python -X utf8 tests/rustdiff/gen_policy.py --check --ref v0.6.26-beta.2       car-policy: generated files (classify, settings, plug) match v0.6.26-beta.2, rc=0
```

The 97 diffs, by seat: harness (S0.4) 4; S1.1 27; S1.2 15; S2.1 13 (continuation 3, failures 3, policy 3, vocab 4); S2.2 11 (values 4, files 2, policy 2, plug 2, homefind 1); S3.1 27.
Every count of the earlier runs held: classify 694,880 generated cases, 2,968 corpus cases, 103,503 continuation builds, 59,817 policy (`own.*` among them), 41,367 gates, 24,243 quiet;
settings 48,130 coerce/validate/migrate (26,012 accepted, 22,118 refused alike), 1,186 schema, 4,102 own-value, 923 homes/kinds/memory, 367 file, 8,439 policy-key, 5,457 power-action cases,
and the plug's tables, NULL and 133 consult cases. `SeamParity` and the `own.*` cases now hold `settings::ownvalues` and the plug's words (a copy before); `diffs_classify_*.py` and
`diffs_settings_*.py` are not edited but for the new homefind module and one docstring.

Python, standard lane through `wait_quiet.sh` (`PYTHONPATH="src;tests"`, 597 s): `test_korean test_workflow_privilege test_repo_hygiene test_srcscan test_structural_invariants test_stack test_layers
test_edition_audit test_vocab_export test_split_runs test_privacy_claims test_privacy_bare_hosts`: Ran 273, OK (skipped=2). Advanced lane (`CODEX_AR_EDITION=advanced
PYTHONPATH="src;advanced/src;advanced/tests;tests"`, 49 s): `test_advanced_stack test_advanced_vocab_export`: Ran 18, OK.

### For the next seats

* S3.2/S3.3 (car-codex) and the entry points: nothing from this integration. car-policy holds the classifier (`classify`), the settings (`settings`) and the plug (`plug`); car-store reads its gates,
  categories and constants from it and keeps only `seam/python.rs`. The harness's `policy.batch` and `leaves.batch` (`classify.*`, `own.*`) answer every call of both seats.
* `rediff_classify.py` still lists only S2.1's Python files and diffs; at the v0.6.26 final run it, then `gen_policy.py --check --ref v0.6.26` and the settings re-diff command in
  `tests/rustdiff/README.md` ("S2.1 and S2.2 together").
* The engine (P4): `classify::failures::{admits, takes, readmits}` and `plug::Guarded` are the two halves of what core takes of a plug; the engine calls them and does not copy them.

## The packaging skeleton (seat S8.1, branch `car-v0627-package`, 2026-11-25)

PLAN 5.3 row P8 / S8.1 on the stub core: the shape every Rust release keeps, so that what cannot change later - what an
installed Python version's updater requires of an archive (D9 means 1) and what v0.6.26's setup handover reads (D9 means 2,
`plans/v0627-rust/BRIDGE.md`) - is proved before the core lands. Nothing of the Python release path changes: new files only
(`build/rust_release.py`, `build/rust_legacy_bootstraps.py`, `build/rust_edition_audit.py`, `rust/tools/legacy_lines.py`,
`tests/test_rust_release.py`, `tests/data/rust_release_budget.json`), and car-legacy, car-bin and car-adv-bin filled.

### The archive (both editions; `python build/rust_release.py --edition standard|advanced [--version V] [--build]`)

| Entry | What |
|---|---|
| `payload/CodexAutoResumeSettings.exe`, `payload/codex-auto-resume.ico` | the C# window (`build/make_gui.ps1`, stamp checked), as today; the payload root holds nothing else |
| `payload/app/bin/codex-auto-resume.exe` (console), `codex-auto-resume-setup.exe` (GUI, `asInvoker` manifest), `car_core.dll` | each edition's own build (D2): car-bin / car-adv-bin and car-host / car-adv-host |
| `payload/runtime/python.exe` (console), `payload/runtime/pythonw.exe` (GUI) | car-legacy, from the standard workspace in both editions (byte-identical) |
| `payload/app/src/codex_auto_resume/mcpserver.py`, `payload/app/scripts/plugin_setup.py` | content-free stubs (comment lines only), the same bytes in both editions |
| (advanced) `payload/app/src/codex_auto_resume_advanced/__init__.py` | a stub whose first line is the sentinel, which old Test-Archives, Get-Edition and the window's EditionOfSource look for |
| `payload/app/{.codex-plugin,.agents,skills,assets,docs,README.md,LICENSE,.mcp.json}`, `payload/app/mcp/codex-auto-resume-mcp.exe`, `payload/app/scripts/{bootstrap.ps1,release.json}` | the plugin tree and the updater as make_release ships them (the manifest at the version built, `mcpServers` added, the advanced display name) |
| `payload/app/src/codex_auto_resume/{data,locales,mcp/assets}/*` and (advanced) the package's `locales/*` | the non-Python files of the shipped trees at their paths: the C# window and setup read the catalogs from there (`SettingsRemove.cs`, `SetupWindow.cs`, the strings cache key) |
| `install/install.ps1`, `Install.cmd`, `Uninstall.cmd`, `README.txt` | `install.ps1` is a placeholder until S8.2: it reads no argument, changes nothing, prints `Nothing was installed.` and ends with 1 |
| `setup-handover.json` (archive root) | `{"format": "codex-auto-resume/setup-handover/1", "version": V, "edition": E, "setup": "payload/app/bin/codex-auto-resume-setup.exe"}` |

No Python file but the stubs; the watcher host `CodexAutoResume.exe` (S6.2) and the one-file Setup exe around the archive
(`make_setup.py`) are not built by the skeleton.

### The compatibility entry (car-legacy)

`ACCEPTED` (`rust/crates/car-legacy/src/lib.rs`) is the 26 command lines `rust/tools/legacy_lines.py` collects from every tag
v0.5.2-v0.6.26-beta.2 (and dev's v0.6.26, which adds none): each bootstrap's repair branch and `Invoke-InstalledSetup`
(`plugin_setup.py setup [--no-startup]`, `setup --keep-state [--no-startup] [--watcher-was-stopped]`, `watcher-running`,
`downgrade-state --to 3|4 --stop-watcher`, `remove-entry`, each with and without `-X disable-remote-debug`), `gui/McpLauncher.cs`
(`-I [-X disable-remote-debug] -c <the one code string> <home>\app\src --home <home>`), the Run value (`watcher-launcher.py run`,
`app\src\auto_resume.py --home <home> run`) and the protocol handler (`[-X ...] watcher-launcher.py activate <uri>`,
`[-X ...] app\src\auto_resume.py --home <home> --quiet activate <uri>`). `{home}` is the folder above car-legacy's own `runtime`,
compared as `startup._canonical` compares (car-platform `same_path`); `<uri>` must start `codex-auto-resume:`. The bootstrap's
`-c <code> ... compat-import` is never reached: every tag guards it with `app\src\codex_auto_resume\controlcli.py`, which a Rust
archive never carries (a stub there must never be added). `tests/published.rs` holds the table to `published.txt` both ways and
refuses 35 lines one step away.

An accepted line is handed to the program that replaces its script, with the words after it, the environment plus
`CODEX_AUTO_RESUME_LEGACY_ENTRY=<setup|watcher-running|downgrade-state|remove-entry|mcp|run|activate>`, through car-platform's
starter (`CREATE_NO_WINDOW`): `plugin_setup.py <words>` -> `app\bin\codex-auto-resume.exe <words>`, the MCP line ->
`codex-auto-resume.exe mcp --home <home>` (D18), `activate` -> `codex-auto-resume.exe <same words>` (all waited for, their exit
code returned; streams inherited for python.exe, none for pythonw.exe), `run` -> `app\bin\CodexAutoResume.exe <same words>`
(started, not waited for). Its own codes: 2 refused (argparse's code: an updater reads it as "no such command"), 1 the program
missing. What the old updater needs to finish, by command: `setup` 0 (or 2, then `watcher-running` 0); `watcher-running` 0
running, 2 not running or cannot tell (plugin_setup.py's EXIT_UNCONFIRMED, as v0.6.26 answers; the one contract, review 9
note 6 - the bootstrap's Test-CurrentWatcherStopped, v0.6.26's, reads only 1 as stopped, so it hears "unknown"); `downgrade-state` exactly one line `downgrade: converted a b c d e` or `downgrade: nothing`
with 0, or `downgrade: watcher-running` with 3, anything else is "failed" and the older version is not installed; `remove-entry`
0 removed / 2 none / else failed. The stub core answers every command with code 3 and one stderr line naming it, so each of
those ends as "did not finish / failed / unknown" and nothing is changed; the handover's setup stub ends with 3, which
v0.6.26 reports as "did not finish" and keeps the installation. Re-registering onto the Rust binaries is the Rust `setup`'s
(PLAN 6.4: the Run value to `app\bin\CodexAutoResume.exe`, the protocol to `codex-auto-resume.exe activate`), which every old
updater's path runs; a `run` or `activate` that arrives through car-legacy carries the variable so the core re-registers too.

### The proofs (archives built here: `--version 0.6.27-alpha`, release binaries, `CARGO_BUILD_JOBS=2`, the C# window from `make_gui.ps1`)

```
python build/rust_legacy_bootstraps.py --dist build/dist/rust --version 0.6.27-alpha --ref dev      rc=0, 69 s
  (a) the compatibility entry: 64 - v0.5.2 to v0.6.26-beta.2 (name and Test-Archive, both editions where the tag knows advanced)
  (b) the setup handover: 1 - dev@f72e8b908 (the v0.6.26 final's bootstrap: Test-Archive, Read-SetupHandover, Resolve-SetupProgram)
  these cannot read v0.6.27-alpha as an installed version: v0.6.0-v0.6.8 (11 tags; a final 0.6.27 they read)
python build/rust_edition_audit.py --dist build/dist/rust --version 0.6.27-alpha --rebuild          rc=0
  allowed: CodexAutoResumeSettings.exe, bootstrap.ps1 (the Python audit's own allowances); (a)-(g) found nothing
```

* (d) found the advanced window's one-word literals (`address`, `capacity`, `interrupted`, `requires`, `returned`) in every Rust binary:
  the standard library's panic messages. `rust_edition_audit.plain_word` leaves a one plain lowercase word out for the Rust binaries
  only, by `edition_audit.one_word`'s rule for (c); every other literal and every name is still looked for. Since D18 the MCP
  launcher is car-bin's too and carries the same five (std's io error kinds and `OpenOptions` message, `capacity overflow`,
  the formatter's `returned an error`): `rust_release.RUST_BUILT` is every cargo-built executable and the rule reads them
  all alike. Proof (CI fix seat): a std-only program built with this profile holds exactly these five window literals.
* The allowances (`RUST_EXECUTABLE_ALLOWED`): `codex-auto-resume.exe` and `car_core.dll` x the package name (car-policy's edition look,
  the allowance `ALLOWED` gives `edition.py`); `codex-auto-resume-setup.exe` x the package name (the installer window's and C# setup's,
  `EXECUTABLE_ALLOWED`/`SETUP_ALLOWED`). None is used by the stub core; car-legacy has none.
* (e), and reproducibility: `git archive HEAD` with `advanced/` deleted, built again in a temporary folder (cargo release build of
  `rust/`, `make_gui.ps1`, `rust_release.py`): the same archive bytes, sha256 `6658d8c3b8eae308c32d3697f0f225cf993797879dab3c5cc64fcfb301fd6986`.
  `test_rust_release` also builds one archive twice in two folders from the same inputs and compares. No PDB in either `target/release`;
  the release skill's `privacy_scan.py` on both archives and the eight release binaries: all `clean`, no `X:\Users\` path written.
* Sizes (packed, deflate 9): standard archive 2,483,793 bytes, advanced 3,870,898. App (as `rust_release_budget.json` counts it)
  standard 1.497 MiB, advanced +1.183 MiB (the advanced catalogs); binaries standard 0.437 MiB of which car-legacy 0.262 (python.exe
  292,864 and pythonw.exe 288,256 bytes unpacked), advanced app/bin 0.169 MiB. The budget file keeps release_budget.json's margin rule;
  its binaries keys are the stub core's and P6 sets them again.

### For the next seats

* **S8.2 (install.ps1's migration):** replace `rust_release.INSTALL_PLACEHOLDER` with the real installer; keep it, `Install.cmd` and
  `payload/runtime/python.exe` in the archive (every tag's Test-Archive requires them, and v0.6.26 then holds the archive to Test-Archive
  before it hands over). It must leave `runtime\python.exe` and `runtime\pythonw.exe` (car-legacy) and `app\scripts\plugin_setup.py` in the
  home: v0.5.2-v0.6.26's `Get-InstalledVersion` returns nothing without `runtime\python.exe`, and their repair branch and
  `Invoke-InstalledSetup` name the script. Never ship `app\src\codex_auto_resume\controlcli.py` (it opens `-c ... compat-import`).
  Make `codex-auto-resume-setup.exe` real (BRIDGE.md section 4: `-Handover`, `-Edition`, `-AllowEditionChange`, the install lock, keep
  state, end 0 only when installed) and the core's `setup`, `watcher-running`, `downgrade-state`, `remove-entry` answer the codes and
  lines listed above; re-register the Run value and protocol handler on `setup` and when `CODEX_AUTO_RESUME_LEGACY_ENTRY` is `run` or
  `activate`. Decide the one-file Setup exe (`make_setup.py`) around a Rust archive, and (h) of the audit with it. Run
  `rust_legacy_bootstraps.py` with `--ref <the v0.6.26 tag>` once it exists, and in the release job beside `legacy_bootstraps.py`.
* **P6 (the host):** the watcher host goes to `payload/app/bin/CodexAutoResume.exe` (add it to `rust_release.EDITION_BINARIES` and to
  `RUST_EXECUTABLES` through `BINARIES`; GUI subsystem, checked in `collect_binaries`); it must accept car-legacy's `run` lines as
  handed on (`run`, `--home <home> run`), started with `CREATE_NO_WINDOW` and not waited for. The MCP launcher's retarget (D18) makes
  `codex-auto-resume.exe mcp --home <home>` what car-legacy already hands on. Set the budget's binaries keys from the first full build.
  `test_rust_release.AuditTests` runs the whole audit once on stand-ins (about four minutes: (c) over the real plugin tree).

## S3.3: car-codex's app-server half and the registry (branch `car-v0627-appserver`, 2026-11-25)

Ported from v0.6.26-beta.2 (`git log v0.6.26-beta.2..origin/dev` empty for every file below), the implementation replaced and
not the behaviour (odd reference behaviour kept, each recorded in `plans/v0627-rust/AUDIT-v0628.md`):

| Python | Rust |
|---|---|
| `codex/pairing.py` | `car-codex/src/pairing.rs` (rows are the dicts the inventory lists, read as Python reads a dict) |
| `codex/layout.py` | `car-codex/src/layout.rs` (`snapshot`, `read`, `Watch`; a look's snapshot is an `Arc`, its identity the reference's `is`) |
| `codex/appserver.py` | `car-codex/src/appserver.rs` (`Protocol`, `next_message`, `TextReader` - a text-mode pipe's decoding and newlines) |
| `codex/transport.py` | `car-codex/src/transport.rs` (`Backend`, every child through car-platform's `Spawn`: CREATE_NO_WINDOW) |
| `compat/{standing,report,reported,files,cache,probes,views,evaluator}.py` | `car-codex/src/compat/` (same names) |
| `compat/__init__.py`, `compatio.py` | `compat/mod.rs`, `compatio.rs` (fronts: `pub use`) |
| `compat/model.py`, `compat/permits.py` | already car-machine's (S1.1) and car-policy's (S2.1); re-exported by `compat/mod.rs` |

`car-codex/src/system.rs` is the one trait the half asks Windows through (`System`: the process list, holders,
identities, signers, the environment, the pid, the monotonic clock, `Path.resolve`, the Restart Manager), with
`Platform` over car-platform and `PolicyOs` (car-policy's `Os` over car-platform, for `paths::newest_generation`).
`refold.rs` is `re.IGNORECASE` and `str.casefold()` as the reference's interpreter has them. car-machine gained
`compat::raw_decode` (`json.JSONDecoder().raw_decode`). No new dependency; no new crate edge.

### The diffs (`tests/rustdiff/diffs_codex_appserver_*.py`, `diffs_codex_compat_*.py`, `README.md` "S3.3")

Through `car-harness serve`'s `codexapp.script` (`src/appserver.rs`, `src/registry.rs`), each case a stand-in world, the
reference patched to the same world. Processes started: only `car-fake-codex` (a new bin of car-harness, dev only)
copies in scratch bin folders. Results of the last full runs (release build, reference v0.6.26-beta.2, rustc 1.100.0):

```
pairing   19 known layouts x 4 worlds 2,680 calls; 900 generated row lists 46,729 calls; official_engine 29 worlds 1,032;
          the inventory's 3 s and our own servers 165
layout    120 Watch sequences (kept files in 12 forms) 3,150 calls, the files left equal
appserver next_message over 36 streams (at and past LINE_LIMIT, oversize answers, errors, requests, notifications);
          _unknown, last_result, offers 5,246 cases; usage and queue delete through 29 fake helpers 147 calls, every
          request byte equal (CRLF included), the 25 s call wait and the 4 s end wait as the reference's
transport engine checks over 16 fake engines 80 calls; 38 sends; app_identity, loaded and holder over 36 layouts 540 calls
registry  41 documents (19 data sequences in history, the frozen and advanced data, the community fixture, 11 broken
          copies, 8 bad files) 19,721 standing cases; evidence, evaluate, accepted_word over 99 pairs 28,545; the
          grids 3,484; reports and views 1,861; reported over 29 files 378
compatio  files; 585 cache files read and judged 8,655; imports over 41 documents 401; probes over 13 homes 660;
          views over 14 report files 268; live_report's discovery over 4 fake bins; the evaluator over 40 tick
          sequences 605; run_refresh over 68 stubbed answers 71
```

The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_appserver.py --reference v0.6.26`.

### For P4 and P7

* **car-engine / car-scheduler (P4)** take the backend as `car_codex::transport::Backend` (built with an
  `Arc<dyn System>`, the Codex home and engine, `require_holder`, and `config.version()`; set `bundled` to the data
  file so `engine_verified` reads it): `compatible()`, `engine_checks()`, `app_identity()` (and `app_look`,
  `app_looked_at`, `served_elsewhere`, `server_holds`, `layout`, `app_unmatched_reason()`), `loaded()`, `holder()`,
  `usage()`, `send(thread, prompt, launch_guard)` (the guard is `transport::LaunchGuard`; the dispatch lock goes
  there), `delete_queue()`, `session_holder`, `protocol_results` (the engine's usage wait reads it with
  `appserver::last_result(method, Some(&backend.protocol_results))`). The gate's word is
  `compat::evaluator::Evaluator::tick(Some(&mut backend), &[])`, its report written by it alone; the watcher builds one
  `Evaluator` (a `views::Registry` naming the data files and the home's two config files) and one `layout::Watch`
  (`look(backend.layout.as_ref(), stamp, engine_version)`). Module state the reference keeps per process is per process
  here too (`pairing::reset`, `appserver::reset`, `transport::reset` are for tests and the harness only).
* **The advanced meter (P7, `engine/usage.py` and `codex/inuse.py` from the final tag)** will call `pairing::inventory`
  / `app_running_now` / `own_server` / `own_server_gone` / `own_holder` for who runs, `Backend::usage()` and
  `appserver::last_result` / `BROKEN` for why a read broke, `usage::parse_usage` (S3.2), and `Protocol::open` +
  `call` only for the three `PROTOCOL_METHODS` (anything else is `protocol_method_not_allowed`, as the reference).
  An advanced helper of its own (advanced `codex/protocol.py`) is not this one: it is ported with car-adv.

## The advanced store (seat S7.1a, branch `car-v0627-advstore`, 2026-11-25)

PLAN 5.3 row P7 / S7.1, the store half, into `car-adv` (D19: one crate): `advanced/src/codex_auto_resume_advanced/state/`
(all 19 modules), `ledger.py` (P11), `profiles.py`, `watchlog.py`, `images.py`, ported from v0.6.26-beta.2; none of them
moved on dev after it. Seat S7.1b ports `registry.py`, `arming.py`, the statement, `vocabulary.py` and the policy into the
same crate at the same time: this seat's `lib.rs` lines are `pub mod state; images; ledger; profiles; watchlog;`.

| Python | car-adv |
|---|---|
| `state/session.py`, `schema.py` | `state::session` (`AdvancedState`, the opening, every upgrade step, `_carry_windows`, `attach`, the transactions), `state::schema` (+ `schema_gen.rs`: every statement and table list generated from the tag, so `sqlite_master` is the tag's bytes) |
| `state/arming.py` ... `steers.py` | `state::{arming, spend, records, journal, choices, resets, continuations, prompts, meter, runs, chat, analytics}`, `state::small` (restarts, opens, account, steers) |
| `Scoped` and the eleven handles | `state::scoped` (`Scoped`, `Handle`) |
| the call surface by name | `state::calls::{call, scoped_call}`: every method with Python's positional/keyword binding, the answers as the reference's runner writes them |
| `ledger.py`, `watchlog.py`, `profiles.py`, `images.py` | `ledger` (`ClaimLedger`, `Answer`), `watchlog`, `profiles` (`Profiles`, base64 of Python's `validate=True`; read with car-machine's `compat::loads` - `json.loads` exactly: NaN, the infinities, lone surrogates, any int, the nesting limit's RecursionError - and written as `json.dumps` writes NaN; addresses compared and masked by code points), `images` |

The methods take Python-model values (`car_machine::json::Value`) wherever the reference checks a value's type itself,
so a wrong type is refused with the same class and sentence; values are read and bound as car-store reads and binds
them (`state::sql`), plus Python's own pre-binding errors (OverflowError for an int past 64 bits, UnicodeEncodeError
for half a surrogate pair). `rusqlite` is a direct dependency of car-adv now (already in the lock through car-store).

### The seams (`state/seam/`), for the integration

| Seam | Stands in for | Replace with |
|---|---|---|
| `registry.rs` + `registry_gen.rs` (`Registry` trait, `Definition`, `OptionDef`, `Shipped`, `Listed`; `GLOBAL_HOURLY`, `CORE_DAILY_CAP`, `CORE_COOLDOWN_SECONDS`) | `registry.py`'s REGISTRY, generated from the tag | S7.1b's registry: implement `Registry` over it, delete `registry_gen.rs` |
| `words_gen.rs` (36 StrEnums, `KEPT_NOTICES`) | `vocabulary.py` | S7.1b's vocabulary (same member names, upper case) |
| `hooks.rs` (`held`, `spent_on`, `fresh`) | `engine/hookclaims.py`, `control/sendnow.py` | S7.2 / S7.3 |
| `accounts.rs` (`Host`: seal/open = DPAPI, the saved accounts' mutex, `private` = the folder's DACL, `authfile.sweep`, `swap.unwind`, `token`; plus `check`, `confined`, `own_folder`, `write_atomic`, `mask` as the tag has them) | `codex/authfile.py`, `codex/account.py`, `codex/swap.py`, `win/dpapi.py`, `win/sync.Mutex` | S7.2's codex modules; car-platform's DPAPI and mutex at the entry points |
| `Tokens` (`secrets.token_hex`) | the OS random source | car-platform has none yet: a `BCryptGenRandom` there, handed in by the entry points |

`gen_advstore.py --write|--check --ref TAG` makes the three generated files. Not here: `Scoped.outbox` and `Scoped.feed`
(the courier's, S7.3).

### The diffs (`tests/rustdiff/diffs_advstore.py`, `advstore.py`, `advreference.py`)

The Rust side is car-adv's `examples/advstore.rs` (never shipped; `cargo build --release --locked -p car-adv --example advstore`
in `advanced/rust`, built by the diffs when missing; `CODEX_AR_ADVSTORE_EXE` names another build). The reference is the tag's
core **and** advanced trees (`advreference.py`, PYTHONPATH `src;advanced/src`, `CODEX_AR_EDITION=advanced`). Both run one request
(scratch home, pinned clock, the token counter both use for `secrets.token_hex`) on two copies of one home; every answer and
every file left is compared (SQLite files dumped, sealed profiles unsealed - the seal is a stand-in both use, never DPAPI and
never compared as sealed bytes). Answers by class, and by sentence and word for the store's own errors.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advstore`; or `run.py --build -k diffs_advstore`.
Re-diff at the final: `python -X utf8 tests/rustdiff/rediff_advstore.py --reference v0.6.26`.

### Found and not fixed (another seat's crate)

car-config's `Paths.ensure()` writes the provenance marker `\n`-ended; Python's `write_text` writes it `\r\n` on Windows. car-adv
writes its own markers (`config/advanced/`, `accounts/`) as Python does (`session::owner_text`); the diffs fold only the two
car-config markers' line ends (`advstore.KNOWN`). For S1.1/the integration: car-config's two `fs::write(OWNER_TEXT)`.

### For the later seats

* S7.1b: `arming.py` reads `state.arming()`, `meta()`, `move_capability`/`move_set`/`all_off`/`set_keep_on`/... (`state::arming::Move`
  for `move`'s keywords); `registry.py`'s `Option.takes` and `CapabilityDef.option`/`code` are mirrored in `seam::registry`.
* S7.2/S7.3: a capability's code gets `state::scoped::Scoped`; the ledger is `ledger::ClaimLedger { state }.claim(core_connection, ...)`
  inside car-store's claim (core's `BEGIN IMMEDIATE`; car-store's claim still has only the NULL plug's ledger: the plug's P11 call
  is the integration's).

### Checks (`CARGO_BUILD_JOBS=4`, `. tools/rustflags.sh` first; reference v0.6.26-beta.2, rustc 1.100.0, SQLite 3.54.1 bundled)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked rc=0; cargo deny --locked check: all four ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0 (car-adv's pattern test 1, the rest 0); cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       all 7 standard binaries the same with and without advanced/; profile-path scan: none
python -X utf8 tests/rustdiff/gen_advstore.py --check   generated files (schema, words, registry) match v0.6.26-beta.2
diffs_advstore (release advstore.exe)                Ran 15 tests in 724 s, OK; then LenientProfilesDiff added (16), run with ProfilesDiff: OK
```

The 15 diffs: generated 1; fresh (50 reads with no file, nothing made, then the first write); migrations (files made by the own
code of 17 releases, v0.6.11-alpha's version 1 to v0.6.25's version 9, each opened by a read and by a write, 50 reads each); 16
historic and refused files (versions 1, 2, 3, 6, 7, three newer, a table too many, a column too few, no meta row, the old
ceiling at 12 and at 7, empty, not SQLite); the script (279 calls over every method, 81 refused alike; then each implementation
reads the other's file, 56 reads); choices against their generations (27); the watch limit through a prune; 136 calls of Scoped and
the eleven handles on, off and unset; 2 damaged files x 55 calls; prune (563 lines, two passes); the ledger (19 claims and records
on a schema-5 core state from the tag's own store, and 3 with no advanced file); the claim race (12 rounds, every pairing of Python
and Rust: one granted each round); profiles 43; images 24; the watch log.

Mutation checks (each broken alone on a debug build, its diff run, restored): the generation moved by two (ScriptDiff, op 1); a
choice of the default stored instead of its row taken away (ChoicesDiff, the file); a second resend allowed (LedgerDiff, op 4);
the old words bound read as 8193 (MigrationDiff, v0.6.11-alpha's file); a profile id in capitals (ProfilesDiff, op 41); webp not a
picture (ImagesDiff, op 2); WATCH_LIMIT 96 (ChoicesDiff.test_watch_limit). Each failed; all pass restored.

The harness runs on a 256 MiB stack: values nest as deep as `json.loads` takes them (about 3,000 levels) and Value's clone and drop recurse; the entry points must give the threads that read profiles a stack with that room.

## The advanced edition's registry, arming, statements, vocabulary and policy (seat S7.1b, branch `car-v0627-advpolicy`, 2026-11-25)

Ported into `advanced/rust/crates/car-adv` (one crate, D19), from v0.6.26-beta.2 (none of the seven modules moved on dev since):

| Python (`advanced/src/codex_auto_resume_advanced/`) | car-adv | How |
|---|---|---|
| `vocabulary.py` | `vocabulary.rs`, `vocabulary_gen.rs` | typed enums (`as_str`, `parse`, `ALL`, `ClosedWord`), `ENUMS`, `parse_member`, TRIPWIRES, KEPT_NOTICES, NOTE_FOR_PASS/FAIL: generated |
| `standards.py` | `standards.rs`, `standards_gen.rs` | FAMILIES generated; STANDARDS, DEPARTABLE, DECLARABLE made as the tag makes them |
| `measured.py` | `measured.rs`, `measured_gen.rs` | the build-time table, generated; `Table` is the shape arming reads |
| `policy.py` | `policy.rs` | by hand: `read(reader)`, `Policy`, `windows_reader` over car-platform's `Registry` (KEY_READ only; REG_MULTI_SZ decoded from the bytes the platform returns) |
| `registry.py` | `registry.rs`, `registry_gen.rs` | the definitions, WAITING, INSTALLED_ONLY and SHOWN_ORDER generated as data; `problems`, `Registry` (refusals, requires, required_by, at), `offered`, `shown` by hand. `make` (the factory of a capability's code) is not here: it is the plug's, S7.2 |
| `statement.py` | `statement.rs`, `statement_gen.rs` | `Catalogs` over a directory read at run time (the package's own `locales/`), `words`, `text`, `badge`, `missing`, `complete_in`, `statement`; the key lists generated |
| `arming.py` | `arming.rs` | the pure decisions (`standing`, `warnings_for`, `compat_warning`, `departs`, `held_word`, ...) and `Arming` with every method of the tag, over the seams below |
| `autocheck.py`'s `settled` and `grade` | `seam_autocheck.rs`, `seam_autocheck_gen.rs` | the pure half arming reads, with the reach column of `CHECKS` generated; S7.2's autocheck port replaces it |

`tests/rustdiff/gen_advpolicy.py --write | --check [--ref TAG]` writes the six `*_gen.rs` files from the tag's own package (`advref.run`). The `_gen` modules are `#[rustfmt::skip]`.

**Seams** (`seam.rs`; what later seats and the integration seat replace):

* `StatePort` - every call `Arming` makes of `AdvancedState` (about 35), with `StateFault` (`State`, `Stale`, `Refused(Refusal)`; the tag's `StaleGeneration` and `Refused` are subclasses of `StateError`). S7.1a's state implements it. Rows come as `ArmRow`; the opaque ones (rules, samples, rule ids) as car-machine `Value`s. `spends_since` and `payers` return `Vec`s so the state's order is kept.
* `Edges` - what `arming.py` imports inside a function: the default view and live check (`_view_of`), `compatdata.table_for`, `autocheck.results_for`, `runtime.SENDING`'s points, the Stop hook's declaration, core's power tasks, `account.forget`, `usage.touched/order_problem/previews`, `wrapwords.check_custom/MAX_CUSTOM_LENGTH/PLACEHOLDERS`.
* `CoreView` (in `arming.rs`) - core's records `sweep` is told of.
* The host gives `Setup`: the policy reader (`policy::read(&|hive, name| policy::windows_reader(&registry, hive, name))`), the view and live closures, the clock, and `Catalogs::new(<app>/src/codex_auto_resume_advanced/locales, current-locale)`.

The wire-typed arguments of `arm`, `set_keep_on`, `disarm`, `set_option`, ... are car-machine `Value`s, checked as the tag checks them (`type(x) is int`, a word that is no member), so a request of the wrong type is refused alike. Answers are `Value`s with the tag's key order.

**Proofs** (`run.py` loads them: `python -X utf8 tests/rustdiff/run.py -k Advpolicy`; alone: `PYTHONPATH="src;tests" python -X utf8 -m unittest rustdiff.diffs_advpolicy_words rustdiff.diffs_advpolicy_pure rustdiff.diffs_advpolicy_arming`). They go through car-adv's example `advprobe` (`advanced/rust/crates/car-adv/examples/advprobe`, built on demand by `advref.ensure()` with `cargo build --release --locked --example advprobe`; `CODEX_AR_ADV_PROBE_EXE` names another build), not through car-harness, which belongs to the standard workspace and may not name car-adv. The reference is the tag's own advanced edition (`advref.py`: `src` and `advanced/src` taken out of git, CODEX_AR_EDITION=advanced).

| Module | Holds equal to the tag |
|---|---|
| `diffs_advpolicy_words.py` | all enums and `Enum(text)`, the standards, the measurement table; `policy.read` over generated registry contents and the real reader through a registry stand-in on both sides; the definitions, WAITING, INSTALLED_ONLY, `problems()` over every definition and about 75 mutants of each, options, codes, shapes, registries made of definitions (every refusal, requires, required_by, at, shown), `offered` and the registry for 300 tables; every catalog of the tag, `words`, `text`, `badge`, `missing`, `complete_in` and `statement()` for every definition, on the tag's directory and nine damaged copies |
| `diffs_advpolicy_pure.py` | the pure functions, `standing` included, and autocheck's `settled` and `grade` |
| `diffs_advpolicy_arming.py` + `arming_scenarios.py` | scenarios run by the tag's `Arming` over a Python stand-in for the state and stubs for the edges, and by car-adv's over a Rust one with the same semantics: each step's answer, every call made of the state and the edges in order with its arguments, and the state left. The stand-ins' semantics are written twice and are small on purpose: what is under test is `Arming`, not the state (S7.1a's) |

**For later seats.** S7.1a: implement `StatePort` on the ported state (the stand-in's semantics in `ops_arming.rs` say what each call must do for arming), and `crate::vocabulary` is the one source of the closed words (`JournalCode`, `OptionKey`, `RuleState`, ...): do not generate another. S7.2: a `make` per capability id; `usage::{touched, order_problem, previews}`, `wrapwords::check_custom`, `hookplugin::follow`, `powertasks::follow`, `account::forget`, `autocheck::results_for`, `compatdata::table_for` and `runtime::SENDING` fill `Edges` (usage and inuse come from the final tag). S7.3: `surfaces` calls `Arming` with `Value`s from the wire; `listing`, `statement` and the answers are the tag's JSON. The integration seat: `advanced/rust/Cargo.lock` was not changed by this seat (no new dependency: car-adv already reached car-machine, car-words, car-policy and car-platform); `lib.rs` gained `arming, jsonx, measured, policy, registry, seam, seam_autocheck, standards, statement, vocabulary` and the `_gen` modules, and `Cargo.toml` is unchanged; `tests/rustdiff/advref.py` extracts `advanced/src` as well as `src`, which S7.1a's diffs will want too.

**The final re-diff, one command:** `python -X utf8 tests/rustdiff/rediff_advpolicy.py --reference v0.6.26` lists which files the port reads changed since beta.2, checks the generated tables against the tag, and runs the three diff modules with the tag as the reference.

**Kept oddity.** A statement catalog that is not UTF-8 raises `UnicodeDecodeError` in the tag (nothing catches it) and does so in car-adv (`statement::Undecodable`, through `Catalogs::{catalog, text, badge, words, missing, complete_in, statement}` and `Arming::{arm, statement}`, which therefore return `Result`); AUDIT-v0628.md carries the line ("kept: ...").

## Integration 5 (branch `car-v0627-rust`, 2026-11-25)

Three seats merged with `git merge --no-ff`, in this order, then the cross seams replaced.

| Merge | Seat | What came in |
|---|---|---|
| `5facac3cd` (car-v0627-appserver `fd46204a3`) | S3.3 | car-codex's `pairing`, `layout`, `appserver`, `transport`, `compat/*`, `compatio`, `system`, `refold`; car-harness's `appserver.rs`, `registry.rs`, the `car-fake-codex` bin; car-machine's `compat::raw_decode`; `diffs_codex_appserver_*.py`, `diffs_codex_compat_*.py`, `rediff_appserver.py` |
| `27315a82c` (car-v0627-advstore `ccd03234c`) | S7.1a | car-adv's `state/` (19 modules, `schema_gen.rs`, `seam/`), `ledger`, `profiles`, `watchlog`, `images`, the `advstore` example, `rusqlite` as a direct dependency (`advanced/rust/Cargo.lock` + one line), `diffs_advstore.py`, `advstore.py`, `advreference.py`, `gen_advstore.py`, `rediff_advstore.py` |
| `5662c0892` (car-v0627-advpolicy `a58e0c3ae`) | S7.1b | car-adv's `vocabulary`, `standards`, `measured`, `policy`, `registry`, `statement`, `arming`, `jsonx`, `seam`, `seam_autocheck` (+ `_gen` files), the `advprobe` example, `diffs_advpolicy_*.py`, `advref.py`, `advdiff.py`, `arming_scenarios.py`, `gen_advpolicy.py`, `rediff_advpolicy.py` |

Conflicts, each resolved by keeping both sides: `rust/GROUNDWORK.md` in the second and the third merge (every seat appended its section at the end; both kept, in merge
order) and `car-adv/src/lib.rs` in the third (S7.1a's `images, ledger, profiles, state, watchlog` and S7.1b's `arming, jsonx, measured, policy, registry, seam, ...` are one list
now, with both seats' module docs). The Cargo files, the Cargo locks, `tests/rustdiff/` and the AUDIT notes did not conflict: S7.1b changed no manifest, S7.1a's `car-adv/Cargo.toml`
(`rusqlite = { version = "0.43", features = ["bundled"] }`) and `advanced/rust/Cargo.lock` (the `rusqlite` entry in car-adv's dependency list) came in as written; no new crate, no new edge.

**One reference.** S7.1a's `advreference.py` and S7.1b's `advref.py` both took the tag's `src/codex_auto_resume` and `advanced/src/codex_auto_resume_advanced` out of git
into one scratch folder and ran Python under them. `advref.py` is kept (S7.1b's: it also runs scripts too long for a command line, names the tag's `locales/` and builds and asks
`advprobe`); it gained `trees(tag)`, `popen(...)` and `run(..., timeout=)`, which S7.1a's diffs used; `advreference.py` is gone and `advstore.py`, `diffs_advstore.py` and
`gen_advstore.py` name `advref`.

### The seams, replaced

| Seam | Now |
|---|---|
| S7.1a's `state/seam/words_gen.rs` (36 StrEnums as `&str` constants, `KEPT_NOTICES`) | `crate::vocabulary` (S7.1b's), the one source of the closed words. The store names `Actor::Dashboard.as_str()` and `Actor::ALL`; `py::closed` and `py::is_word` take either an enum's `ALL` or a list of words (`py::Word`); `KEPT_NOTICES` is the enum list. A `match` on a word became a `match` on the parsed member. `gen_advstore.py` makes `schema_gen.rs` alone now |
| S7.1a's `state/seam/registry.rs` + `registry_gen.rs` (`Registry` trait, `Definition`, `Shipped`, `Listed`, the three numbers) | `crate::registry` (S7.1b's `Registry`, `CapabilityDef`, `OptionDef`, `GLOBAL_HOURLY`, `CORE_DAILY_CAP`, `CORE_COOLDOWN_SECONDS`). `AdvancedState` holds an `Arc<Registry>`. The store asks the registry the reference's questions of a value of any type (`registry.get(x)`, `definition.option(key)`, `code(word)`, `takes(value)`, `word in codes`) in `state::ask` (`RegistryAsked`, `DefinitionAsked`, `takes`), so `registry.rs` stays the tag's module. `Shipped` is `registry::shipped(false)`, `Listed(vec![])` is `Registry::new(vec![])` |
| S7.1b's `seam::StatePort` (a stand-in only) | `AdvancedState` implements it (`state/port.rs`): every call `arming.py` makes of the state, with the keywords and arguments it passes, read as it reads them. `Refused`, `StaleGeneration` and `StateError` are `StateFault::{Refused, Stale, State}`. A class the state does not wrap (a `TypeError` of an unhashable wire value) leaves `arming.py` untouched in the reference; a seam result cannot carry it, so it is a panic carrying `port::Raised {class, message}` (D15: the boundary turns it into the answer) |
| S7.1b's `Edges::default_view` and `default_live_view` (`compatio.reader_view`, `compatio.live_view`) | `compat_views::CompatViews`: `_view_of` and `_live_view_of` over S3.3's `compat::views::{Registry, reader_view, live_view}` and car-policy's `settings::load` (the explicit engine is the setting's `codex_exe`, else `CODEX_EXE`). A host's `Edges` delegates to it |
| S7.1b's numbers in `seam.rs` (`RULES_LIMIT`, `RECENT_DAYS`, `DAY`) | kept (typed for `Arming`); a test holds them equal to the state's (`state::port::tests`) |

### The proof that Arming runs over the real state

`diffs_advpolicy_arming.ArmingScenarioDiff.test_over_the_real_state`: the scenario generator of S7.1b's stand-in diff, each scenario run by the tag's `Arming` over the tag's own
`AdvancedState` and by car-adv's `Arming` over car-adv's `AdvancedState` (`advprobe`'s `Real`), each on a home of its own (`<home>/py`, `<home>/rs`), begun empty (the steps make
the rows, options, wordings, rules and journal). Equal: every step's answer, every call of the edges, and the state left as the state's own readers say it (`arming`, `meta`,
`options` and `wordings` of every capability, `rules`, `journal`, `reading`). `arming.aggregated` and `tag_problem` are the real ones here (the stand-in diff patches them). The
stand-in diff stays beside it and still proves what the real state cannot show: every call `Arming` makes of the state and the edges, with its arguments, in order, and the faults
(`faults` in a scenario). 240 scenarios (every other one is made to get somewhere: nothing forbids, a good view and table, a capability that offers Send again armed and then kept on with or without it), 3,531 steps, 167 scenarios writing the journal, Keep on done 140 times, 86 of them with Send again. What the real-state scenarios do not reach: the rows other seats write (overrides, spends,
reset rules, continuations, prompts), which `Arming` reads through `open_overrides`, `spends_since`, `payers`, `reset_rules` and `continuations_pending`; those stay proved by the
stand-in and by S7.1a's own diff of the state's methods. `reading()` with no file answers its keys in a frozenset's hash order (already in AUDIT from S7.1a); the dump sorts them.

### The seams that stay (for the seats named)

* S7.1a `state/seam/hooks.rs` (`held`, `spent_on`, `fresh`): the engine's `hookclaims` and the control's `sendnow` - S7.2/S7.3.
* S7.1a `state/seam/accounts.rs` (`Host`: DPAPI seal and open, the saved accounts' named mutex, the folder's access list, `authfile.sweep`, `swap.unwind`, `token`) and `seam::Tokens`
  (`secrets.token_hex`): car-platform has no DPAPI, no mutex for it and no random source yet; S7.2's codex modules (`authfile`, `account`, `swap`) fill the rest.
* S7.1b `seam::Edges`, but the two views: `table_for` (`compatdata`), `checked_for` (`autocheck.results_for`), `sending_points` (`runtime.SENDING`), `hook_follow`,
  `power_tasks_follow`, `account_forget`, `usage_touched`, `usage_order_problem`, `usage_previews`, `wording_*` (`wrapwords`): S7.2. `seam_autocheck.rs` (`settled`, `grade`) is S7.2's autocheck port's.
* S7.1b `registry`'s `make` (the factory of a capability's code): S7.2's plug. `arming::CoreView` (core's records `sweep` is told of): car-store, at the engine's integration.
* P11: `ledger::ClaimLedger` inside car-store's claim: car-store's claim still has only the NULL plug's ledger; the plug's P11 call is the engine integration's.
* The engine's and the control's seams are not touched here.

### Checks (`CARGO_BUILD_JOBS=4`; reference v0.6.26-beta.2, rustc 1.100.0; the Rust code did not change after the full run)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked rc=0; cargo deny --locked check: advisories ok, bans ok, licenses ok, sources ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0 (car-adv 3: the pattern test, compat_views, port; the rest 0); cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0: car-core-stub, car-fake-codex, car-harness, car_core.dll, codex-auto-resume-setup, codex-auto-resume, python, pythonw
                                                     the same with and without advanced/; "profile-path scan: none in any .exe, .dll or .pdb"
python -X utf8 tests/rustdiff/run.py --build -v      Ran 173 tests in 4,116 s, OK, no skip; by family: diffs 4; S1.1/S1.2 leaves 27 + store 15; S2.1 13; S2.2 11; S3.1 27;
                                                     S3.2 28 (homes 20, pure 8); S3.3 24 (appserver_lines 2, pairing 5, transport 4, compat_io 8, compat_registry 5);
                                                     S7.1a diffs_advstore 16; S7.1b diffs_advpolicy 8 (arming 3, pure 1, words 4)
   then, after the last two additions to the diffs (no Rust code changed): test_over_the_real_state 1 test OK (240 scenarios, 3,531 steps, 167 writing the journal, Keep on
   done 140 times, 86 with Send again); diffs_advstore.LedgerDiff 2 tests OK (21 claims and records, with who paid and whether a channel did)
gen_advstore.py --check, gen_advpolicy.py --check    current (v0.6.26-beta.2)
```

Mutation checks, each made alone on a debug build of the probe or of the `advstore` example, its diff run, restored; every one failed its diff: `StatePort::set_keep_on` drops
Send again (real-state arming); `move_to` drops the revision (real-state arming); `meta` swaps the ceiling for the generation (real-state arming); `takes` ignores a custom range
(`ChoicesDiff`); `keeps_wording` accepts any word (`ScriptDiff`); `CHANNELS` without the unloaded point (`LedgerDiff`'s `channel_paid`). Three first attempts survived and the diffs were
made to catch them: Send again (the real-state scenarios now include ones armed and kept on with it), `CHANNELS` (the ledger diff asks `payers` and `channel_paid`), and `keeps_wording`
(`ChoicesDiff` has no refused word; `ScriptDiff` has).

Python guards (standard lane through `wait_quiet.sh`): `test_repo_hygiene test_privacy_claims test_privacy_bare_hosts test_edition_audit test_srcscan test_stack test_layers
test_structural_invariants test_rust_release`: Ran 130, 2 failures that are not this integration's, both because the tag `v0.6.26` now exists: `test_privacy_claims.WordingTests.
test_the_shipped_list_above_is_not_behind_the_tags` ("add these to `shipped`": `v0.6.26`) and `test_rust_release.PublishedLinesTests.test_car_legacys_list_is_what_the_tags_say`
(`rust/crates/car-legacy/tests/data/published.txt`: run `rust/tools/legacy_lines.py --write`). Left for the main session; the other 128 pass (1 skip).

### Re-diff commands at the final

`rediff_appserver.py`, `rediff_advstore.py` (it now checks `gen_advstore.py` and `gen_advpolicy.py`) and `rediff_advpolicy.py`, each with `--reference v0.6.26`. The arming
real-state diff runs with `rediff_advpolicy.py` (it runs the three `diffs_advpolicy_*` modules).

## Review 4's fixes, and review 5's S2 (seat fix4, branch `car-v0627-fix4`, 2026-11-25)

What `outputs/plans/v0627-rust/REVIEW-int4.md` found and REVIEW-int5's S2, each fixed with a diff that failed before
(`tests/rustdiff/diffs_review4.py`, seven; `car-policy tests/review5_replace.rs`), plus `diffs_policy_hive.py`.

* **car-legacy** takes 44 lines (was 26): `legacy_lines.py` also reads every tag's shipped documents that tell someone to
  run `runtime\python.exe ...\plugin_setup.py` (today only the skill's Commands table) and takes each command in the shapes
  that tag's `build_parser` takes it (read with `ast`: positionals as `{value}`, choices listed, each option alone in each
  spelling), the `install` shortcut made without a settings window (`pythonw.exe [-X ...] watcher-launcher.py|auto_resume.py
  --home <home> status`, shape `shortcut`), and an old settings window's Repair and Desktop-shortcut box (`desktop-shortcut
  make|remove`). `{value}` is what argparse takes as a value (`value_word`). New shapes `command` and `shortcut` in
  `CODEX_AUTO_RESUME_LEGACY_ENTRY`. A `\\?\` spelling of the home is the same script; `codex-auto-resume:` alone is a URI;
  stderr writes never panic and `main_for` catches a panic (exit 1, never 101). The window's bridge and the advanced hook
  launcher (`-c` lines) are listed as never taken. **For S8.2/P6:** the core must answer `enable`, `disable`, `status`,
  `pending`, `cancel <id>`, `stop`, `doctor`, `logs [-n|--lines N]`, `uninstall [--purge]`, `desktop-shortcut make|remove`
  and `--home <home> status`; the shipped SKILL.md still names `runtime\python.exe ... plugin_setup.py` (car-legacy carries it).
* **The bootstrap proof (c)** (`build/rust_legacy_bootstraps.py`, `--entry-from rust/target/release` alone): every tag's
  own runtime\python.exe lines, by its `Invoke-InstalledSetup` (or the repair branch's call operator), against car-legacy and
  the core in a home whose name holds a space, with and without a trailing separator; `test_rust_release.EntryRunTests`.
* **car-machine** gains `pyfile` (Python's share mode READ|WRITE for every open; std-only `replace`/`rename` defaults that refuse a held
  target or an existing one as os.replace/os.rename do; the real MoveFileExW pair is car-platform's `files`, handed to
  car-policy's `Os::replace` and car-config's `Logbook::with_rename` by the binaries, D3 held by check_groundwork.py) and `winpath` (moved from car-config, which re-exports it): the one
  `os.path.realpath`, 3.14.10's, behind the `NtOs` trait. car-platform's `paths::realpath` asks natively (CreateFileW as
  CPython, FindFirstFileW, `links::is_symlink`, LongPathsEnabled); car-config's `Links` gained `readlink` and
  `find_first_file` (defaults: std's read_link, and "cannot ask"; the harness's probe asks car-platform).
* **car-platform**: `homelock` and the other opens through `pyfile`; `registry_reads::policy_places` (the product's
  conversion; the harness calls it); the reader pads a short DWORD/QWORD and retries ERROR_MORE_DATA; FakeRegistry records
  QWORD/BINARY types; `pytext::strip` for CODEX_HOME and the typeface; `addremove::display_name` answers a `Str`
  (`str(value).strip()`, repr of a list or dict, `printable_gen.rs` written by `gen_codex.py` with car-codex's);
  `powerdown::{NO_POWER_ACTION, refuses}`; the probe's `hive_policy`.
* **car-config**: `owns_home` reads with `compat::loads`; the log holds its stream (as FileHandler) and rotates with
  the handed-in rename (`with_rename`; the harness hands `files::rename`). **car-policy**: settings and status-file saves with `Os::replace`. **car-codex**: chains'
  `write_atomically` (`files::replace`) only (its rollout and workspace opens still share delete: for the seat that owns car-codex).
* **The suite's power guard**: `tests/sitecustomize.py`, `scripts/test_parts.py` and `tests/rustdiff/core.py` set
  `CAR_NO_POWER_ACTION`; `tests/test_rust_power_guard.py`, car-platform `tests/power_guard.rs`.
* Re-diff for the final: `python -X utf8 tests/rustdiff/rediff_review4.py --reference v0.6.26`.

## The second review's fixes (seat fix5, branch `car-v0627-fix5`, 2026-11-25)

REVIEW-int5 (outputs/plans/v0627-rust) found four "should fix" and ten notes; this seat took S1, S3, S4 and the notes in
car-store, car-words, car-machine and car-policy. S2 (atomic replace with share-delete) is the fix4 seat's, with every
share-mode question of car-platform and car-config; its review test (`car-policy --test review5_replace`) stays red here.

* **The float repr (S1).** car-machine's `json/float.rs` (the writer, so `pytext::float_repr` and car-store's schedule texts)
  and car-brand's `pyfmt::repr` take x rounded exactly to the shortest length only where that form reads back as x, and
  otherwise `{:e}`'s form (at 46 powers of two the nearest form lies below the narrower half of the interval). Held by
  `tests/support/float_corpus.rs` (both crates' `float_repr_reference` tests: every power of two and the doubles around
  it, the subnormals, the doubles around every decimal exponent, a million random values, against `python -I`'s repr;
  `CAR_FLOAT_COUNT`, `CAR_FLOAT_SEED`), json_reference now draws powers of two, and `diffs_leaves_floats.py` compares the
  texts themselves through car-harness (`pytext.float_texts`, `pyfmt.repr_bits`: a float sent as its bits).
* **The channel's floats (S3).** A NaN or an infinity crosses as `{"$float": "nan" | "inf" | "-inf"}` both ways:
  `tests/rustdiff/diffs.py` `TAGGING` (`tagged`, in `leaves.PRELUDE`, `codexdiff.SCRIPT`, `diffs.encode`, and the store
  diffs' requests), car-harness `leaves::untag` on `leaves.batch`, `codex.script` and the store calls' line and
  `leaves::tag` on the leaves and codex answers. Finite values are written as before, so every existing diff sends the same
  bytes; a dict whose only key is `$float` is the tag's. `policy.batch` (settingsdiff) keeps its own loose reading.
* **BLOBs (S4).** car-store's `value::blob` carries a BLOB as `bytes`: a one-key object `{"\u0000bytes": hex}` whose truth,
  equality, binding (back as a BLOB) and sort are `bytes`'; no check that wants a number or a text takes it. The reference's
  store runner writes `bytes` the same way. car-codex's `Cell` is untouched (another seat's).
* **Notes fixed:** the sign-in's `$` (a final newline kept); `begin()`'s unwind guard (a panic rolls back); `set_enabled`
  with no settings row (TypeError); a NaN caps spacing refuses; car-store's `py_eq` compares an int and a float exactly;
  car-words' `share` is Python's unbounded int and a ValueError on NaN and -inf, `countdown` and `age` read a digit string as
  `int()` does and write every digit of a huge count; `l10n::text` reads its key from the cache without copying the catalog.
* **The product's clock (note 3).** car-policy `classify::clock::Crt` is `LocalClock` over the UCRT's `_localtime64_s` and
  `_mktime64`, the functions CPython's `time.localtime` and `time.mktime` call on Windows, with CPython's own range checks
  (`_PyTime_ObjectToTime_t`, `gettmarg`, `time_mktime`'s sentinel). It is in car-policy, beside the trait and the policy
  that reads it (crate-map: `quiet` is car-policy's), declared as car-brand declares `erfc`; car-platform (D3) was another
  seat's when this was written: the integration may move it there unchanged. `LocalClock::localtime_now` is
  `time.localtime(None)` (`postpone_time(None, ...)` reads the time now). car-harness's `Clock` answers the zone `"local"`
  with `Crt`; the diffs hold it to the interpreter's `time` in this PC's zone (diffs_classify_policy, every edge: before
  1970, the C runtime's last second, time_t's end, fields that carry over or do not fit an int) and in six `TZ` zones with
  summer time, half hours and UTC (diffs_classify_clock.py).
* **Not changed:** lone surrogates in projects/chains/sql (signatures car-codex calls, recorded in the AUDIT); the LF
  catalogs (CatalogsDiff already compares `read_text`'s text and the parsed catalogs, and `gen_catalogs.py --check` the
  tag's LF archive bytes, so a CRLF checkout is no difference).

The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_review5.py --reference v0.6.26`.

## The engine (seat S4.1, branch `car-v0627-engine`, 2026-11-25)

`src/codex_auto_resume/engine/` of v0.6.26-beta.2 (nothing in it moved on dev after the tag; `rediff_engine.py` says so
for the final) into car-engine, and `engine/reconcile.py` into car-scheduler (PLAN 1.2 rows 9 and 10, crate-map).

### What is ported, and how it is shaped

* **car-engine**: one struct, `Engine`, and one `impl Engine` block per mixin, in a module named as the mixin's file:
  `options`, `detect`, `freshness`, `dispatch`, `delivery`, `routes`, `tosession`, `foropen`, `kinds`, `compaction`,
  `announce`, `outcome`, `guard`, `relaxed`, `resend`, `notices`, `impossible` (the watcher's judge, pure), `storeview`,
  `plugrecords` (the part core reads) and `lib.rs`'s `tick`. A record is the store's `dict` (car-machine's `Map`), read with
  Python's operators (`py.rs`); an error is the class the reference raises (`Py<T>`), caught exactly where it catches one.
  The plug is car-policy's `Guarded`, asked at every point the reference asks it; the standard edition's is `Guarded::null()`.
* **car-scheduler**: `Host`, the engine as `ReconcileMixin` sees its `self` (car-engine's `host.rs` implements it), and
  `watch.rs` - `watch_needed`, `watch`, `watch_record`, `guard_queued`, `withdraw_reason`, `withdraw`, `settle`,
  `correlate` - generic over it. Its `Store` and `Source` traits are the part of car-engine's seams the watch reads (the
  graph gives car-scheduler only car-machine and car-policy); car-engine's are their subtraits.
* **Not ported, and why**: `launches.py` (P12's pool: `_workers` asks P12 and every send stays inline, which is what the
  reference does for every answer but the advanced plug's), `recordchannel.py` and plugrecords' record flow (P2: a record
  handed over costs itself as one that raised, `plug_record_check_failed`), and an errand's guards (P8/P22:
  `store.errand_guard` is the advanced store's; an errand is logged `plug_errand_failed`). All three need the advanced
  store (`store/plugclaims.py`, P11's ledger), which car-store does not have; they come with S7.2.

### The seams (`car-engine/src/seam.rs`)

| Seam | What | Replaced by |
|---|---|---|
| `Store` (+ car-scheduler's) | every store call the engine makes, keyword for keyword; `Claim`, `Register`, `Correlate`, `Withdrawn` mirror car-store's option structs | car-watcher's adapter over car-store (the harness's `EngineStore` is the model: car-engine may not name car-store) |
| `Source` (+ car-scheduler's) | `LocalSource`'s calls, implemented for `Codex(LocalSource)` here | as is |
| `Backend` | S3.3's: `app_identity`, `loaded`, `usage`, `send` (with a `LaunchGuard`), `delete_queue`, and the attributes read with `getattr` (`app_look`, `app_unmatched_reason`, `protocol_results`, `session_holder`, `engine_version`, `holder`) as methods whose defaults are the defaults | the integration seat, over car-v0627-appserver's transport |
| `OnceWords` | `control/oncewords.py` (car-control's) | car-control |
| `Given` | the reference's keywords, and what Python reads of the process: `draw` (jitter), `local` (`time.localtime`/`mktime`), `environ` and `windows_languages` (a continuation's language), `os` (the settings' coercion) | car-watcher |

### The proof

`tests/rustdiff/diffs_engine.py` (README, "The engine"). Run 2026-11-25, `run.py --build --reference v0.6.26-beta.2 -k
EngineTraceDiff -v`, release build, 926 s, OK:

```
engine corpus (the frozen modules' flows): 81 scenarios, 1023 steps equal (63 sends, 767 log lines), 201 s
engine random walks: 60 scenarios, 5153 steps equal (122 sends, 2530 log lines), 725 s
```

Equal at every step: the answer, every log line and notification, every backend call with its words, and the whole
`state.sqlite`. The traces reached 40 log events (detection, every wait, the claim, queued, correlated, every outcome,
withdrawals and releases, budgets, needs-you, held after sleep, would_send, a failing notifier).

Mutation check (each rule broken alone in car-engine or car-scheduler, the harness rebuilt, the traces run, restored):
`SETTLED["expired"]` to `cancelled` (e_queued_withdrawn_after_timeout), a settle one second late (o_settle_boundary), a
reset's first look 31 s away instead of 30 (e_reset_inside_half_minute), no `failed` notification
(e_queued_then_not_loaded_withdraws), the delivery window one second longer (e_crash_unknown_then_receipt), a usage
reading reused 31 s (f_usage_cache_boundary), the day's cap wait one second longer (e_daily_cap_wait), one more
withdraw attempt before `queue_cleanup_unconfirmed` (e_cleanup_unconfirmed): all eight failed their traces. Four of
them first survived and are what the four edge scenarios were added for.

### For S4.2 (the scenario proxy) and the watcher

* `Engine::new(store, source, backend, Given)`; public: `tick`, `watch`, `watch_needed`, `apply_policy(values, managed)`,
  `after_sleep`, `activity`, `last_usage`, `limits`, `capacity_limits`, `caps`, `recovers`, `delay_for`, `first_delay`,
  `quiet_until`, `tier`, `allowed`, `observing`, `admission`, `detection_since`, `not_taken_up`, `valid_interruption`,
  `presend_problem`, `collect`, `attempt`, `dispatch`, `transition`, `observe`, `observe_all`; fields `options` (a struct:
  `Options::apply(map)` sets names as `engine.options[...] = v` does), `policy_values`, `managed`, `retiring`,
  `detection_failed`, `handed_waits`, `home_key`, `once_words`, `home_lock`, `engine_state`.
* The frozen modules read two private attributes: `engine._usage_cache` (test_engine 520/525, set to None) and
  `engine._random` (test_ladder_and_guards 290): the proxy needs a way to clear the usage cache and a `draw` it controls.
* `car-harness/src/engine.rs` is the model for the proxy: the backend asked back over the pipe, the launch guard entered on
  the Rust store before the stand-in is told. Words for this time need an asked-back `OnceWords` whose `prune(keep)` is two
  asks (the keys, then the verdicts); not built yet, so no trace uses them (test_once_words_engine is S4.2's to run).
* car-policy's `Channel::send` and `Route::resume` take no launch guard; the reference hands both one. S7.2 adds it with
  the advanced plug.

## The quiet bridge commands (seat S5.1a, branch `car-v0627-bridge5`, 2026-11-25)

PLAN 5.3 row P5 / S5.1, first half: `car-control`'s quiet bridge commands and `serve`'s framing, ported from
v0.6.26-beta.2 (`tests/rustdiff/reference.py`) and held to it by `tests/rustdiff/diffs_bridge*.py`. Nothing under `src/`,
`advanced/`, `gui/`, `build/`, `scripts/` or `docs/` changes.

### Which commands are quiet

Quiet = the answer is read from the state, the settings, the store, Codex's files and the vocabulary, without the engine
acting, the watcher running or a process starting. The few that write, write the settings file or a small file beside the
state, never a recovery.

| | commands |
|---|---|
| **ported** (14 of the 23 plain) | `status`, `settings`, `describe`, `defaults`, `pending`, `pending-all`, `history`, `dashboard`, `strings`, `failure-seen`, `plugin-copy`, `state-access`, `host-app`, `home-suggestion` |
| **ported** (9 of the 28 with an argument) | `update`, `check-setting`, `conversation-message`, `home-dismiss`, `timeline`, `statistics`, `logs`, `preview-continuation`, `once-words` (its read form: no `text`) |
| not quiet, S5.1b | plain: `start-watcher`, `stop-watcher` (start or signal a process), `clear-history`, `cancel-all` (`control.actions` write a recovery), `demo` (signals the icon's event), `power-action` (`control.poweraction`), `detection-check` and `rescan` (the watcher's own rules over Codex's files), `own-report` (below). With an argument: `enabled`, `cancel`, `reset-budget`, `retry-now`, `thread-enabled`, `cancel-thread`, `interruption-recovery`, `postpone`, `unpostpone`, `release-hold`, `thread-tier`, `project-rule`, `once-words` with `text` (all `control.actions`), `startup` (the Run key), `power-arm`, `power-disarm`, `compatibility`, `compat-import`, `compat-refresh` (S3.3's registry; the last starts a process), `diagnostics` (the checkup and the report) |
| in scope, **not yet ported** | `own-report` and `diagnostics`' bundle: `ownreport/{document,evidence,reading}` (about 930 Python lines) and `diagnostics.py`. Both read only; they need `compat.SEND_GATE`, `VERIFIED`, `CHECKED` (car-machine has them), the compatibility view (S3.3, behind `Host::compat_view`) and, for the bundle, the checkup (the watcher's). A command not ported answers `unknown command` (the refusal for any command the bridge has none of), so a build of this crate must not be wired into the window until S5.1b and the two above are in |

`control.wire` (`control/wire.py`) is types only: nothing imports it at run time, and `tests/test_wire_types.py` holds its
keys to the goldens. Its Rust counterpart is the order and kind of every key in the replies built here, held by the 122 golden
cases below; no struct is declared for it.

### What is where

| Python | `rust/crates/car-control/src/` |
|---|---|
| `controlcli.py`: `PLAIN`, `WITH_ARGUMENT`, `encode`, `_payload`, `_argument`, `_emit`, `statistics_days`, `_flag`, `dispatch`, `_plugged`, `serve`, the one-shot `main` after argparse | `bridge.rs`, `commands.rs` |
| `control/errors.py` | `error.rs` (`ControlError`, `Failure::{Control, Other(class)}`, the five refusal tables, `identifier`, `thread_id`) |
| `control/layer.py`, `state.py`, `policy.py` (`set_aside` too) | `layer.rs`, `aside.rs` |
| `control/seen.py` | `seen.rs` |
| `control/records.py` | `records.rs` |
| `control/preview.py` | `preview.rs` |
| `control/tools.py` (`search_logs`, `state_access`, `host_app`; not `show_demo`) | `tools.rs` |
| `control/watcher.py`, its reading half (`_watcher`, `how_it_ended`, `get_status`, `plugin_copy`, `startup_enabled`, `homes_view`) and `control/poweraction.py`'s `read_file`/`power_view` | `status.rs` |
| `oncewords.py` (all of it, writers too) | `oncewords.rs` |
| `homefind.py` (the parts the control layer asks) | `homefind.rs` |

### The seam: `host::Host`

The control layer holds no Windows call (D3). Everything it asks of the machine is one trait, `Host` (a supertrait of
car-store's `open::Windows`): `now`, `store_clock`, `os` (the settings' path questions), `version`, `codex_home`, `managed`
(the policy keys), `environ`, `windows_languages`, `watcher_running`, `startup_value`, `boot`, `compat_view`, `state_access`,
`host_app`, `edition_name`, `superseded`, `installed`, `account_codex_home`, `app_homes`, `local_clock`, `is_symlink`, `lock`.
`SystemHost` answers them over car-platform and car-config; the entry point (car-bin, S5.2) builds one. What it does not
answer yet, and the integration seat must:

* `compat_view` returns `null`: `compatio.reader_view` is S3.3's (`car-codex` `compat/*`). `homes_view` reads the Codex
  version out of it only while another Codex home is configured; with `null` it is as if no report could be read.
* `managed` returns none: the policy keys (`registry_reads::read_policies` into `managed::parse`, only for an installed
  copy) are wired in the harness's `policy.rs` `registry_places`, not here.
* `startup_value` returns none: `startup::current_value(&WinRegistry::current_user())`.
* `local_clock` is `localclock::UtcClock`: car-platform has no reader of the account's time zone yet. A `{reset_time}` in a
  previewed message is written on it; the reference writes it on the zone Windows reports.
* `windows_languages` returns none: the user's preferred UI languages (`GetUserPreferredUILanguages`) are not in car-platform.
* `superseded` returns false and `version` reads the plugin manifest at `project_root`.

The harness's `WorldHost` (`car-harness/src/bridge.rs`) answers all of them from a JSON world, and
`tests/rustdiff/bridgeworld.py` patches the same answers into the tag's modules (`SCRIPT`), so both sides answer for one machine.

### The proofs (reference v0.6.26-beta.2, release harness, `run.py -k diffs_bridge`)

```
python -X utf8 tests/rustdiff/run.py -v -k diffs_bridge     Ran 29 tests in 1450 s, OK
  FramingDiff 4        the goldens' 11 framing cases, 60 request streams, 400 requests, a bad byte past the first 8 KiB chunk
  GoldenCasesDiff 1    122 of the wire goldens' cases, 23 quiet commands, the watcher running and not
  WorldDiff 8          watcher x Run value, Run values that belong to the home, 7 sets of administrator's keys, install lock x superseded,
                       11 language/environment worlds, host-app x access (36), the compatibility view with Codex homes (6), the installed copy's home suggestion
  DamagedDiff 10       no home / no state, unreadable states, other schemas, v0.6.10 and v0.6.13 states with and without the install lock,
                       17 settings files, 14 failure-seen files, 9 logs x 17 queries, 20 once-words files, 1,500 records
  WriterDiff 3         update (33 shapes), check-setting, conversation-message (past the limit of 50), preview-continuation (8 languages)
  EdgesDiff 4          statistics days, timeline ids, the lists in each watcher state, the one-shot form (24 shapes)
cargo test -p car-control   8 unit tests (command lists, the set-aside stamp, splitlines, payload, the wire's candidates, days and flags, ids, refusals)
```

Found by the diffs and fixed here (not in the reference): none in car-control's answers; four faults of the diffs themselves (a home's key hashes its path, so
each side now runs at one path; the harness needs the reference's scratch environment because the real mutex is named from the user's home folder; a lone
surrogate cannot be encoded into a request stream; the one-shot form of a plain command takes no argument).

Mutation checks (a rule broken in car-control, the dev harness rebuilt, the named diff run; each one fails it, the source restored after): the
byte order mark no longer stripped from a request line and an empty text argument no longer "no argument" (`FramingDiff`); the log search
folding case with `lower()` instead of `casefold()` (`DamagedDiff.test_logs`); the failure-seen file's size limit 4096 -> 8192
(`DamagedDiff.test_failure_seen_files`; the first run did NOT catch it - no file past the limit held a seen time the next acknowledgement would
keep - so three cases of exactly 4,096, 4,097 and 9,000 bytes were added, and it then failed); the administrator's refusal sentence changed
(`WorldDiff.test_managed_keys`); the heartbeat's staleness 180 s -> 0.5 s (`GoldenCasesDiff`); the statistics bound 3650 -> 3651
(`EdgesDiff`).


### For the next seats

* **S5.1b** (the rest of `controlcli`): add each command to `commands.rs::run` and the actions to `layer.rs`'s `Control`; the
  `Host` has what they need except the registry writer, the process starter and the icon's events. Nothing here sends.
* **S5.2 / car-bin**: `bridge::serve(&control, &mut stdin, &mut stdout)` and `bridge::one_shot(&control, argv, stdin, stdout)` are
  `bridge serve` and `bridge <command> [-]`; argparse (usage errors, `--home`) and the choice of `SystemHost` are the binary's.
  `serve` reads 8192-byte chunks like Python's text stream and ends with code 1 where Python's loop would die (bytes that are not
  UTF-8; a reply or id holding half of a surrogate pair), after answering the lines before it.
* **P6**: the set-aside sweep (`controlcli.sweep_soon`) is the watcher's (`setaside.py`); `serve` here does not start it.
* The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_control.py --reference v0.6.26`.

## Integration 6 (branch `car-v0627-rust`, 2026-11-26)

Four branches merged with `git merge --no-ff`, in this order, then the seams the merged code allows wired.

| Merge | Branch | What came in |
|---|---|---|
| `767fa6855` | car-v0627-fix4 `80a2bf01a` | REVIEW-int4's fixes and REVIEW-int5's S2: car-legacy's 44 lines, car-machine `pyfile` (Python's share mode; std-only `replace`/`rename` defaults), car-platform `files::{replace, rename}` (MoveFileExW) handed to car-policy (`Os::replace`) and car-config (`Logbook::with_rename`), one realpath, the power-action guard, the policy places, the registry notes, CRLF markers, check_groundwork's D3 rule |
| `6f9a21c20` | car-v0627-fix5 `64b8fee59` | REVIEW-int5's S1, S3, S4 and notes: Python's float repr, the `{"$float": ...}` tag, car-words' share and countdown, car-store BLOBs, the sign-in newline, `begin()`'s rollback, the product's `LocalClock` (`Crt`) |
| `84270b023` | car-v0627-engine `018e7679d` | S4.1: car-engine and car-scheduler, car-harness `engine.rs`, `diffs_engine.py`, `enginerun.py`, `rediff_engine.py` |
| `501dc8b4a` | car-v0627-bridge5 `3c4434ca3` | S5.1a: car-control's quiet bridge commands and `serve`, car-harness `bridge.rs`, `diffs_bridge*.py`, `bridgeworld.py`, `rediff_control.py` |

Conflicts, each resolved by keeping both sides:

* `rust/GROUNDWORK.md` and `tests/rustdiff/README.md` in merges 2-4 (every seat appended a section; all kept, in merge order). fix5's README
  had been committed with CRLF and a raw NUL byte (the BLOB key), so git took it for binary and the whole file conflicted; it is LF text
  again and the key is written `\u0000bytes`, as the GROUNDWORK and the code write it.
* car-harness `main.rs` (merge 3): S3.3's `codexapp.script` arm and S4.1's `engine.*` arm at the same place; both arms.
* car-harness `Cargo.toml`, `lib.rs`, its `Cargo.lock` entry and check_groundwork's car-harness edge list (merge 4): S4.1's car-engine and
  car-scheduler beside S5.1a's car-control; the edge list is the union.
* fix4 and fix5 touched the same crates (car-machine, car-policy, the harness, tests/rustdiff) but no function on both sides; the one
  shared file, `car-policy/tests/review5_replace.rs`, was the same on both. Both reviews' tests pass on the merge (`review5_replace`,
  `review5_float_repr`, `review5_watcher_status` and the rest of the `review5_*` and `diffs_review4` tests).

### The seams, wired

| Seam | Now |
|---|---|
| fix5's `LocalClock` (`classify::clock::Crt` in car-policy, `extern "C"` there) | the trait and `Tm` are car-machine's `localclock` (car-policy's `classify::clock` re-exports them, so every path stays); `Crt` is car-platform's `localclock::Crt`, unchanged (D3: the C runtime's reading of Windows' zone is a Windows call). car-policy takes it as a parameter as before, car-engine through `Given::local`, car-control through `Host::local_clock` (no default now: `SystemHost` answers `Crt`, the harness's `WorldHost` the UTC zone bridgeworld.py pins); car-harness's zone `"local"` is car-platform's `Crt`. check_groundwork: only car-platform declares `extern "C"` too; the C library's pure math is named in `C_MATH` by file and linked function (car-brand's `erfc`) |
| car-control's file writes and opens (`std::fs`) | once-words and failure-seen replace with car-platform's `files::replace` (os.replace), the settings' set-aside renames with `files::rename` (os.rename: a name taken meanwhile is refused, never replaced), their temporaries opened as `mkstemp` opens them, every read through car-machine's `pyfile`; `PlatformOs::replace` is `files::replace`, so a settings save through `SystemHost` is os.replace |
| car-control `Host::compat_view` (null) | `SystemHost`: `compatio.reader_view(paths, settings=...)` over car-codex `compat::views` (the bundled data beside the package, `src/codex_auto_resume/data/` until P6 places it; the report and the cache in the state folder; a failure is no view, as `homes_view`'s `except Exception`) |
| car-control `Host::startup_value`, `Host::managed` (none) | `startup::current_value` (an unreadable Run key is none, as `startup_enabled`'s `except StartupError`); `managed.parse(policykeys.read())` for an installed copy only, over `registry_reads::policy_places` |
| car-engine `Backend` (S3.3's) | `car_engine::transport::Transport` over car-codex's `transport::Backend`: every call and every `getattr` attribute is the backend's own (None where Python's attribute is unset; `protocol_results` `{method: (code, seq)}`; `session_holder` the pair). The reference enters `store.submission_guard(key)` around its one Popen; the engine's guard runs a body inside the store's lock, so car-codex's `send` is split (preflight, the one start, the receipt) and gains `send_within(thread, prompt, scope)`, which starts the process inside the guard's body and answers every case as `send` |
| car-codex's opens (fix4 left them) | the rollout, workspace, layout, chains, source and compatibility-file reads through `pyfile`; the layout and compatibility files' atomic writes replace with `files::replace`; `PolicyOs::replace` is `files::replace` |
| car-codex `sql::Cell` (a BLOB as an empty list) | fix5's `value::blob` is car-machine's `pybytes` (car-store re-exports it); a BLOB cell is that value, equal only to the same bytes; `row_status` reads it as bytes (hashable, "other"); codexdiff writes the reference's `bytes` the same way |
| S7.1a's line-end fold of car-config's two markers (`advstore.KNOWN`) | gone: fix4 writes them CRLF |

### The seams that stay

* car-engine `Store` (+ car-scheduler's): car-watcher's adapter over car-store (S6.1); the harness's `EngineStore` is the model.
* car-engine `OnceWords`: car-control's `oncewords` answers it, but car-control may not be named by car-engine and car-engine not by
  car-control (PLAN 1.3); car-watcher, which sees both, implements the trait over `car_control::oncewords::OnceWords`.
* car-engine `Given` (jitter's draw, `local`, `environ`, `windows_languages`, `os`): car-watcher builds it, `local` being car-platform's
  `Crt` and `os` car-control's `PlatformOs`.
* car-control `Host::windows_languages` (none): `GetUserPreferredUILanguages` is not in car-platform yet. `Host::superseded` (false) and
  `version` (the manifest at `project_root`): the entry point's (S5.2).
* The engine's launch guard on car-policy's `Channel::send` and `Route::resume` (S7.2), P11's ledger inside car-store's claim, the advanced
  plug's errands: as S4.1 and Integration 5 left them.
* The BLOB in car-codex is `bytes` where it is compared, bound back, told by kind and by status; `pyval::hashable` and `pyval::truthy`
  read it as the dict it is carried as (a BLOB of no bytes reads true; `hash()` of a BLOB raises; the empty list it was
  carried as before read false and raised too). No diff reaches either; a later seat that needs them asks `pybytes::blob_bytes` first.

### Found by the full run and fixed here

* `diffs_advstore` (8 of 16 failed, `config/.owned-by-codex-auto-resume` LF on the Rust side) and `diffs_advpolicy_*` compared car-adv's
  `advstore` and `advprobe` examples as built on 2026-11-25, before these merges: both modules built them only when missing, and
  `run.py --build` built the harness alone. `diffs_review4.LegacySkillLines` skipped (no `python.exe`). `run.py --build` now also runs
  `core.build_rest()`: the standard workspace's release binaries and car-adv's two examples. With fresh binaries all 31 tests of those
  three modules are equal, none skipped.
* `diffs_codex_homes.test_odd_rows` (after the BLOB change): `values::row_status` told a BLOB by the empty list it used to be carried
  as; it asks `pybytes::blob_bytes` now.
* `test_repo_hygiene.test_every_uuid_is_obviously_synthetic`: fix4's `diffs_review4` used the RFC's example UUID; a fixture one now.
* fix4's `diffs_review4` docstring `homes\*.lock` (a SyntaxWarning) is raw.

### Checks (`CARGO_BUILD_JOBS=4`; reference v0.6.26-beta.2, rustc 1.100.0)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked rc=0 (62 test binaries ok, among them
                   review5_float_repr x2, review5_replace, review5_watcher_status, review5_share, files_replace, power_guard; car-engine's
                   transport tests 2); cargo deny --locked check: advisories ok, bans ok, licenses ok, sources ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0; cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0, every binary the same in both folders, with and without advanced/;
                                                     "profile-path scan: none in any .exe, .dll or .pdb"
python -X utf8 tests/rustdiff/run.py --build -v      Ran 220 tests in 7,053 s: 211 OK, 8 FAIL and 1 skip, all from the stale advanced
                                                     examples and python.exe (above); after `build_rest`, `-k diffs_advstore -k diffs_advpolicy
                                                     -k diffs_review4`: Ran 31 in 1,123 s, OK, no skip. By family (220): diffs 4; leaves
                                                     (machine 5, domain 4, words 5, brand 8, config 2, log 2, codex 1, floats 1, config_text 1)
                                                     29; store 15 + store_values 5; S2.1 classify 14 (clock 1, continuation 3, failures 3,
                                                     policy 3, vocab 4); S2.2 settings 11; policy_hive 1; S3.1 platform 27; S3.2 codex 28 (homes
                                                     20, pure 8); S3.3 24 (appserver_lines 2, pairing 5, transport 4, compat_io 8,
                                                     compat_registry 5); S4.1 engine 2 (corpus 81 scenarios, random walks 60); S5.1a bridge 29
                                                     (bridge 4, commands 25); S7.1a advstore 16; S7.1b advpolicy 8; review4 7
```

Mutation checks, each alone on the release harness, its diff run, restored: car-codex `send_within` answering `queue_consent_refused`
for a guard that raised before the start (`(_, None)`) failed `TransportDiff.test_sends` (case 36, `{"enter": "raise"}`: the
reference `queue_spawn_failed`); `row_status` without its BLOB arm (the state before its fix) failed `HomeDiff.test_odd_rows`
(`passed_over` raised TypeError where the reference answers).

Python guards (standard lane through `wait_quiet.sh`): `test_repo_hygiene test_privacy_claims test_privacy_bare_hosts test_edition_audit
test_srcscan test_stack test_layers test_structural_invariants test_rust_release test_rust_power_guard`: Ran 136, 1 failure
(`test_every_uuid_is_obviously_synthetic`, fixed above; `test_repo_hygiene` then OK alone), 1 skip. Integration 5's two reds are green:
`test_privacy_claims`' `shipped` has v0.6.26, and `legacy_lines.py --write` read 65 refs to v0.6.26 - no new line, so car-legacy's 44 and
its ACCEPTED stay and only `published.txt`'s ranges and counts moved.

### For the next seats

* **S6.1 (car-watcher)**: builds `Engine::new(store, Codex(LocalSource), Transport::new(car_codex Backend), Given)`; implements car-engine's
  `Store` over car-store (the harness's `EngineStore`) and `OnceWords` over car-control's; `Given::local` is car-platform's `Crt`, `os`
  car-control's `PlatformOs`.
* **S4.2 (the scenario proxy)**: `backend.send_scoped` in car-harness `appserver.rs` is the model of a send through the engine's guard.
* **S5.2 / P6**: `SystemHost::compat_view` reads the bundled data at `<project_root>/src/codex_auto_resume/data/`; the archive's layout
  decides where it is.
* **The final's port**: `rediff_*.py --reference v0.6.26` as each seat named; nothing of this integration needs one of its own (the
  wiring is held by the existing diffs, and `test_sends` covers `send_within`).
## The scenario proxy (seat S4.2, branch `car-v0627-proxy`, 2026-11-25)

PLAN 4.3's row "Frozen scenario modules" and 5.3's P4: the fifteen modules of `tests/neutral.py` MODULES run, unedited,
on car-engine. With `CODEX_AR_CORE=rust` the shim's finder (`tests/rustdiff/shim.py`) also passes
`codex_auto_resume.engine`, and as it loads its `Engine` becomes `tests/rustdiff/engineproxy.py`'s: every module that
builds an engine (a test's Harness, `runtime/app.py`, `rescan.py`, `checkup.py`) builds car-engine.

* **One `car-harness serve` per test process, one session per engine** (`car-harness/src/proxy.rs`: `proxy.open`,
  `proxy.call`, `proxy.close`). The store, the source and the backend stay the test's own Python objects; car-engine's
  `Store`, `Source`, `Backend` and `OnceWords` seams, the clock, the log, the notifier, `home_lock`, `engine_state`,
  `connectivity`, jitter's draw (`engine._random`), `time.localtime`/`mktime`, `os.environ` and the Windows languages
  are all asked back over the pipe (`AskStore`, `AskSource`, `AskBackend`, `AskOnceWords`, `AskLocal`), each call with
  the reference's own arguments and keywords (`reserve_detailed(..., ledger=plug, carried=frozenset(Point...))`,
  `hold_changed(..., actor="engine")`, `latest_failures(since[, needs_you=...][, admissible=True, shapes=True])`).
* **A send is handed the reference's own guard**: `LaunchGuard::key()` (new, a default method) names the record, and the
  Python side passes `launch_guard=store.submission_guard(key)` of the test's store, which the backend enters as it
  enters the reference's. `with store.submission_guard(key)` inside car-engine (routes) is `store.guard_enter`/`_exit`.
* **Callbacks and nesting**: `once_words.prune(keep)` is asked with `keep` kept on the Rust side; each
  `{"callback": [key]}` line is `keep(key)`, which may ask again. A request line read while an answer is awaited is
  another engine's call made from inside that answer (test_engine 16: a backend that ticks a second engine during the
  first one's send) and is answered nested; the same engine re-entered answers `RecursionError`.
* **The attributes the modules read** are the proxy's own (`store`, `source`, `backend`, `clock`, `log`, `notify`,
  `plug`, `home_lock`, `engine_state`, `connectivity`, `once_words`, `retiring`, `home_key`, `language`, `options`,
  `policy_values`, `managed`, `detection_failed`, `handed_waits`); `options`, `retiring`, `once_words` and `home_key`
  go to car-engine before each call and what it holds comes back after it, so `engine.options` starts as car-engine's
  own defaults. `_usage_cache = None` is `Engine::clear_usage_cache()` (new); `_random` is the draw.
* **Panics as a test's input**: a seam object that raises `engineproxy.Panic` makes car-harness panic at that call, so
  D15's boundaries inside the engine can be held (the review's S1 diffs).

### The proof

`python scripts/test_parts.py --worker tests --report X.json <the 15 modules>` on the Python engine and again with
`CODEX_AR_CORE=rust`, one process at a time, then `--compare`: **456 test ids, 456 pass on both, 0 differ** (Python
530 s, Rust 863 s, 2026-11-25). `test_once_words_engine` (S4.1's) is among them: the words for this time, their prune
included, run on car-engine. The LEDGER stays empty: no frozen test needed P12's pool, P2's record channel, an errand's
guards or anything else not ported, because the standard edition never reaches them.

Mutation check (each rule broken alone in car-engine, the harness rebuilt, test_engine and test_outcomes run on the Rust
lane, the file restored): the day's cap one claim late (`>=` to `>`, dispatch.rs) failed test_engine T24 and test_outcomes
T24; the settle five seconds short (outcome.rs) failed test_engine T14 and test_outcomes T14; one more queue launch
before `queue_launch_retry_limit` (delivery.rs) failed test_engine 15 and test_outcomes T29. The Python lane is green on
all three, so the proxy really runs car-engine.

### For the next seats

* The watcher (S6.1) builds its engines from car-store and car-codex directly; the proxy is the test lane's only.
* `rediff_engine.py --reference v0.6.26` re-diffs the engine; the frozen modules themselves are held byte for byte by
  test_released_calls, so the proxy's proof is re-run as is against a new tag's engine (the two `--worker` runs above).

## Review 6 in car-engine (seat S4.2, the same branch, 2026-11-26)

`outputs/plans/v0627-rust/REVIEW-engine.md`; its traces are `tests/rustdiff/diffs_review6.py` (cherry-picked).

* **S1 (D15)**: a panic costs what the reference's exception costs, never the tick. `car_scheduler::caught` is
  `try/except Exception` for a panic too, at every per-record boundary the reference keeps (tick's attempt loop,
  `observe_all`, the watch's rows, `resend_uncertain`, around the send) and tick's `finally` (`usage_checks_left` runs,
  then the panic goes on); and `caught.rs` wraps every seam `Engine::new` is handed (`Store`, `Source`, `Backend`,
  `OnceWords`), so a panic inside S3.3's transport, car-codex or car-store is the exception at that call and meets the
  reference's own `except` there (observe's `seen = None` was the one the diffs found besides the review's list). The
  watch budget is elapsed seconds against the budget, as the reference's monotonic deadline: 1e300, inf or NaN is no
  deadline, a negative one ends the pass at once (`Duration::from_secs_f64` panicked). Proof: `diffs_engine_panics.py`
  (EnginePanicDiff, 6 cases: the reference's seam raises where car-harness panics, through the scenario proxy; 5 failed
  before the fix) and review 6's `r6_watch_budget_huge`.
* **Note 1**: `Options` holds what `Engine(options=...)` was given as the reference does: the counts it only compares
  with (`max_queue_retries`, the day's cap, the withdraw attempts) as floats, the budgets, `max_chain_seconds` and the
  ladder's steps as the numbers given (`int` or `float`), so `max_queue_retries` 2.5 fails at the third launch that never
  started, not the second; `delay_for`/`first_delay` answer the step as given (`max(60, step)`). Proof: review 6's
  `r6_queue_retries_fraction`, and `s4_fraction_options` (below).
* **S2**: the harness's engine session launches **inside** the launch guard. `AskBackend::send` (car-harness/src/engine.rs)
  asks the stand-in to launch from within `launch_guard.enter`'s body, while car-store's write lock is held, as
  codex/transport.py runs `Popen(... queue ...)` inside `with launch_guard as permitted:`. Before, it entered the guard,
  let it go, and launched after: a Cancel, a Pause or a conversation switched off committed in between would have been
  launched past. **This file is the model for the product backend: a Backend launches inside `enter`'s body, never
  after it** (seam.rs `LaunchGuard` says so). Proof: `diffs_launch_guard.py` (the stand-in finds the write lock held at the
  launch; it found it free before the fix). The scenario proxy needs none of this: it hands the backend the
  reference's own guard object.
* **S5** (left to car-watcher, S6.1): the store adapter car-engine is traced through, `EngineStore` (actor "engine" on
  every update, `hold_changed`/`hold_waiting`'s actor, every option struct mapped to car-store's, the launch guard), lives
  only in car-harness. car-watcher writes the product's over car-store; it should move this one into a crate that may
  name both (or a car-store feature) and have the harness call it, so the traces hold the product's adapter.
* **S4**: `diffs_engine_inputs.py` (EngineInputsDiff, 12 scenarios, equal): an administrator's policy (the `policy` step's
  `managed`: DisableAutoResume, ForceObserveOnly, quiet hours beside a person's, MaxRecoveryAttempts' clamp ending a chain
  `retry_budget_exhausted`), `impossible.rs` (the `judge` step, `car-harness/src/judge.rs`: the recovery rules' looks,
  gaps and clock going back, the detection rules' ticks, the words, `usage_reason` and `recovery_facts` over their edges),
  the backend's getattr attributes (`backend` step's `attrs`, asked back as `backend.getattr`/`backend.holder`:
  `app_look` "unmatched", `protocol_results` of a broken usage probe, `engine_version`, `session_holder`, `holder`),
  `activity` and `last_usage` (in `facts`, a reading with windows), a clock set back over a cached usage reading and a
  cached loaded state, and Note 1's fractional options. All equal at the first run: nothing to fix in car-engine.
* **S3 (done by the section below, seat plugtrace)**: the plug's answer paths were traced only with the NULL plug. What a scripted test
  plug over car-policy's `Plug` (and the reference's `domain/plug.Plug`, the same script on both sides, handed through
  `engine.open`'s and enginerun's `plug`) would hold, and needs no advanced store: P7 `schedule` (`resend.rs`'s
  `_resend`/`watch_resent`, `relaxed.rs`'s EARLY and SEND_NOW), P17 `admission` (ADMIT, CAPACITY, `known_failure`'s
  relaxations, `_refused`'s held and capacity branches), P16 `unloaded` answering QUEUE_FOR_OPEN and TO_SESSION
  (`foropen.rs`, `tosession.rs`, with `holder`/`session_holder` now askable), P6 `outcome` in `transition`, P14 `moved`
  and the claim's `carried` set. What needs S7.2's real plug: a P16 `Route` (`routes.rs`: `route.resume` takes no launch
  guard yet, `Channel::send` neither), P2's records and P11's ledger, P8/P22 errands, P12's pool.

### Checks (2026-11-26, HEAD of this section's parent `fbe947a8b`)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked rc=0; cargo deny: all four ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0; cargo deny: all four ok
check_groundwork OK (17 standard crates, 3 advanced); check_rebuild.sh rc=0 (identical, no profile path)
run.py -k EngineTraceDiff -k EngineReview6 -k EnginePanicDiff -k EngineInputsDiff -k LaunchGuardHeld: 17 tests OK
  (1 expected failure, B1), 676 s; corpus 81 scenarios / 1,023 steps and walks 60 / 5,153 steps equal
the 15 frozen modules on CODEX_AR_CORE=rust after every fix: 456 test ids, 0 differ from the Python lane
```

## The plug's answer paths in the engine's traces (seat plugtrace, branch `car-v0627-plugtrace`, 2026-11-26)

`outputs/plans/v0627-rust/REVIEW-engine.md` S3, which the section above left open: every trace asked the NULL plug alone, so none of
P3-P22 was ever answered. Now a scripted plug, the same on both sides, answers; `python -X utf8 tests/rustdiff/run.py --build -k
EnginePlugDiff` (README, "The plug's answer paths"; `diffs_engine_plug.py`).

### What is built

* **The script** (`tests/rustdiff/enginerun.py`, `Script`): one object on the test's side - the points the plug `wants` and, per hook,
  rules (`when` facts of the record and of the hook - `name` at a gate, `to` at a move, `outcome`, `due_at` - then `answer`, `skip`,
  `times`). An answer is a word, a text, a list, `null` (DEFER), `raise` or `panic`. A `plug` step changes it mid-scenario. Every
  question it is asked is written down in the trace (`["plug", hook, what it was handed..., answer]`), beside the backend's calls.
* **Both sides ask that one object**: the reference's Engine is handed a `domain.plug.Plug` (`scripted_plug`) whose hooks call the script;
  car-engine is handed car-harness's `plugscript.rs`, a test double of car-policy's `Plug` trait (`Scripted`) whose hooks ask the same
  script back over the harness pipe (`plug.<hook>`; its asker is a closure, so a native script can replace the pipe later). P4 words,
  P6, P7, P14, P15, P16's two queued answers, P17, P18, P19, P3 and `wants` are answered; P5 is asked and DEFERs, a hook that raises is
  an `Err` and one that panics unwinds (D15, caught in `Guarded`, counted in `failures`; `facts` carries `plug_failures` on both sides).
* **What the claim is told** (`note.claim`): `carried`, `relaxed`, `resend`, `forced`, `caps`, `quiet_until` and whether the plug is not
  NULL's, of every claim, on both sides - P11's ledger would pay for exactly these, and nothing else of a trace shows them.
* **Three tests**: `scripted_paths` (63 scenarios, 878 steps, named `pl_*`: P3 HOLD at each of the seven gates, P4's words, P15 and P5
  asked, P7's EARLY (a record waiting for its reset, for usage), SEND_NOW (a retry's wait, a postponement, the spacing, an attempt budget
  of the person's own, never quiet hours or a reset ahead) and RESEND (a lost send found no trace of, a gate that holds it, a duplicate
  proof afterwards), P7 HOLD and unknown words, P14 and P6 (every move; outcomes; none while paused), P16 QUEUE_FOR_OPEN and TO_SESSION
  (kept, taken back, expired, no holder), the app closed with a holder, P17 ADMIT/AS_TIMEOUT/CAPACITY/VERIFIED_RESET with known_failure,
  an answer outside `takes`, P18 and P19 gone and cancelling, bad answers, a hook that raises or panics);
  `corpus_with_a_deferring_plug` (the 81 corpus scenarios again with a plug that wants every point and defers: every call site's
  question and the claim's `carried` compared as asked); `random_walks_with_a_plug` (40 of `generated`'s walks with a script drawn from
  the seed, `CODEX_AR_PLUG_WALKS`). `CODEX_AR_PLUG_ONLY=name,name` runs the scenarios starting with one.
* `rediff_engine.py --reference v0.6.26` runs both trace sets, and lists the plug's and the store's claim files beside the engine's.

### What the first run found: car-store's claim, not car-engine

The first run of `scripted_paths` differed in 11 of 58 scenarios, every one a relaxed claim (EARLY, SEND_NOW, RESEND, ADMIT, CAPACITY):
car-engine asked the plug and carried out its answers exactly as the reference does, but car-store's `reserve_detailed` was the NULL
plug's alone (`ledger.null` decides every plug branch in `store/ledger.py`, `validate.reset_refused`), so each relaxation was refused
where the reference grants it. Fixed in car-store (commit `f8a1c71cb`): `Claim` carries `plugged` (`not ledger.null`) and `carried`, and
`claims.rs` has `_early_claim`, `_forced_claim`, `reset_refused`, the full `_relaxation_refused` (capacity's 24 hours, admitted) and a
granted `_resend_claim`; car-engine's seam `Claim` says `plugged` (dispatch and routes). Nothing in car-engine itself differed: every
other scenario was equal at the first run, the corpus and the walks included. **P11 itself is still not asked**: a claim whose plug is
not NULL's treats the ledger as one that always answers DEFER and never raises - no savepoint, no authorizer, no hold, no `broke` -
because that needs `store/ledger.py`'s connection and the advanced store (S7.2: `Ledger` is an empty trait in car-policy today).

### What needs the advanced plug (S7.2), by name

* **P11, the ledger's hold and its failure** (`_ledger_holds`: HOLD, a raise on a claim that `carried` something, `_refused`'s held
  branch) and what the ledger reads on the claim's connection; `Claim.carried` is compared, but nothing pays for it.
* **P2** records (`recordchannel.py`, `plugrecords.py`'s flow: a handed record costs itself as one that raised), **P5** a channel
  (`Channel::send` takes no launch guard; CLIENT_ID at P15 and a channel's `pools()` are taken only with one; the scripted plug asks P5 and
  P15 and they cannot be carried out), **P8** and **P22** errands (`store.errand_guard`), **P12**'s pool (`launches.py`), **P16**'s
  `Route` (`routes.rs`'s `route.resume`, `still_unloaded`; `Route::resume` takes no launch guard; SILENT), **P9**, **P13**.
* **P20** (notices told to the plug) is `runtime/app.py`'s - the watcher's - and **P21** the power action's, neither the engine's:
  `Guarded::notice` and `power` are car-watcher's to trace. The engine's own notices (`notify` calls, the needs-you notices) are in
  every trace already.
* The scripted plug answers an array where the reference takes a `tuple`, `set` or `frozenset` (P18, P19: `kinds_of` refuses a
  `list`); `hands::kinds_of` takes any array, which is right for a Rust plug (it has no list/tuple), so the double's Python side hands the
  reference a tuple. S7.2's plug returns a set either way.

### The mutation check (a build with the broken rule behind an environment switch, run, restored; the tree is the committed one)

Each rule broken alone in car-engine, `scripted_paths` of the scenario that holds it: EARLY's claim not carrying `schedule`
(`relaxed_points`: `pl_early_looks_before_reset`, the log 8 lines on the reference, 5 on Rust), an answer outside P17's `takes` taken
(`pl_admit_answer_outside_takes`, a record registered where the reference registers none), P14 told for a move to the state the record
is in (`pl_send_now_passes_retry_wait`, 10 calls against 11), a resend's P3 hold ignored (`pl_resend_gate_hold`, 0 log lines
against 2): all four failed their trace, and the four together with nothing broken were equal (46 steps).

### Checks (2026-11-26; `CARGO_BUILD_JOBS=3`, `. tools/rustflags.sh` not sourced for the dev builds)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked rc=0; cargo deny: advisories, bans, licenses, sources ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0; cargo deny: all four ok
check_groundwork OK (17 standard crates, 3 advanced); check_rebuild.sh rc=0 (identical, no profile path)
run.py -k EngineTraceDiff -k EngineReview6 -k EnginePanicDiff -k EngineInputsDiff -k LaunchGuardHeld -k EnginePlugDiff
  -k ScriptDiff -k RefusalDiff: 23 tests OK (1 expected failure, B1), 1,256 s; corpus 81 / 1,023 steps and walks 60 / 5,153 equal;
  plug: scripted 63 scenarios / 878 steps (52 sends, 1,687 questions), the corpus with a deferring plug 81 / 1,023 (2,022 questions),
  walks with a scripted plug 40 / 3,429 (86 sends, 5,114 questions), all equal
the 15 frozen modules, test_parts --worker on the Python lane and with CODEX_AR_CORE=rust, after the car-engine and car-store change:
  456 test ids, 456 pass on both (Python 567 s, Rust 681 s), 0 differ
```
### The bridge review's fixes (seat bridgefix, branch `car-v0627-bridgefix`, 2026-11-25; REVIEW-bridge.md)

* **B1, D15**: `bridge.rs` `unwound` is the unwind boundary of a request: `serve` answers a panic under a command (or under the
  reading of the line, with a null id) with the generic refusal and reads the next line; `one_shot` answers it with the generic
  refusal's JSON and exit 1, as `dispatch`'s `except Exception` and `_emit` do. The tests (`tests/review_bridge.rs`) panic through a
  test host's policy-key read, not through any product path. car-words' `lock().expect` (`l10n.rs` 152, 290, 296) is not changed
  here (another branch changed `l10n.rs`): the integration must make those process locks survive a poison
  (`unwrap_or_else(PoisonError::into_inner)`), or the first panic caught while one is held makes every later `strings`/`describe`
  panic (and so answer the generic refusal).
* **S1**: an argument given as JSON text is read over the text's code points (`loads_text`: each lone surrogate stands in as a
  private-use character the text holds neither raw nor as an escape, and is turned back in the result), so it parses and answers
  as `json.loads` does. car-machine's `loads` takes a `&str`; a `loads` over a `Str` there would replace the stand-in.
* **S2, the Host seam grew six methods**, one per operation: `file_id` (`st_ino`), `read_file` / `open_file` (Python's share mode,
  `FILE_SHARE_READ | FILE_SHARE_WRITE`, never delete), `create_file` (`mkstemp`'s exclusive create), `replace` (`os.replace`) and
  `rename` (`os.rename`). Every read and write of a file car-control makes goes through them (`seen.rs`, `oncewords.rs`,
  `aside.rs`, `status.rs`, `tools.rs`, `homefind.rs`). `SystemHost`'s `replace` is std-only: a held target answers error 5, a folder
  or junction at the name answers 5, and `rename` answers 183 for any existing name (a dangling junction included), the rule
  car-machine's `pyfile` follows on car-v0627-fix4.
  **Integration 6 must hand car-platform's `files::replace` and `files::rename` (fix4) to `SystemHost`'s `replace` and `rename`**
  (the std-only versions stay for a host without them), and **car-platform needs one function this seat could not add**
  (D3: std has no stable file index, and this seat may not touch car-platform): `files::file_index(path) -> Option<u128>`
  (CreateFileW with FILE_READ_ATTRIBUTES and all shares, GetFileInformationByHandle, `nFileIndexHigh << 32 | nFileIndexLow`,
  as `homelock::folder_identity` reads a folder's). `SystemHost::file_id` answers the file's creation time until then: a new file is
  a new creation time, except that NTFS tunnelling gives a file renamed onto a name just deleted the old file's, which
  `review_bridge.rs` `a_failure_seen_file_replaced_by_another_of_the_same_size_and_time_is_read_again` does, so that one test
  stays red until `file_id` is the file index.
* Notes fixed: the failure-seen stamp now holds the file id; `_observe_only` swallows `ControlError` and `StoreError` only; the
  reply and its newline are one write; the diff harness resets the Interface-language preference for every stream.

## The acting bridge commands (seat S5.1b, branch `car-v0627-bridge6`, 2026-11-26)

PLAN 5.3 row P5 / S5.1, second half: every `controlcli` command S5.1a left out, `control.actions`, `control.codexstart`,
`control.poweraction`'s writers, `control/watcher.py`'s acting half, `ownreport/` and `diagnostics.py`, ported from the
**v0.6.26 final** and held to it by `tests/rustdiff/diffs_bridge_acting.py` (with `actworld.py`). With S5.1a's 23 and these
28, car-control answers all 51 of `PLAIN` and `WITH_ARGUMENT`; `unknown command` is again only for a command the bridge has
none of. Nothing under `src/`, `advanced/`, `gui/`, `build/`, `scripts/` or `docs/` changes; car-engine, car-codex, car-adv,
car-platform and car-words are untouched.

### What is where

| Python | `rust/crates/car-control/src/` |
|---|---|
| `control/actions.py` (every method; `rescan_pending` takes the judge through the Host) | `actions.rs` |
| `control/watcher.py`'s acting half (`start_watcher`, `_launch_watcher`, `await_watcher`, `await_stopped`, `stop_watcher`, `set_startup_enabled`, `start_timeout`) and `startup.watcher_python` | `lifecycle.rs` |
| `control/codexstart.py` (all of it: the decision, the note line, the look after the start) | `codexstart.rs` |
| `control/poweraction.py`'s writers (`power_options`, `arm`, `disarm`, `stop_power_countdown`, `power_batch_end`, `power_batch_finish`, `power_refused`, `power_show`, `_power_change`, `_write`, `_replace`) | `power.rs` (`read_file` stays in `status.rs`, now `read_power_action_at(now)`) |
| `control/tools.py` `show_demo` | `tools.rs` |
| `controlcli.py` `_compatibility`, `_compat_import`, `_compat_refresh`, `detection-check` | `compat.rs` |
| `ownreport/__init__.py`, `reading.py`, `evidence.py`, `document.py` | `ownreport/{mod,reading,evidence,document}.rs` (rusqlite, read-only, query_only, trusted_schema off, a 3 s busy timeout) |
| `diagnostics.py` (`Redactor` and its five patterns matched by hand over code points, `_record`, `_installation`, `_compatibility`, `collect`, `write`) | `diagnostics.rs` |
| `controlcli.dispatch`'s other 28 commands | `commands.rs` `acting` |

Two writers of S5.1a's were fixed on the way (they were unreachable until `once-words` took `text`): `oncewords::put` keeps an
existing entry in its place, and a guard that refuses under the lock leaves the file as it was (`change_or`).

### The seam: `host::Host`, grown

Every new method has a default that refuses (`Raised::refused`, a `NotImplementedError`) or answers nothing, so a host that
answers only the quiet commands (S5.1a's review test host) still builds. What a call raised is `host::Raised` (the Python
class and `str(exc)`); a launch is `host::Launched` (`pid`, `poll`); Rescan's judge is `host::Judge`.

| Host method | Python | `SystemHost` |
|---|---|---|
| `monotonic`, `sleep` | `time.monotonic`, `time.sleep` | real (std) |
| `signal(Event::{Wake,Stop,Demo}, state_dir)` | `WakeEvent/StopEvent/DemoEvent(...).signal()` | real (car-platform `sync`) |
| `startup_read`, `startup_install`, `startup_uninstall`, `protocol_value`, `notification_identity_owner` | `startup.*` | real (car-platform `startup` over `WinRegistry::current_user()`); `startup_value` now reads through `startup_read` |
| `python_launcher` | `startup.python_launcher` | the reference's rule (`pythonw.exe` beside the running program), which the Rust core never meets: **StartupError**, so `start-watcher` and `startup` answer `not_installed` / the sentence. **The integration must hand the Rust watcher's own launch** (what `_launch_watcher` starts: the program and its arguments) |
| `launch(argv, cwd, flags)` | `subprocess.Popen(..., DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP)` | real (car-platform `spawn`, which ORs `CREATE_NO_WINDOW` in); an OSError's text as Python writes it (`[WinError n] ...`) |
| `power_available` | `win/powerdown.available` | real (car-platform `powerdown::available`); nothing here can act - `tests/acting.rs` holds that no source names an acting call |
| `internet`, `process_context`, `process_there` | `win/network.internet`, `windows.process_context`, `windows.process_identity` | real (car-platform) |
| `token_hex`, `token_bytes` | `secrets.*` | **std only** (`host::std_random`: SipHash under std's OS-seeded keys over a counter and the clock). **The integration must hand car-platform a `BCryptGenRandom`** |
| `windows_version`, `system` | `sys.getwindowsversion()`, `diagnostics._system()` | **None, and `python: null`**: car-platform has no version reader (`RtlGetVersion`) yet, and the Rust core runs under no Python. The integration hands a version reader; the owner decides what `python` says |
| `note_turn(&File)` | `codexstart._note_turn` (one byte locked at 2^40) | **no turn**: car-platform has no byte-range lock. A Rust writer appends and never cuts codex-start.log until the integration hands `LockFileEx` in |
| `compat_live_view`, `compat_import`, `compat_refresh` | `compatio.live_view`, `import_document`, `run_refresh` | **refuse** (S3.3's `compat/*`, car-codex): the integration hands them |
| `checkup`, `checkup_for_bundle(home, key)` | `checkup.run`, `checkup.for_bundle(control)(redact)` | **refuse** (car-watcher's `checkup.py`); `detection-check` answers the generic refusal and the bundle `{"error": "NotImplementedError"}` |
| `rescan_judge(home)` | `rescan.judge_for(control)` | **refuses** before anything is read or written (car-watcher's `rescan.py`) |

Still from S5.1a and unchanged: `compat_view` is null, `managed` none, `windows_languages` none, `local_clock` UTC (car-policy's
`classify::clock::Crt` is the product clock to hand in).

Safety, as the brief asks: nothing in a diff starts a process, writes the registry, signals an event or acts on the power - the
world answers every such call, and `SystemHost` is never asked to write in a test. Start and Stop watcher in the diffs ask the
world's mutex answers; the one real mutex a test takes (`tests/acting.rs`) is named from a scratch home, a name no real watcher
holds. The power commands only arm, turn off and read `power-action.json` and ask whether an action is available; the harness
runs with `CAR_NO_POWER_ACTION` set (fix4 S3) and every stream asserts it (`power_guard` in `bridge.run`'s answer). Nothing starts
Codex: `start_for_codex` starts only the watcher's launcher, through the world's stand-in.

Also for the integration: car-policy's `StartRoute` has no `told` (the reference tells a plug's route what core made of it,
`_tell`); `start_for_codex` tells nothing until it has one. `StartRoute::start` takes `&[String]`; car-control hands the one
command line as a single element, as the reference hands one `str`.

### The diffs (`tests/rustdiff/diffs_bridge_acting.py`, reference the v0.6.26 final)

Each stream runs on both sides in fresh copies of one scratch installation at one path (`acts`: the wire goldens' golden
installation with `wiregolden._seed_exhausted`), under one world: bridgeworld's, with actworld's acting answers. The reference
is the tag's `controlcli`, patched by `actworld.HOOK` to the same stand-ins (a `Popen` whose `poll` is the world's list, the
Run key in memory, a stand-in monotonic clock that only a sleep moves, deterministic tokens, `time.mktime` and `strftime` on
the world's UTC clock). Compared, byte for byte: the reply lines and the exit code, every file under the workspace (settings,
power-action.json, once-words.json, the usage checks, codex-start.log, a diagnostics bundle), every row of every table of the
state afterwards (`actworld.state_dump`), and **the Host calls each side made, in order, with their arguments**
(car-harness `acting.rs` writes them down; `actworld.HOOK` does the same). `control.call` (car-harness) and `mode: "call"`
(the hook) run one Control method for what no bridge command reaches.

### The proofs (reference the v0.6.26 final, release harness)

```
python -X utf8 tests/rustdiff/run.py -v --build --reference v0.6.26 -k diffs_bridge_acting     Ran 23 tests in 886 s, OK
  GoldenActsDiff 1     42 streams: every case wiregolden asks of the 29 acting commands (112 golden cases), stand-ins as the world
  WatcherDiff 3        start over 12 worlds (the mutex in turn, a launch that exits or is refused, no launcher, a chosen Python's
                       108 s, the install lock) and two homes; stop over 5; startup over 9 Run-key worlds (StartupError at each step)
  ActionsDiff 6        11 actions x 19 keys of every kind, watcher running and not; 13 thread ids; 33 ways to postpone; Retry now and
                       Rescan under 11 things that stop a usage reading; 5 judges x 2 + no judge; garbage, empty, older and absent states
  PowerDiff 2          12 power-action.json files of every kind x 11 requests; a port that raises, every reason, the key
  RegistryDiff 2       the registry and check stand-ins answering values, raising, not objects; the demo's event; the one-shot form (10)
  OwnReportDiff 4      8 kinds of log (alpha, sub-alpha, Unicode digits, invalid dates, leap seconds, every line break, rotated, 8 MiB+1),
                       10 kinds of state (absent, garbage, newer, older, schema 3, a column gone, paused, odd values, hidden, empty home),
                       7 watcher views x 4 product versions, exactly 500 and 501 records on one version
  DiagnosticsDiff 1    the bundle's bytes over 7 homes and worlds and 2 empty ones; names taken, upper-case, tidied, under a file
  ControlCallDiff 3    start_for_codex over 6 job contexts x the setting x the process alive or gone, 8 refusals, the log cut to 50;
                       launch_ends_with_job; 17 power-writer calls x 5 files; Retry now, Rescan, cancel, cancel-all, clear as 3 actors
  PowerGuardDiff 1     the harness sees CAR_NO_POWER_ACTION (every stream also asserts it)
                       270 streams, 598 requests, 1324 Host calls equal
cargo test -p car-control   tests/acting.rs 5 (no source names an acting power call; the stand-ins refuse; iso's limits; versions; graded)
```

Found by the diffs and fixed here: `codex-start.log` was never cut (std's append mode has no FILE_WRITE_DATA, so `set_len` failed;
now read and write, each write after a seek to the end, as the C runtime's `a+b`); `iso` failed at the wrong second (the C
runtime's `gmtime` on 3.13.15 takes up to 3001-01-19T21:59:59Z, then OSError; OverflowError past `time_t`). Faults of the diffs
themselves: the tag's `quiet.py` binds `time.mktime` as a default argument at import (the hook now rebinds every such default),
the tag's entry script is its own tree's (the hook puts it where car-harness's Paths put it), a state that is not a database
cannot be dumped (its bytes are compared instead).

Mutation checks (a rule broken in car-control, the release harness rebuilt, the named diff run, the source put back; each one
fails it): the watcher's start looked at every 0.2 s, not 0.1 s (`WatcherDiff.test_start`, by the Host calls: the sleeps); a cancel
that changed nothing ending its sentence with a full stop (`GoldenActsDiff`); the power action's warning written as minutes times
61 (`PowerDiff.test_files_of_every_kind`, by power-action.json); a report taking 501 records on one version
(`OwnReportDiff.test_many_records` - MISSED at first, the golden home's own records carried both cases past the bound; the diff now
holds exactly 500 and 501, and it fails); a user name of two letters redacted (`DiagnosticsDiff`, by the bundle's bytes); the look
after a start for Codex waiting 3 s, not 4 s (`ControlCallDiff.test_start_for_codex`, by the calls). The first run of these found
that unittest's difflib took hours over two lists of a thousand calls; a difference is now reported as its first place.

The re-diff (`python -X utf8 tests/rustdiff/rediff_control.py --reference v0.6.26`, all of `-k diffs_bridge`: S5.1a's framing and
quiet commands and this seat's acting ones): `control/watcher.py` the one ported file changed since beta.2; Ran 52 tests in 1672 s,
OK - the goldens' 122 quiet and 112 acting cases, 270 acting streams and 1324 Host calls equal. `cargo test --locked` (both
workspaces), clippy `-D warnings`, fmt, `cargo deny --locked --offline check` and `check_groundwork.py` pass but for the known red.

KNOWN REDS on this base (left red, not this seat's): `review_bridge.rs`
`a_failure_seen_file_replaced_by_another_of_the_same_size_and_time_is_read_again` (needs car-platform's `files::file_index`, a later
integration), and two inherited `diffs_review_bridge` cases (`ReplaceDiff.test_settings_saved_over_a_dangling_junction`,
`FloatTextDiff.test_a_heartbeat_time_that_is_a_power_of_two`), fixed on fix4 and fix5.

### For the next seats

* **S5.2 / car-bin**: every command is in `commands.rs`; `SystemHost` is the host to build, with the hand-ins above.
* **The integration**: the bold rows of the table; `rediff_control.py --reference v0.6.26` runs these diffs too (`-k
  diffs_bridge`), and lists `control/actions.py`, `codexstart.py`, `poweraction.py` and the domain files they read.
* **car-watcher (P6)**: `checkup.run`, `checkup.for_bundle` and `rescan.judge_for` are this crate's `Host::checkup`,
  `checkup_for_bundle` and `rescan_judge`; the watcher's own power-action writers are `Control::power_batch_end`,
  `power_batch_finish`, `power_refused` and `power_show`, and a notice's stop is `stop_power_countdown`.
* **The MCP server (S5.3)**: `start_for_codex(confirm_seconds)` and `launch_ends_with_job()` are here.
## Fix 7: review 7's findings in car-codex and car-adv (branch `car-v0627-fix7`, 2026-11-26)

Cut from `car-v0627-review7` at `233a90ffd` (Integration 5 plus the reviewer's failing tests). Fixed: S1, S2 and notes 3, 4, 5, 6, 8 (two of three), 9 of
`outputs/plans/v0627-rust/REVIEW-int5b.md`; that file's end says per finding what was fixed and what was not, and why.

### The lock shape of advanced.sqlite (S1)

The reference's one connection is guarded by a re-entrant lock held for a whole transaction, and `_open` reads `self._connection` WITHOUT that lock where it is already set,
so core's claim (`ClaimLedger::claim` and `record`, inside core's `BEGIN IMMEDIATE`) attaches the file while another thread's transaction on the advanced connection waits
for the reservation that very claim holds. car-adv keeps the `Mutex<Option<Connection>>` (a Rust `Connection` is not `Sync`; the mutex is what gives each transaction the
connection whole, as the RLock does) and adds `open: AtomicBool`, written under the mutex when the connection is opened and when `close` drops it, read without it by
`attach`. `attach` never touches the advanced connection once it is open - it reads `PRAGMA database_list` of core's connection and attaches there - so the flag is all the
unlocked read needs. Thread safety is unchanged: every use of the advanced connection itself still holds the mutex. `begin` also rolls back on a panic (a drop guard, as
car-store's has; D15), and a ROLLBACK that fails goes out as SQLite's own error (the reference raises the raw `sqlite3.Error` from its `except`).

### One bound for a child's output and its exit (S2)

`transport::Output` reads a child's stdout on a thread of its own and `transport::communicate(child, output, until)` is `Popen.communicate(timeout=)` on Windows: the reader
joined with the time, then the exit waited for with what is left of it. `run_to_end` is `subprocess.run(timeout=)`: on the time's end the child is killed and the pipe read to
its end (Windows' `run` calls `communicate()` after `kill()`), and the answer is the timeout. Used by `codex --version` (10 s), `codex queue --help` (20 s), the send (45 s;
then kill, 5 s more, `queue_timeout`) and `compat::evaluator::SystemRunner` (the refresh's PowerShell). Every way out reads the pipe to its end - an `Output` that is dropped
finishes itself - so no reader thread and no child is left behind; like the reference, a process the engine started that holds the pipe holds the caller as long as it lives.
The App Server helper's `close` does the same at its end: after its 1 s join it marks the helper's stdout closed (`appserver::Closable`), the read in progress ends as it would,
the next one fails, and the reader is joined (the reference's `process.stdout.close()` waits for the read in progress).

### For the hosts of `Arming` (S7.3's surfaces, the watcher, P4)

* `state/port.rs` raises an exception the state does not wrap (a `TypeError` of the wire) as a panic carrying `port::Raised {class, message}`. Every entry point that calls
  `Arming` - each surface's command, the watcher's tick, the MCP tool - calls it inside `std::panic::catch_unwind` and reads the payload with `state::port::raised(&*payload)`:
  `Some(raised)` is the reference's exception of that class (answer it as that entry point answers that exception: the bridge's generic refusal, the tick's caught error),
  `None` a panic of the port's own (D15's generic answer). The panics come after the state's call returned, outside any transaction. Hosts today: the `advprobe` example
  (both its boundaries now answer the class, as the reference's runner does).
* The compatibility evaluator keys a backend engine by `Backend::object_id()` (`id(backend)`), a number each Backend takes at `new()` and keeps wherever it moves; a Backend
  does not need pinning any more. A Backend made anew is a new key (a recompute), as a new Python object is unless it reuses a freed one's id.

### Left (not this seat's)

* S3 (`std::fs::rename` in `compat/files.rs`, `layout.rs`, car-adv `images.rs`, `state/seam/accounts.rs`): car-platform's `files::replace` (fix4), at the integration;
  `review7_replace` stays red until then.
* A prompt's lone surrogate in `transport::send`: car-platform's `Spawn` takes UTF-8 arguments only, so it goes out as three U+FFFD (and counts three units); a wide
  argument in `Spawn` is car-platform's.
* N1 and N2 (the v0.6.26 final's fresh-home probe and package engines): the seat that brings the port to the final.

### Checks

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; cargo deny --locked check: all four ok
                    test --locked --no-fail-fast: every target passes but review7_replace (S3, red on purpose); review7_send_receipt ok, fix7_engine_checks ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0 (car-adv 5 + review7_attach 1); cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh            rc=0, every binary the same with and without advanced/; profile-path scan: none
python -X utf8 tests/rustdiff/run.py --build -k diffs_codex -k diffs_adv    Ran 76 tests in 5,575 s, OK (reference v0.6.26-beta.2)
```

Revert proofs, each its diff reverse-applied, the test run, the diff re-applied: `attach` through the mutex (review7_attach: 10.8 s), `begin` without the guard
(`a_panic_in_a_body_rolls_back`), the helper's close without `Closable` (fix7_engine_checks: 2.1 s); S2's own red at the base is the reviewer's (accepted in 76.4 s).
## car-surface (seat S6.0, branch `car-v0627-surface`, 2026-11-25)

The pure halves of the tray, the popup, the notice card and the notifications (PLAN 1.2 row 13, 1.5 "the surface port"),
ported from the **v0.6.26 final tag** (D17; `ui/popup/model.py` changed after beta.2 and the final added
`domain/usage.newest`), on car-v0627-fix5 at `64b8fee59`.

| Python (v0.6.26) | car-surface | what |
|---|---|---|
| `codex_link.py` | `codex_link` | the Codex app's link and the chat's, read and written; `open_in_codex` through the `Launch` seam |
| `notice_uris.py` | `notice_uris` + `pyurl` | the four readers and three writers; `urllib.parse.urlsplit`/`parse_qs` as CPython 3.13 has them (the C0 strip, tab and line-break removal, the scheme's characters, brackets and IPv6/IPvFuture hosts, the NFKC check of a non-ASCII authority by a table read from the interpreter, `%XX` decoded per ASCII run with U+FFFD) |
| `notice_inbox.py` | `notice_inbox` | `Inbox<T>`: the same limit, wake outside the lock, a wake that panics is a wake that failed (D15) |
| `notice_presence.py` | `notice_presence` | `card_allowed` and every number of the probes; the probes themselves are the `Presence` seam |
| `notify.py` | `notify` + `speech` | every `*_content`, the sentences, `_toast_xml`, `SCRIPT`, `show`/`show_content`; `str.format` of the three catalog keys that use it |
| `notifier.py` | `notifier` | `Notice`, `build` (every kind), the demo, the cancel's and power stop's notices, Open Codex, clicks, `deliver`, `complete`, `show_demo`, `told`, `activate` |
| `notice_card.py` | `notice_card` | `view`, `texts`, `layout` (+ `mirror`), the curves and `CardMotion`, the stack, `float_shadows`/`shadow_at`/`shadow_margin`, `corner_coverage` (circle and squircle), `premultiply` |
| `ui/popup/model.py` | `popup::model` | every function and `PopupModel`; with the pure part of `ui/popup/words.py` (`say`, `one_line`, `locale_of`, `kept`, `vocabulary`) and `placement.py` (`taskbar_edge`, `place`) they and the card read (`popup::words`, `popup::placement`) |
| `ui/tray/model.py`, `ui/tray/stored.py` | `tray::model`, `tray::stored` | `popup_attention`, `snapshot_from`; `StoredMixin` as `Stored` |
| (helpers) | `py` | `str()`/`repr()` of a list or a dict, `list()`, `dict()`, `in`, unpacking, unbounded `int()`, `sorted` with a fallible `<` |

Not ported here (crate-map: C# host): `notice_window.py`, `ui/card/*`, the popup's window, renderer, motion, theme and
accessibility, `ui/popup/words.unbroken`, `layout.layout`/`share_columns`, the tray's icon, menu, tip and motion.

### The seams (`car-surface/src/seam.rs`, `usage.rs`)

| Seam | Implemented by | Stands for |
|---|---|---|
| **`CardHost`** (`wake`, `measure`) | **the C# watcher host** (D1, S6.2/S6.3) | `notice_window.Card`'s host: the one message that makes the icon's thread call `Inbox::take`, and the renderer's `measure(role, text, width, wrap)` that `notice_card::layout` lays the card out with. The card's window, its paint, its stack's windows and their motion clock are the host's; it asks `CardMotion` for each frame and `stack_positions` for each place |
| **`Presence`** (`snapshot(aumid)`, `battery_saver`, `message_duration_ms`) | car-platform (D3) | `notice_presence`'s probes: `SHQueryUserNotificationState`, WinRT `NotificationMode` and `ToastNotifier.Setting` by vtable slot (the IIDs and slots are in `notice_presence`), `SPI_GETSCREENREADER`, `SM_REMOTESESSION`, the input desktop's name, `GetSystemPowerStatus`, `SPI_GETMESSAGEDURATION`; each answer a closed value or `Null` |
| `PowerShell` (`available`, `run`) | done: `SystemPowerShell` over car-platform's `pwsh::run` and a `Starter` | the toast's constant script, `-Command` plain text (issue #65), its values as `CODEX_AUTO_RESUME_ARG_*` variables, `CREATE_NO_WINDOW`, 20 s |
| `Launch` (`is_file`, `start`) | done: `SystemLaunch` over car-platform's `SystemStarter` | explorer.exe for `open_in_codex` |
| `CardControl`, `PopupControl` | car-control's `Control` (S5.1) | the card's buttons (`cancel_interruption`, `stop_power_countdown`, actor `toast`) and the popup's `CONTROL_CALLS`, in process |
| `TrayStore` | car-store's `Store` (via car-watcher) | `snapshot_from`'s four reads |
| `StoredSettings`, `TraySurface` | car-watcher (the control layer's `get_settings`/`settings_path`, `os.stat`) and the C# host (adopting the theme and Reduce motion, the strings, the log) | `StoredMixin` |
| `usage::{newest, meter_windows}` | car-machine `domain::usage` (the integration moves the two functions there unchanged and deletes `usage.rs`) | the v0.6.26 final's `domain/usage.newest`, which car-machine's beta.2 port lacks |

`Speech { locale, clock }` hands in what the reference reads from process globals: `l10n.current()` (car-words'
`resolve` with the platform's languages) and `time.localtime` (car-policy's `LocalClock`, `Crt` in the product).

### The diffs (`tests/rustdiff/diffs_surface_*.py`, `surface.py`; car-harness `src/surface.rs`, `surface.batch`)

Eighteen diffs in five modules, every one run by the reference interpreter (the v0.6.26 tag through
`tests/released.py`) and by car-harness on the same cases, answers compared as the JSON they are, byte for byte. The
stand-ins are written once in `surface.py`'s `SURFACE` and once in car-harness `surface.rs`: nothing is started, raised
or shown (PowerShell's argv, argument variables, flags, streams and timeout recorded; explorer.exe's argv and flags
recorded; the presence answers and the card host's wakes the case's).

| Module | Diffs | Cases (all equal to v0.6.26) |
|---|---|---|
| `diffs_surface_uris.py` | UriDiff, LinkDiff, PresenceDiff, InboxDiff | 2,552 `urlsplit`, 1,330 `parse_qs`, 12,883 reader/writer cases; the NFKC table (19 code points) is the interpreter's; 100 link and `open_in_codex` cases; 1,441 presence; 303 inbox scripts (4,500 steps) |
| `diffs_surface_notify.py` | ContentDiff, ToastDiff | 15,796 contents and sentences in all 22 languages (1,012 raise, alike); 1,514 XML documents; 340 `show`/`show_content` with 274 PowerShell requests recorded (`-Command` and the script whole, `XML`/`AUMID`/`SILENT`, `CREATE_NO_WINDOW`, NUL streams, 20 s) |
| `diffs_surface_notifier.py` | BuildDiff, RouteDiff, ActivateDiff | 1,910 builds (every kind, 22 languages, each destination and kept kind), 216 Open Codex, 696 click/page/actions/status; 546 `deliver`, 36 `complete`, 72 `show_demo`, 240 `told`; 198 `activate` (word, log lines, announced notices, calls) |
| `diffs_surface_card.py` | ViewDiff, MotionDiff, StackDiff, ShadowDiff | 242 views, 242 texts, 3,244 layouts (5 scales, Arabic/Hebrew/Persian mirrored, the five special days, 0-5 buttons); 147 curve cases and 400 `CardMotion` lives (17,538 steps); 1,920 placement/stack cases; 124 shadow/corner/premultiply |
| `diffs_surface_popup.py` | WordsDiff, HeaderDiff, ViewDiff, ModelDiff, TrayDiff | 332 word cases; 7,048 header cases; 645 `view_model`, 643 `task_item`, 528 `row_menu` in 22 languages over the picture inputs' rows (build/make_screenshots.py `popup_rows`/`popup_status`, rebuilt) and generated ones, 32 `newest`; 523 `PopupModel` scripts (6,909 steps), 850 `perform`, 36 `select_action`, 19 `busy_key`; 509 `snapshot_from`, 400 `StoredMixin` scripts |

`python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 -k diffs_surface -v`: Ran 18, OK. The left/used rule
(glance surfaces say LEFT) is held by the near-limit toast's share (`notify.near`) and the popup's usage line.

**Mutation check** (each rule broken alone, the harness rebuilt, its diff run, the file restored; every one FAILED):
M1 `card_allowed` takes a float 5.0 (PresenceDiff), M2 `quoteattr` always writes double quotes (ToastDiff), M3 a
resumed notice wears the waiting light (BuildDiff), M4 the header ignores a row held for a person (HeaderDiff), M5 the
card's fade ends at 40% of the entrance (MotionDiff), M6 `parse_qs` keeps blank values always (UriDiff), M7 the icon
counts an unmatched record of a switched-off conversation (TrayDiff), M8 the usage meter's toast says the share USED
(ContentDiff).

The reference found one aliasing of its own: `PopupModel.rows` changes in place, so a recorded state is deep-copied
(`diffs_surface_popup.state`); Rust's answers are copies already.

### The re-diff

`python -X utf8 tests/rustdiff/rediff_surface.py --reference v0.6.26` (or a later tag of the archived repository): the
ported and the read files that changed from v0.6.26, then every `diffs_surface_*` with the tag as the reference.
run.py's default reference (beta.2) cannot run these diffs: `newest` and the final's model are not in it.

### For the next seats

* **S6.2/S6.3 (the C# host and the surfaces):** implement `CardHost` (post one message, then `Inbox::take` on the icon's
  thread; measure with the renderer) and draw `notice_card::layout`'s items, `popup::model::view_model`'s values and
  `PopupModel::menu_for`'s menus; the popup's clicks go through `PopupModel::action_for`/`begin`/`apply_outcome`
  and `perform` on a worker thread. A card's button is `notifier::activate`; its end is `notifier::complete`.
  `layout`'s measure returns ints (GDI's); the stand-in's numbers are not the renderer's.
* **car-platform:** implement `Presence` (the probes listed above; every failure is `Null`, never a guess).
* **car-control / car-watcher:** implement `CardControl`, `PopupControl`, `TrayStore`, `StoredSettings`; the watcher
  builds with `notifier::build`, routes with `notifier::deliver` (its `show` is `notify::show_content` over
  `SystemPowerShell::system()`), and answers the icon with `tray::model::snapshot_from` and
  `popup::model::snapshot_activity`.
* **Integration:** move `usage.rs` into car-machine; `check_groundwork.py` EXPECTED has car-harness -> car-surface.

### The review8 fixes (seat fix8, branch `car-v0627-fix8`, 2026-11-26)

* **A seam's panic is the exception the reference catches (D15, REVIEW-surface S2).** `seam::caught(body)` is
  `try: ... except Exception` for a panic as well as an `Err`: a panic answers as `Raised` (the payload's own, else
  the class a `"ClassName: ..."` text names, else `Exception`). It wraps `popup::model::perform`'s whole body, every
  seam call of `notifier::activate`/`power_stop` (the control, `open_link`, `open_chat`, `open_dashboard`,
  `announce`, `log`), `deliver`/`show_demo`'s probe and `told`'s store. **The integration seat should share one
  helper:** this one, car-engine's `caught.rs` over car-scheduler's `caught` (which answers `Err("Exception")`, a
  `&'static str`) and car-adv's `port::Raised` are three spellings of the same rule; one function in car-machine
  taking a body that returns the crate's own error type would serve all three.
* **A corner of a radius that is no number** raises ValueError (NaN) or OverflowError (infinity, 2**63 and past) as
  `int(math.ceil(radius))` and `bytearray(size)` do; a size past 2**15 cells answers MemoryError (no card has one:
  the radius is `brand.RADII["card"]` times the scale) instead of allocating.
* **The icon's snapshot** asks `disabled_threads()` before it hashes a row's id (REVIEW-surface N1).
* `rediff_surface.py` also reads `domain/vocabulary.py`, `domain/plug.py`, `domain/gates.py` and `ownvalues.py`.
* Tests with no diff: `tests/fix8_probe_panics.rs`, `tests/fix8_uncovered.rs` (`seam::launch_error`, the presence
  snapshot, `CardMotion::slide`, `notify::shown`).
* Still open, not this seat's: S1 (the Unicode 16 tables of car-machine, car-words, car-policy); `ShippedInterpreterDiff`
  stays red on its six digit cases until they are regenerated.
## The installer, the migration and the way back (seat S8.2, branch `car-v0627-package2`, 2026-11-25)

PLAN 6.1-6.10 on the stub core, with the v0.6.26 final's tag as the reference (D17). What is built:

* **`build/rust_install/install.ps1`** (shipped as the archive's `install/install.ps1`; `rust_release.INSTALLER` replaces S8.1's
  placeholder): v0.6.26's installer, function by function (`test_rust_install.InstallerShapeTests` holds the list), with
  `app\bin\codex-auto-resume.exe` where v0.6.26 ran `runtime\python.exe app\scripts\plugin_setup.py` - `claim-home` and
  `verify-home` from the payload's core, every other command from the installed one (`Invoke-Setup`), the Store engine's
  signature asked as `engine-trusted <path>` (0 only for `official_engine == (True, 'openai_signature')`). Removed: the
  precompile and the chosen-Python line (nothing compiles). Kept byte for byte: the outside gate, the lock, the journal,
  the rollback, the Dashboard close/reopen, the edition rule (14), repair/update wording, uninstall keeping data, purge.
  `runtime\python.exe`/`pythonw.exe` (car-legacy) and `app\scripts\plugin_setup.py` (stub) are required in the payload
  and stay in the home. The line `[ok] Bundled Python ...` keeps its start for the setup window's milestone (S6.2 renames it).
* **The migration from a Python version** (`$fromPython`: no core, and `app\src\codex_auto_resume\__init__.py` there):
  `Get-OwnedWatcherProcess` also finds `app\bin\CodexAutoResume.exe` of this home by its image; the version being
  replaced stops its own watcher (`Invoke-InstalledEngine`: its core, or its own `runtime\python.exe plugin_setup.py stop`),
  so the Rust host takes the same mutex only once the Python one let go (6.2). State and settings are never touched (D13).
  The Python trees, the window, its icon and the kept uninstaller stay aside (`.old-<stamp>`, `.migrating`, the journal)
  until the new `setup --keep-state` has run (`Complete-Migration`, 6.5), and the advanced edition's `runtimes\` goes then
  (D8). Where that setup does not complete, `Undo-Migration` asks the new core to stop, puts every tree and file back and
  starts the Python watcher again through the Python engine: a failed migration leaves exactly what was there.
* **Registrations (6.4), as the real core must write them:** the Run value `"<home>\app\bin\CodexAutoResume.exe" "--home"
  "<home>" "run"` (every word quoted, as `startup.quote_argument` writes) and the link handler
  `"<home>\app\bin\codex-auto-resume.exe" "--home" "<home>" "activate" "%1"`. **The `--home` is required**: v0.6.26's
  `setup --keep-state` re-registers the start at sign-in only where `startup.belongs_to` knows the value, and without
  `--home` it does not (`RunValueContractTests`, against the tag's own function) - going back would leave the sign-in start
  on a host that is gone.
* **The way back (6.10):** `scripts/bootstrap.ps1` `Stop-WatcherBeforeOlder`, in the pick path before the older installer
  runs: over a Rust installation and an archive with no core (a Python one) it asks the installed core `stop`, then
  `watcher-running` until non-zero (60 s; `pick: refused watcher-running` otherwise, nothing ended by force). It calls the
  core directly: car-legacy refuses `-X disable-remote-debug plugin_setup.py stop`, a line no earlier version used (found by
  the proof; the table is not widened). v0.6.26's own installer then lays its Python runtime over car-legacy and its app over
  the Rust one, and its `setup --keep-state --watcher-was-stopped` starts the Python watcher because the Rust Run value is
  its installation's.
* **`codex-auto-resume-setup.exe`** (car-bin `setup_main`, BRIDGE.md 4): `-Handover update|another|install -Edition E
  [-SkipStartup] [-AllowEditionChange] [-DeleteSavedAccounts] [-Silent]`, names and values case-insensitive; another edition
  14, no `-Handover` or an unknown word 2 (nothing run: the Welcome window is P6's); it runs `<archive>\install\install.ps1
  -Silent [switches]` in Windows PowerShell by the system folder through car-platform's starter (`CREATE_NO_WINDOW`), keeps
  both streams in `%TEMP%\CodexAutoResume-Setup.log`, waits, ends with the installer's code and after a 0 opens
  `<home>\CodexAutoResumeSettings.exe` (without `CODEX_AUTO_RESUME_UPDATING_DASHBOARD`). The install lock is install.ps1's:
  a mutex cannot be handed to a child, and a setup that held it would make its own installer refuse. car-bin now reaches
  car-platform (check_groundwork's graph has the edge).
* **The test double (`tests/install_double.py`)**: the stub core forwards every command to `CODEX_AUTO_RESUME_TEST_CORE`
  (+ `_SCRIPT`), setting `CODEX_AUTO_RESUME_TEST_CORE_EXE`; nothing else changed in the stub (3 and a stderr line otherwise).
  The double answers plugin_setup.py's codes and lines (`setup` 0/2/4/5, `watcher-running` 0 or 2 as v0.6.26's does, `stop`,
  `doctor`, `uninstall [--purge]`, `remove-entry`, `downgrade-state ... --stop-watcher`, `desktop-shortcut`, `claim-home` and
  `verify-home` by the tag's `config.Paths`), stands in for v0.6.26's engine (`--role engine`) and for both watchers
  (`--role watch`), refuses any home outside the scratch, writes a JSON registry, and names its mutex and stop event
  `Local\car-double-<id>-...`.
* **make_setup and (h), decided:** the one-file Setup exe around a Rust archive is `build/make_setup.py`'s C# program,
  unchanged (it carries the archive and runs its Install.cmd, so the same install.ps1): `rust_release.py --setup` builds it;
  `rust_edition_audit.py` reads (h) with `edition_audit.check_setups` where both are in the dist folder (`--setups` makes them
  required; `--rebuild` builds the standard one again around (e)'s archive). `rust_legacy_bootstraps.py --ref v0.6.26`: a ref
  whose commit a listed tag has is asked once, under the tag. The release check is `.github/workflows/rust.yml`'s `package` job.

### The proofs (`tests/test_rust_install.py`; cargo release build of both workspaces; Windows PowerShell 5.1 under Set-StrictMode 2.0)

Scratch homes only (profile, LOCALAPPDATA, APPDATA, TEMP, CODEX_HOME in a temporary folder; the JSON registry; the install
lock renamed; the outside gate, Codex and the two registry functions stood in; real car-legacy, stub core and setup program;
a real Python copied in as v0.6.26's runtime and as P6's host stand-in). Each edition: v0.6.26 installed by its own
installer -> the Rust installer (update: the Python watcher stopped by its engine, the host started, Run/protocol on the
Rust programs, config/logs/accounts byte-identical, the runtime only car-legacy, no `.old-`/`.migrating`/journal, D8's
`runtimes\` gone) -> again (Repaired) -> the bootstrap's 6.10 step and v0.6.26's installer (the Python watcher running,
the Run value Python's again, nothing of the person's lost). Also: a migration whose setup fails puts v0.6.26 back with its
watcher; another edition is refused with 14; the setup program installs what it is handed (14 and 2 before it runs
anything); a fresh install, uninstall keeping data, reinstall picking it up, purge. Re-diff:
`python -X utf8 tests/rustdiff/rediff_package.py --reference v0.6.26`.

### What waits for the real core and host

* **P5 (core):** the commands and lines the double answers, with the registrations above; `engine-trusted`; `stop` and
  `uninstall` waiting for the watcher as plugin_setup.py does; the MCP server ending on EOF (an uninstall kills the launchers
  only); `claim-home`/`verify-home` printing the canonical root on the second/last line; `desktop-shortcut` 0/3.
* **P6 (host):** `app\bin\CodexAutoResume.exe` (add it to `rust_release.EDITION_BINARIES`; the tests copy a Python in its
  place), taking the watcher mutex and stop event of `win/sync.py`; the setup program's window (BRIDGE 4 "show its own
  window", the Welcome question without -Handover); the setup window's `[ok] Bundled Python` milestone; and a host that
  stops when a v0.6.26 installer run by hand (not through our bootstrap) moves app\ aside under it, which v0.6.26 cannot see
  (written out as a contract in the fix9 section below).

## Integration 7 (branch `car-v0627-rust`, 2026-11-26)

Six branches merged with `git merge --no-ff`, in this order, then the seams the merged code allows wired, each its own commit.

| Merge | Branch | What came in |
|---|---|---|
| `749059124` | car-v0627-plugtrace `73906007e` | S4.2's scenario proxy (`engineproxy.py`, car-harness `proxy.rs`), S4.3's plug traces (`diffs_engine_plug.py`, `plugscript.rs`), review 6's engine fixes (`caught.rs`, the watch budget, `Options` as given, the launch inside the guard), car-store's claim `plugged`/`carried` branches |
| `36ea19384` | car-v0627-bridge6 `acea87eb0` | S5.1a's review fixes (bridgefix) and S5.1b: all 51 bridge commands, the Host's file calls, `diffs_bridge_acting.py`, `actworld.py`, `diffs_review_bridge.py` |
| `bcd236243` | car-v0627-fix7 `63dfc6375` | review 7: advanced.sqlite's lock shape (`open: AtomicBool`, `begin`'s rollback guard), `transport::Output`/`communicate`/`run_to_end`, `Backend::object_id` |
| `678d51bdb` | car-v0627-fix8 `1078717d2` | S6.0 car-surface, its review fixes, `seam::caught`, `diffs_surface_*.py`, `rediff_surface.py` |
| `99dc6a2da` | car-v0627-refpy `9700898df` | `run.py --reference-python` (the reference on the bundled 3.14.10), `refpython.py`, `reftwin.py` |
| `fae915a9b` | car-v0627-package2 `461ef7b76` | S8.2: car-bin's install, migration and downgrade, `install_double.py`, `test_rust_install.py`, `rediff_package.py` |

Conflicts, each resolved by keeping both sides:

* `rust/GROUNDWORK.md`, `tests/rustdiff/README.md` (every seat appended a section; all kept, in merge order). fix8's README was CRLF
  with a NUL byte again (git took it for binary): HEAD's LF text with fix8's car-surface section appended.
* car-harness `lib.rs` (`proxy`, `registry`, `acting`, `appserver`, `surface`), `Cargo.toml`, `main.rs` (`codexapp.script`, `engine.*`,
  `surface.batch` arms) and check_groundwork's car-harness edge list: the union.
* car-control (`aside.rs`, `homefind.rs`, `oncewords.rs`, `seen.rs`, `status.rs`, `tools.rs`, `host.rs`), merge 2: Integration 6 called
  car-platform's `files::replace`/`rename` and car-machine's `pyfile` directly; bridgefix routes every file call through the Host
  (`read_file`, `open_file`, `create_file`, `replace`, `rename`, `file_id`). The Host's calls are kept, and `SystemHost` answers them
  with Integration 6's: `pyfile::read`/`open`/`options` and car-platform `files::replace`/`rename` (bridgefix's std-only
  `held_or_folder` and `python_options` are gone; a test host may still answer its own). `startup_value` reads through `startup_read`.
  The review test host (`tests/review_bridge.rs`) answers `local_clock` (UTC), which Integration 6 made required.
* car-codex `transport.rs`, merge 3: Integration 6's split `send` (`send_preflight`, `send_start`, `receipt`, `send_within`) is kept;
  `receipt` reads the child with fix7's `Output` and `communicate` (one bound for the output and the exit), so both sends do.
* car-surface and car-harness `surface.rs` (merge 4) named `car_policy::classify::clock::Crt`; it is car-platform's `localclock::Crt`
  since Integration 6.

### The seams, wired (each its own commit)

| Seam | Now |
|---|---|
| car-control `SystemHost::file_id` (the creation time) | car-platform `files::file_index` (`d290e8033`): `os.stat(path).st_ino`, read as `homelock::folder_identity` reads a folder's (CreateFileW for FILE_READ_ATTRIBUTES with every share, GetFileInformationByHandle, `nFileIndexHigh << 32 \| nFileIndexLow`). `review_bridge.rs`'s file-index test (a failure-seen file replaced by another of the same size and time) is green |
| car-control `SystemHost::replace`/`rename`/`read_file`/`open_file`/`create_file` (bridgefix's std-only rules) | car-platform `files::replace`/`rename`, car-machine `pyfile` (in merge 2, so Integration 6's wiring is never undone) |
| the four `std::fs::rename` writers review 7 found | car-codex `compat/files.rs` and `layout.rs` were car-platform's `files::replace` since Integration 6; car-adv `images.rs` and `state/seam/accounts.rs` now too (`162d6a7ad`), the account's temporary opened as Python's `"xb"` shares (`pyfile::options`). `review7_replace` is green |
| car-words `l10n.rs`'s `lock().expect` (the catalog cache, the preference) | `unwrap_or_else(PoisonError::into_inner)` (`ec48508f0`), and the same for car-config `codex.rs`'s reported set and car-adv `statement.rs`'s catalog cache, the only other process locks that panicked on poison; a unit test poisons both l10n locks and reads the words again |
| three panic catchers (car-scheduler's `caught` under car-engine's `caught.rs`, car-surface's `seam::caught`, car-adv's `port::Raised`) | one, car-machine `caught` (`61b92acb7`), the lowest crate all of them may name: `catch`, `caught(body, as_error)`, `Raised {class, message}` + `raised`, `class_of` (a `Raised`'s class, a `ClassName: ...` text's, else `Exception`). Each boundary keeps its answer: car-scheduler `Err("Exception")`, car-engine's attributes `Null`/`Some(Err("Exception"))`, car-surface its own `Raised` (with its `code`) first and `class_of` for any other payload, car-adv's `port::{Raised, raised}` re-exported, so the probes answer as before |
| car-surface `usage.rs` (the final's `domain/usage.newest`, `meter_windows`) | car-machine `domain/usage.rs` (`36686d496`), unchanged, with the small Python helpers it read as private functions; car-surface re-exports `car_machine::domain::usage`, so the popup and the harness name it as before |
| car-engine's Backend inside the launch guard | checked, nothing to change: car-engine `transport::Transport::send` is car-codex's `send_within`, its scope the guard's `enter` body (the process starts inside it); the harness's `AskBackend::send` (S4.3's traces) asks the stand-in from inside `enter`'s body; the scenario proxy (S4.2) hands the Python backend `SubmissionGuard::key()` and it enters the test store's own `submission_guard(key)`, as before |

### Checks (`CARGO_BUILD_JOBS=4`; reference v0.6.26-beta.2 on the system Python 3.13.15, rustc 1.100.0; HEAD `4ad7f6569`)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0 (review_bridge 7 of 7
                   with the file index, review7_replace, the l10n poison test, car-machine caught 2); cargo deny --locked check: all four ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0 (car-adv 5 + review7_attach 1); cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0, every binary the same with and without advanced/; profile-path scan: none
python -X utf8 tests/rustdiff/run.py --build --reference-python system -v
                                                     Ran 286 tests in 4,265 s: 277 OK, 1 expected failure (diffs_review6's fresh-home
                                                     test, N1: the final's, not beta.2's), 8 FAIL, no skip. FAIL: ShippedInterpreterDiff
                                                     .test_edges_shipped (6 of 1,437 cases: the bundled 3.14's Unicode 16 digits, REVIEW-surface
                                                     S1, the unicode16 seat's, known); and 7 that start an old tag's store or settings
                                                     (diffs_store Legacy/Migration x2/OpenState, diffs_store_values Blob/NoSettings,
                                                     diffs_settings_files): ModuleNotFoundError codex_auto_resume in the tag's process.
                                                     Alone (`-k diffs_store -k diffs_settings_files`, same reference): Ran 22 in 158 s, OK.
the 15 frozen modules (test_parts --worker, Python lane, then CODEX_AR_CORE=rust; the Engine is rustdiff_engineproxy's)
                                                     456 test ids, 456 pass on both, 0 differ (Python 186 s, Rust 195 s)
Python guards (standard lane, wait_quiet.sh): test_repo_hygiene test_privacy_claims test_privacy_bare_hosts test_edition_audit
  test_srcscan test_stack test_layers test_structural_invariants test_rust_release test_rust_power_guard test_rust_install
  test_rustdiff_reference_python                     Ran 164 in 1,101 s, OK (skipped=7)
```

The 7 old-tag reds are not explained yet: they pass alone and after `diffs_bridge_commands` (which extracts v0.6.10 and v0.6.13 first;
`-k diffs_bridge_commands -k diffs_settings_files -k diffs_store`: Ran 47 in 352 s, OK). In the full run v0.6.10/v0.6.13 were
extracted by `diffs_bridge_commands` about an hour before `diffs_settings_files`, and the tag's process then found no
`codex_auto_resume` on its path: the shape of `released.package`'s `%TEMP%\released-<tag>-*` folder gone while its cache entry stays
(a sweep of %TEMP% by another run on this PC, or a family between them that removes it). The next full run should say which:
`released.package` could check that the folder is still there before answering its cache.

### For the next seats

* **Integration 8** (fix9, mcp, unicode16, adv72c, adv73c): the merges above changed car-control's file calls (the Host's), car-codex's
  `receipt`, car-machine (`caught`, `domain::usage`'s `newest`/`meter_windows`) and car-platform (`files::file_index`); a branch cut before
  them that edits those places conflicts there. unicode16's S1 turns `ShippedInterpreterDiff` green.
* **Any new D15 boundary**: car-machine `caught` (`catch`, `caught`, `class_of`, `Raised`/`raised`), not a new `catch_unwind`.
* **S6.1 (car-watcher)**: unchanged from Integration 6's notes; car-surface's popup reads `car_machine::domain::usage::newest`.

## Review 9's fixes: the installer, the migration and the way back (seat fix9, branch `car-v0627-fix9`, 2026-11-26)

What `outputs/plans/v0627-rust/REVIEW-install.md` found in S8.2, each fixed in its own commit and proved by the reviewer's
test (`tests/test_review9_install.py`, seven) or one of `tests/test_rust_install.py`.

* **Undo-Migration (B1, B2)** waits for the Rust host to end - no process of it (Get-OwnedWatcherProcess) and its mutex let
  go (the core's `watcher-running` not 0), the hand-over's 60 s - before it moves anything (`Wait-WatcherEnded`). Where the
  host does not end, nothing is put back: the Rust version is whole, so the migration is finished (`Complete-Migration`) and
  the last word says setup did not complete and the version stays (`kept-new`). Otherwise the trees change places by renames
  alone, all or nothing (new trees to `<tree>.old-<stamp>-new`, the Python ones back; a rename that fails turns every one
  back, `partial`), so no half-deleted tree is left. Then the Python version's own `setup --keep-state` runs **always**
  (with `--watcher-was-stopped` where no watcher ran and the version takes it: the v0.6.16 final on,
  `Test-KnowsWatcherWasStopped`), which writes the Run value, the link handler and the entry back onto the Python programs;
  what the migration added where the Python version had nothing (the kept uninstaller of a version before v0.6.17, and the
  entry naming it) goes. The last word is what was done: `restored` (the old line), `unregistered`, `kept-new`, `partial`.
* **Every exit after a migration's copy** goes through Undo or Complete (note 2): `$script:PendingMigration` is set after the
  copy, and the `finally` puts the Python version back while it is still set (a core missing after the copy, a throw).
* **Leftovers (note 1)**: `Resolve-MigratingCopies` puts the `.migrating` copies back beside a Python installation and
  removes them beside a Rust one; the trees an interrupted run's journal claimed go once this run's setup has run.
* **Repair without a core (S4)**: `Invoke-InstalledEngine` asks the archive's core (`Invoke-Setup -Program $PayloadCore`)
  where the installation has `app\bin` and no Python package but no core; the core run from the payload acts on the home
  the run installs into, as `claim-home` does. No route through car-legacy exists (it hands every line to the core that is
  missing), so the bootstrap's `Stop-WatcherBeforeOlder` answers `no-core` where the host runs (by its image under
  `app\bin`), and the pick or install is refused (`pick: refused watcher-running`, a reason the Dashboard knows).
* **The way back (S1, S2)**: the 6.10 step runs on every bootstrap route whose archive has no core (also `-ArchivePath ...
  -Force`), answers `not-running` where no watcher ran, and after the older installer `Start-WatcherAfterOlder` asks the
  now-installed version `watcher-running` and, where it does not run, its own `setup --keep-state` (Start-CurrentWatcher
  without -WasStopped): a watcher that ran before going back runs after it, whatever the start at sign-in. A failed pick
  whose put-back restored the old version is left to Restore-AfterFailedPick.
* **The test double (S5)** names each watcher's objects by its own rule - the Python ones by the tag's `win/sync.py`, the
  Rust ones by car-platform's `names` (asked of `car-platform/examples/probe.rs`, built `--release` beside the binaries;
  `CAR_DOUBLE_PROBE`) - made test-only by putting the test prefix where `Local\codex-auto-resume-` is, never by sharing one
  name; `test_both_watchers_name_their_objects_by_their_own_rules_and_the_names_agree` holds them equal for the scratch
  home. PLAN 6.2 now lists `win/homelock.py` HomeLock in the handover.
* **The release build refuses the test forward (note 8)**: `rust_release.collect_binaries` stops a build whose core carries
  `CODEX_AUTO_RESUME_TEST_CORE` without being the stub core (`test_rust_release`); the stub never ships as a release.

### For P5 (the core)

* `watcher-running`: 0 running, 2 not running or cannot tell - the one contract (S8.1's line corrected above).
* `stop`, run from the archive (`<archive>\payload\app\bin\codex-auto-resume.exe stop`), acts on the home
  `CODEX_AUTO_RESUME_PLUGIN_HOME` (or the default) names, as `claim-home` does, so a repair can stop a host whose installed
  core is gone.
* **S3, the schema put-back (needs the real core; no test before P5):** a migration from a version on an older state
  schema (v0.6.0-v0.6.1x: 3/4) whose Rust setup starts the host and then fails leaves state.sqlite (and advanced.sqlite)
  upgraded under a Python version that refuses it (exit 4, EXIT_SCHEMA_NEWER). The check P5 needs: a v0.6.10-shaped home
  (schema 3, a pending row), the Rust installer with a setup that starts the host (which upgrades the schema) and then ends
  1; after Undo-Migration, `PRAGMA user_version` of state.sqlite is the Python version's again (or its `downgrade-state --to
  <N>` ran with a backup beside it, as Convert-StateForOlder keeps one), the row is there, and the put-back watcher starts
  (not 4). The fix it proves: before the Rust setup, copy state.sqlite and advanced.sqlite where their schema is below the
  current one; Undo puts the copies back only once `Wait-WatcherEnded` is true.
* An edition change inside a failed migration (note 3): what `setup --edition-from` writes (features off,
  edition-left.txt) is not undone by Undo; P5 says whether its install step must be undone, and how.

### For P6 (the host)

* **It ends when moved aside (S2; PLAN 6.10):** a v0.6.26 installer run by hand (its Setup exe, its Install.cmd) looks
  only for `runtime\pythonw.exe` and moves `app\` aside under the host; its setup then finds the mutex held
  ("already-running"), and the host would run on from `app.old-<stamp>` with its data deleted. The host looks, at least
  once a second, at the file at the path it was started from (compared by volume and file index); once nothing is there,
  or another file is, it ends as on its stop event (a turn in progress finished first), letting go of the mutex and the
  HomeLock. The double's `watch --flavour rust` does exactly this (`own_image`), and the installer proofs rely on it
  (`test_b5_*`). Only the host can: v0.6.26 is frozen.
* It takes the watcher mutex and stop event of `win/sync.py` and the HomeLock files of `win/homelock.py` (both
  `homes\<sha256>.lock` and `id-<volume>-<index>.lock`, the lock's range and share mode as the reference's): P6's diff of
  both, and one installer proof with the real host and the real names (S5).
* `-SkipStartup` on a migration keeps the Python-shaped Run value (note 4): PLAN 6.5's v0.6.28 removal of the stand-ins
  must re-register such values first.
## The Unicode tables follow the product's Python (branch `car-v0627-unicode16`, 2026-11-26)

REVIEW-surface S1: the tables were made by this PC's 3.13.15 (Unicode 15.1.0); the product bundles 3.14.10 (Unicode 16.0.0),
whose `int()` reads 80 more digits and whose bidirectional classes and `isprintable` cover the scripts Unicode 16 added.

* **Made by 3.14.10.** `pytext_tables.rs`, `bidi_tables.rs` (`gen_tables.py`), `printable_gen.rs` in car-codex and car-platform
  (`gen_codex.py`), `text_tables.rs` and `unicode_gen.rs` of car-policy (`gen_policy.py`) are remade; each says "Python 3.14.10
  (unicodedata 16.0.0, the product's bundled runtime)" on its first lines. `tests/rustdiff/productpy.py` finds the zip
  (`build/cache/python-3.14.10-embed-amd64.zip`, this tree's or a sibling worktree's, its SHA-256 against `build/make_release.py`),
  unpacks it beside the system temp folder (a `._pth` with `import site` and a `sitecustomize.py` that gives the embeddable runtime
  PYTHONPATH back and then runs the tree's own `tests/sitecustomize.py`), and each generator runs itself under it whatever Python
  started it. `--check` refuses a file stamped by another Python or Unicode (`productpy.stale`), then compares the text.
* **car-store's copy.** `seam/python.rs` held a hand-pasted `DECIMAL_ZEROS` (68): it is car-machine's 76 now, and
  `diffs_unicode16.py` compares the two files.
* **Held by** `diffs_unicode16.py`: every code point of isspace/decimal, bidi L/R, isprintable, `\w`, lower, casefold against the
  bundled interpreter; `int()` over the 80 new digits (countdown and `int(,16)`), review8's near-limit texts and the class of new
  letters (`first_strong`, `embedded`). With the old tables it fails (446 of 1,735 cases).
* **Not changed:** `re._casefix._EXTRA_CASES` is the same in 3.13.15 and 3.14.10; `str.isspace` the same 29 code points; the
  NFKC netloc delimiters the same 19 (AUDIT-v0628's open question closes).
* **For the integration:** car-surface's `ShippedInterpreterDiff` (review8) needs no change once these tables are in; the reference
  runtime switch (`car-v0627-refpy`) makes the other table diffs (`diffs_leaves_machine.TextTables`, `BidiDiff`, `diffs_codex_pure`'s
  printable, `diffs_classify_vocab`) agree under the default too - until then they pass only when the runner itself is 3.14.10
  (`PYTHONPATH="src;tests" <productpy.interpreter()> -X utf8 tests/rustdiff/run.py ...`). Found beside it, not a Unicode matter:
  3.14.10's `json.loads` reads arrays nested up to about 16,900 deep (3.13.15 about 3,000), so `diffs_settings_files` case 232
  (`[` x 10,000) says RecursionError in Rust and reads in the product's interpreter (hand-written car-machine/json: not touched here).


## The MCP server, the panel, the command line and car-bin (seat S5.2, branch `car-v0627-mcp`, 2026-11-26)

PLAN 5.3 row P5 / S5.2, ported from the **v0.6.26 final** and held to it by `tests/rustdiff/diffs_mcp.py`, `diffs_cli.py`
and `diffs_legacy.py` (worlds: `cliworld.py` over bridgeworld's and actworld's). Nothing under `src/`, `advanced/`, `gui/`,
`build/`, `scripts/` or `docs/` changes; car-engine, car-codex, car-adv, car-surface and car-platform are untouched.
car-legacy and `rust/tools/legacy_lines.py` are car-v0627-fix9's files, taken as they are (the 44-shape table), so the
integration merges them without a conflict.

### What is where

| Python | Rust |
|---|---|
| `mcp/tools.py` (TOOLS, `settings_schema`, `own_words`, RESOURCES, `plugged_tools`) | car-control `mcp/tools.rs` |
| `mcp/server.py` (`Server`: transport, envelope, every tool's body, `_no_homes`, START_WORDING, ENDS_WITH_CODEX) | car-control `mcp/server.rs` |
| `mcp/panel.py` and `mcp/assets/` | car-control `mcp/panel.rs` and `assets/panel.css`, `assets/panel.js` (the shipped files read with universal newlines; `PanelDiff.test_assets` holds them to the tree's and the tag's) |
| `compat.mcp_view` (S3.3's `compat/report.py`) | car-control `mcp/seam.rs`, a seam: the integration replaces it with car-codex's |
| `mcpserver.main` (argv, streams, the start with Codex beside the handshake, `STARTER_GRACE_SECONDS`) | car-bin `roles::mcp` |
| `controlcli.main` (argparse, `--home`, `serve`, one-shot) | car-bin `roles::bridge` (over S5.1's `bridge::serve` / `one_shot`) |
| `cli.py`, `commands/{base,records,status,watcher,install}.py` | car-bin `cli.rs` (+ `uris.rs` for `notice_uris`/`codex_link` parsing, behind a module the integration replaces with car-surface's) |
| `scripts/plugin_setup.py`'s commands | car-bin `setup.rs` |
| argparse, the four parsers | car-bin `argparse.rs` over `parsers_gen.rs` (written by `tests/rustdiff/gen_cli.py` from the tag's own parsers; `--check` says whether it is stale) |
| `gui/McpLauncher.cs` (D18) | car-bin `launcher.rs`, the bin `codex-auto-resume-mcp` (std + car-platform's starter; the core with `CREATE_NO_WINDOW`, the three streams relayed, the core's exit code once stdin closed) |

### How `codex-auto-resume.exe` reads its first word (car-bin `roles::dispatch`)

1. a **role of the edition's own** - the table the edition's `main` hands `main_with(&[Role])`, looked at first. This is
   the **role registry seam** of P7-DESIGN: `car-adv-bin`'s `main` passes its roles (the courier and the Stop-hook
   launcher's target among them, S7.3); the standard `main` passes `&[]`, so no advanced role's name or code is in the
   standard binary and `check_rebuild.sh` sees the same bytes with `advanced/` deleted. A `Role` is `{word, run: fn(&Machine,
   &[String], &mut Io, &mut dyn Read) -> i32}`;
2. `bridge` (`controlcli.main`) and `mcp` (`mcpserver.main`), car-bin's own two roles (`roles::STANDARD`);
3. a **`plugin_setup.py` command** (its parser's choices: setup, status, pending, enable, disable, cancel, stop, doctor,
   watcher-running, verify-home, claim-home, uninstall, remove-entry, desktop-shortcut, logs, downgrade-state) - the words
   car-legacy hands on from `plugin_setup.py <words>`, the skill's lines and S8.2's install.ps1 calls;
4. anything else is **the command line** (`cli.main`, prog `auto_resume`): the shortcut's `--home H status`, the link
   handler's `--home H activate <uri>`, `run`, `install`, `compat`, `diagnostics`. A word that is both (`status`) is
   plugin_setup's when it comes first and the CLI's after the CLI's own options, as every published line has it.

The CODEX_AR_CORE=rust shim's `cli` entry is the CLI whatever its first word (car-harness `car-core-stub`).

### The seams

* **`car_control::host::Host`** grew three methods for the panel, with defaults: `text_size` (`textsize.read()`),
  `ui_face` (`typeface.ui_face()`), `face_lacks` (`typeface.lacks`). `SystemHost` answers them over car-platform
  (`registry_reads::text_size`, `typeface::ui_face`, `typeface::lacks`).
* **`car_control::mcp::seam::mcp_view`**: `compat.mcp_view`, written over car-machine's generated compatibility
  vocabulary (its `except Exception` kept as `Err(Unsummarised)`). **The integration replaces it with S3.3's** and
  `Host::compat_view` with `compatio.reader_view` (still `null` in `SystemHost`, so the summary is the invalid view's).
* **`car_bin::seam::Outside`**: what the command line asks beyond the Host. The registrations (`register_aumid`,
  `unregister_aumid`, `install_protocol`, `uninstall_protocol`, `shortcut_*`, `desktop_*`, `addremove_*`) and
  `watcher_mutex(state_dir, timeout)` are real in `SystemOutside` (car-platform over `HKCU`). **Refused until the
  integration hands them in:** `backend` (`App.backend()`: discovery, the engine's checks - S3.3 and P6's App),
  `engine_word` (`compatio.engine_word`), `app_paired` (`_app_paired`: `backend.app_identity()`, `App.engine_moved()`),
  `app_running_now` (`codex.pairing`), `resource_users` (the Restart Manager), `history` (`LocalSource.latest_failures`,
  car-codex), `doctor_live_view` (`compatio.live_view` with the backend), `run_watcher` (`App.run`: the host is the
  watcher, P6), `announce_cancelled` (`notifier.build_cancelled`/`deliver`, car-surface), `open_dashboard`/`open_chat`
  (`ui.tray`, cut C6), `power_stop` (`notifier.activate`). With them refused, `status` says `codex engine : unavailable
  (engine_discovery_not_ported)`, `doctor` fails its engine line where the app is not known closed, `run` ends 1.
* **`car_bin::uris`**: `notice_uris.parse_*` and `codex_link.parse_chat_uri` over a port of `urlsplit`/`parse_qs`, for
  `activate`; car-surface owns `notice_uris` (another seat) and the integration takes one of the two.

### What is Rust's own (PLAN 6.4, S8.2) and what the reference keeps

The registrations the core writes: the sign-in value `"<home>\app\bin\CodexAutoResume.exe" "--home" "<home>" "run"` (the
`--home` S8.2 requires), the link handler `"<home>\app\bin\codex-auto-resume.exe" "--home" "<home>" "activate" "%1"`, a
Start-menu entry with no settings window opening `codex-auto-resume.exe --home <home> status`; `setup` starts the host
(`app\bin\CodexAutoResume.exe --home <home> run`, `not-started` where it is missing, as the reference says where there is no
pythonw.exe), copies no `watcher-launcher.py` and has no Python-version check. `setup`'s `installed()` is the reference's
test, which a Rust archive passes (car-legacy's two programs and the package folder). `engine-trusted <path>` (S8.2's
install.ps1) is a role answering 0 only for `official_engine == (True, "openai_signature")` - refused (1) until the
integration hands `Outside::official_engine` in. Everything else - every line, word, code and file - is the reference's,
and `cliworld.HOOK` puts only these shapes into the tag for the diffs. AUDIT-v0628 has the six lines.

### What P6's host and the integration must hand in

* **P6 (the host):** the watcher is `app\bin\CodexAutoResume.exe --home <home> run` (what `setup` starts and the Run value
  names); `Outside::run_watcher` (`codex-auto-resume.exe --home H run` reaches it only by hand: car-legacy hands `run` to the
  host); the sign-in value and protocol re-registration when `CODEX_AUTO_RESUME_LEGACY_ENTRY` is `run` or `activate`
  (car-bin does not look at the variable); `announce_cancelled`, `open_dashboard`, `open_chat` and `power_stop` (the
  notifier and the tray, car-surface/C#); the set-aside sweep of `bridge serve` (`controlcli.sweep_soon`).
* **The integration:** the Outside's engine calls (S3.3 car-codex `codex/pairing`, `compat/*`, P6's App:
  `backend`, `engine_word`, `app_paired`, `app_running_now`, `official_engine`, `doctor_live_view`, `resource_users`,
  `history`); `mcp::seam::mcp_view` -> car-codex's; `Host::compat_view`/`compat_live_view`/`compat_import` (S5.1's list);
  car-surface's `notice_uris` for `uris.rs`; the account's time zone for `Host::local_clock` (the CLI's `format_local`
  and the log's stamps are written on it: UTC until then); S8.2's `codex-auto-resume-setup.exe` (`setup_main` on
  car-v0627-fix9) over this branch's car-bin, keeping `core_stub` only for its test double; `rust_release.py` gains
  `codex-auto-resume-mcp.exe` from car-bin at `payload/app/mcp/` in place of the C# launcher.

### The proofs (reference the v0.6.26 final; `run.py --build --reference v0.6.26`)

```
python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 -v -k diffs_mcp        12 tests OK (the last fixes re-run alone)
  GoldenMcpDiff 2   every case of wiregolden.MCP_CASES (20 tool files), tools-list.json and _protocol.json (16 cases): Rust
                    equal to the reference AND, canonicalised as wiregolden does, to the committed tests/golden/mcp (D12)
  FramingDiff 2     117 streams: BOMs, CRLF, a lone CR (and at the 8192-byte boundary), Unicode padding, bad bytes in the first
                    and a later chunk, json's own nesting limit, batches nested 980-1000 deep (Python's RecursionError at 995,
                    3.13 and 3.14), 18 ids x 3 envelopes, 31 malformed envelopes, batches of every kind; 600 requests
  ToolsDiff 5       every tool over arguments of every shape (175 calls), 11 watcher worlds (start_watcher's every outcome), 4
                    homes x 4 administrators' keys x 2 damaged states, 17 compatibility views (mcp_view's every refusal), 3 clocks
  PanelDiff 3       the assets; _STYLE, _SCRIPT, panel_keys, FONT_STACK, tiles and rules; 30 pages (themes, designs, text sizes,
                    UI fonts, seeds, every special day) x 8 worlds (languages, RTL, faces that lack letters) byte for byte;
                    resources/read over 8 worlds and every special day
  in all: 169 streams, 1046 response lines, every Host call equal
python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 -v -k diffs_cli -k diffs_legacy      8 tests OK
  ParserDiff 1      43 command lines over the four parsers: abbreviations, --name=value, -n5, --, negative numbers, every
                    argparse error and -h, as stdout, stderr and the code
  CommandsDiff 4    every CLI command (pending/enable/disable/cancel/logs/stop/run, status and doctor over 8 engine worlds and
                    the Restart Manager, compat 7 ways, install and uninstall 11 ways, activate over 13 URIs x 2, diagnostics,
                    downgrade-state 7 ways), on the golden, empty and fresh homes
  SetupDiff 1       every plugin_setup.py command: setup through each of its exits and environment words, watcher-running,
                    status, pending, enable, disable, cancel, stop, doctor, logs, verify-home, claim-home, remove-entry,
                    desktop-shortcut, downgrade-state, uninstall [--purge], on fresh and empty homes too
                    stdout, stderr (but Python's tracebacks), code, every file (logs, runtime.json, the markers, the bundle),
                    the state, every Host and Outside call (4,210 in SetupDiff alone) equal
  LegacyShapesDiff 1   all 44 published lines: car-legacy's python.exe/pythonw.exe hand each to the core (car-core-world) with
                    the words its table says, once; the answer (python.exe) and the code are the reference's for the same
                    words; downgrade-state's one closed line, watcher-running 0/2, setup 0/1/2/4/5 hold
cargo test -p car-bin (tests/table.rs 6), cargo test -p car-control --test mcp_panel 1
```

Found by the diffs and fixed here: the panel's palette and shadows are soft's where the reference's defaults are; a batch's
depth limit; a home's ownership marker, `edition-left.txt` and `runtime.json` are CRLF on disk (Python's text mode -
car-config's `ensure`/`claim_home` marker was LF, a fault of that crate the CLI diffs caught); a compatibility view the
reference cannot index ends the command as its traceback does; `--out` naming a folder is the reference's
`refusing to overwrite <name>`. Faults of the diffs themselves: logging's `converter` and `time.time_ns` on the world's clock,
`format_local` asked in UTC (`TZ=UTC0`), the reference's role dispatch for `bridge`/`mcp`, stand-in names apart from
actworld's, a `face=None` page asking the host.

Mutation checks (a rule broken, the harness rebuilt, the named diff run, the source put back; each one fails it): the batch's
depth limit 995 -> 996 (`diffs_mcp.FramingDiff.test_streams`); one word of the generated settings schema's description
(`GoldenMcpDiff.test_tool_list_and_protocol`, by tools-list.json); `pending` showing 15 characters of the interruption, not 16
(`diffs_cli.CommandsDiff.test_records`); argparse's long options taken only whole, not by a prefix (`ParserDiff`, 6 lines);
plugin_setup's EXIT_UNCONFIRMED 2 -> 1 (`SetupDiff`, 8 cases).

`test_mcp` through the shim (`CODEX_AR_CORE=rust`, car-core-stub now running car-bin; Node 24 present): Ran 75, OK, no skip.

### The re-diff

`python -X utf8 tests/rustdiff/rediff_cli.py --reference v0.6.26`: the ported files changed since the final (`git diff
--stat`), `gen_cli.py --check` (car-bin's parser tables are the tag's), then `-k diffs_mcp -k diffs_cli -k diffs_legacy`.

### Gates (HEAD of this section's commit, `. tools/rustflags.sh`)

`rust/`: fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast: every result ok but the
known red `review_bridge.rs` `a_failure_seen_file_replaced_by_another_of_the_same_size_and_time_is_read_again` (car-platform's
`files::file_index`, a later integration); cargo deny --locked --offline check: all four ok. `advanced/rust/`: fmt, clippy,
test (5 x 0 tests), deny ok; its lock gained car-bin's new path edges. `check_groundwork.py`: OK (car-bin's and car-harness's
new edges in EXPECTED). `check_rebuild.sh`: all eight binaries the same with and without `advanced/`
(codex-auto-resume.exe, -setup.exe, -mcp.exe, python.exe, pythonw.exe, car_core.dll, car-core-stub.exe, car-harness.exe); its
profile-path scan now reports the Windows user name in codex-auto-resume.exe and car-core-stub.exe - the publisher `songyb111-gachon`
(car-platform `addremove::PUBLISHER`, linked now that the CLI registers the entry), not a path: the scan needs an allowance for
that constant (the main session's call).

## The advanced compatibility report and the Stop hook (seat S7.3c, branch `car-v0627-adv73c`, 2026-11-26)

Reference: the v0.6.26 tag (`--reference v0.6.26`); nothing of the scope changed on dev after v0.6.26-beta.2 (`rediff_adv73c.py` lists it).

### What is ported, and where

| Python (advanced unless said) | car-adv |
|---|---|
| `report/records.py` | `report/records.rs` (`read`, `ledger`, `progress`; `Found::value()` is the reference's dict) |
| core `ownreport/evidence.py`, `reading.py` (the parts `records.py` imports) | `report/evidence.rs`, `report/reading.rs` |
| `report/document.py` + core `ownreport/document.py` (`check_parts`, shapes, `encode`) | `report/document.rs` |
| `report/github.py` | `report/github.rs` (`inspect`, `publish`, `find_gh`, `environment`, `Runner`) |
| `report/flow.py` | `report/flow.rs` (`Flow`, its jobs on threads) and `report/seam.rs` |
| `hook/format.py`, `hook/handler.py` | `hook/format.rs`, `hook/handler.rs` |
| `engine/hookclaims.py` (`claim`, `blocked_at`, `held`, `spent_on`) | `engine/hookclaims.rs`; `state/seam/hooks.rs::{held, spent_on}` stay as S7.1a wrote them and equal these (the ledger diff holds both) |
| `control/hookplugin.py` | `control/hookplugin.rs` (`write`, `remove`, `present`, `roots`, `target`, `follow`, the `Files` seam = `WRITER`/`REMOVER`) |

`lib.rs` carries the seat's lines only: `pub mod report; pub mod hook;`, `pub mod control { pub mod hookplugin; }` and `pub mod engine { pub mod hookclaims; }` (inline, so no `mod.rs` of another seat is touched; the integration replaces them with the real `engine/mod.rs` and `control/mod.rs`).

**Not ported, and why.** `report/__init__.py::make` (the capability's factory, S7.2a's registry entry: `Flow::new` is what it calls); `StopHook` of `engine/hookclaims.py` (P3's `gate`, P8's `tick`: the plug trait is S7.2a's; what it calls is `hookclaims::blocked_at` and `hookplugin::follow_real`); `Hands.live` of the handler (S7.3d, over S7.2a's runtime); the hook's launcher binary (S6.2a's stub; `hook::handler::main` is what `codex-auto-resume.exe hook` calls); `github.run_process`'s job object (S7.3b's car-platform `job.rs`).

### The seams (each named, none replaced here)

* `report::reading::WatcherView` - `compatio.reader_view(paths, settings)` (S3.3 / `car-codex::compatio`). The diffs hand it as data.
* `report::document::Facts` - `config.version()` and `sys.getwindowsversion()` (car-config / car-platform at the entry point).
* `report::seam::Runtime` - `runtime.arming.policy()`, `.states(fresh=True)`, `.state.arming()`, `.arming.trip`, `.state.note` (S7.2a).
* `report::seam::{HomeMutex, MakeMutex}` - `ReportMutex`: the named mutex per home, its handle kept for the process's life, abandonment told. car-platform's `sync::Mutex` closes the handle on exit and cannot try without waiting: S7.3d (or S3.1's owner) adds `try_take() -> Result<abandoned, Busy>` over the kept handle; `seam::mutex_name` is the name.
* `report::seam::CodexHome` - `codex/inuse.home(paths)` (S7.2c).
* `report::github::{Runner, Jobs}` - gh started in the job object: `ProcessRunner` over `Jobs` is written (suspended start, adopt, timeout, kill) and never run by a seat; `Jobs` is S7.3b's `job.rs`.
* `hook::handler::Hands` - the capability's state (`Arming(AdvancedState).current()`), Codex's latest turn (`LocalSource.latest`), the settings, the claim.
* `engine::hookclaims::World::managed` - `control/policy.managed_policy()` (car-control's `Host::managed`).
* `Edges::hook_follow` (S7.1b): `control::hookplugin::follow_real(paths, codex_home, armed)`.
* core's `ownreport/{evidence,reading,document}`: car-control has a port on `car-v0627-bridge6` (not in this tree; merging it conflicts in nine files). `report/{evidence,reading,document}.rs` are that port at `acea87eb0`, taken as the port of the same Python and widened to what the advanced reader asks and the Dashboard's report never does: the ledger's `paid` times in `another_route`/`by_route`, `ledger_reach`, `place`'s `elsewhere` count and `body`'s progress counts. The integration folds the two (car-control's `by_route(rows, reach)` is this one's with `paid` empty; its `body` is this one's with every `progress` None) and re-exports; nothing else in `report/` changes.

### The proof (`tests/rustdiff/diffs_advreport_*.py`, `diffs_advhook_*.py`; examples `advreport`, `advhook`; helper `advreport.py`)

Each family runs a script under the tag's own advanced edition (`advref.run`) - the homes made by the tag's `advanced/tests/reportfixtures.py` and `ghfake.py`, taken out of git beside its package - and the same cases through the Rust example; every answer must be equal as the wire writes it, the refusal's class and closed code included. The Rust side never writes a home it reads (a snapshot of every file, its time and its bytes before and after), starts no process (gh is a recorded script of the tag's own `FakeGh`), reads no real home, and shows no window.

* goldens: the six homes of `reportfixtures.SCENARIOS` read by the Rust reader; the body (car-machine's writer, two-space indent) equal **as bytes** to `advanced/tests/golden/report/*.json`'s, `left_out`, the envelope's keys and fixed values; no golden regenerated.
* records: the six scenarios asked 18 ways and under 13 watcher's reports, every refusal (no state, newer, older, damaged, a column gone, a ledger newer / damaged / marked readable-from, a junction in place of a folder, no engine, a bad version, 501 records), history absent / moved / the home gone / a file in its place; a state locked under `BEGIN EXCLUSIVE` (both give up after their three seconds); hand-edited rows of every wrong type and time, logs of every size, encoding and line break; the spend ledger in every shape; `ledger_reach` on a grid; `by_route`, `place`, `body`, `current_engine` over generated input; `check_login`, `assemble`, `check` over the six bodies and about 120 breakages.
* gh: every check and every write over the recorded script (calls compared: argument list, environment digest, folder, stdin, timeout, flags), the Unicode case folding of a name, pages of every shape, a stop between any two writes, the pull request gh will not repeat; `find_gh` over PATHs of every kind.
* hook declaration: 6 formats over 15 trees (complete, one root, none, junctions, ours / foreign / damaged / mixed declarations): every step and the whole tree equal, bytes included - **the tag writes the declaration in text mode, so with Windows line ends (`\r\n`)**; kept.
* hook handler: `read_input` and `pick` over every shape of input, `stop_of`, `turn_key`, `continues`, `decide` over every failure kind, language and claim answer, `main` with its budget and its commit grace.
* hook claim: the claim over real `state.sqlite` + `advanced.sqlite` twins: granted, answered, once a turn, not armed, paused, observe only, the thread's switch, the administrator's keys and quiet hours, core's record in flight / cancelled / held / postponed / over its budgets, the day's caps, this edition's ceilings, no file, no id, a lock not had; every answer and every table equal.
* flow: the Dashboard's commands - build, save, check, send, job - over a scripted runtime (policy, where the capability stands, what the state stores, changes between the questions of a send, a pause flipped mid-send), a scripted home mutex (free, abandoned, busy, one that cannot be made), the recorded gh, a clock that steps, tokens and a gate that holds a job open (one at a time): 75 programs, every status and refusal, and the journal, the trips, gh's calls, its sleeps and how many times each seam was asked, all equal. The diff found one fault of the port's own (the web status's keys in the wrong order).

### Odd reference behaviour kept (also in AUDIT-v0628.md)

* `document.check` lets `codex_version: null` pass (`canonical_version(None) != None` is False).
* `hookplugin.write` writes the declaration in text mode: `\r\n` on Windows.
* `gh api --paginate`'s pages are read with `raw_decode` (NaN and Infinity accepted, a recursion past the limit a `RecursionError` that goes on); `car_machine::compat::raw_decode` has the same grammar.
* `github.spelling` uses `str.casefold()`: only `ſ K ß ẞ ﬀ ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ` fold into a login's ASCII; every other non-ASCII character cannot, so `ascii_fold` is exact.

### Checks and mutations (`CARGO_BUILD_JOBS=2..4`; reference v0.6.26, rustc 1.100.0)

```
## advanced/rust   fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked rc=0 (car-adv 3 unit tests); cargo deny --locked check: all four ok
## rust            fmt --check rc=0; cargo deny rc=0 (the standard workspace's code is not touched by this seat: only this file)
python -X utf8 rust/tools/check_groundwork.py            -> rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD           -> see the return (a long run; its log is named there)
```

The diffs, one `unittest` module each, all equal on the last run: `diffs_advreport_goldens` (2), `diffs_advreport_records` (7: Read, Locked, Damaged, Ledger, Evidence, Document ...), `diffs_advreport_github` (3), `diffs_advreport_flow` (1, 77 programs), `diffs_advhook_plugin` (1, 240 programs over 15 trees), `diffs_advhook_handler` (3), `diffs_advhook_claim` (2).

Mutation checks (a rule broken in car-adv, the example rebuilt, the named diff run; each fails it, the source restored with `git checkout -- file`): the ledger's paid times no longer mark a record another route's (`diffs_advreport_goldens`: the two ledger scenarios' bodies and counts change); the long s no longer folds into a login's letters (`diffs_advreport_github.InspectDiff`: `gh_spelling` becomes `web`); a declaration with a command that is not ours removed all the same (`diffs_advhook_plugin`); a rate limit is a kind a hook may continue (`diffs_advhook_handler.InputDiff`, the `continues` grid); a second claim in a turn that has had a block passed, not refused (`diffs_advhook_claim.ClaimDiff`); the flow keeping five reports instead of four - **survived** the first time (no case checked the oldest of five builds), so two programs were added (four builds then the first checked; five builds then the first checked), and it then failed.

### Left undone

* The real home mutex, the job object around gh, `Hands.live`, the plug-side `StopHook`, and the hook launcher binary are seams (above), not diffed: each needs Windows state or the plug of S7.2a.
* The tag's own default `find_gh` and `inuse.home` (the process's PATH and Codex home) are the cases' to name; the diffs name them.

### For later seats

* S7.2a: implement `report::seam::Runtime` over the real `Arming` and `AdvancedState`; `Flow::new(paths, Config)` is `report.make(paths)`; `StopHook` calls `hookclaims::blocked_at` (P3) and `hookplugin::follow_real` (P8).
* S7.3a: `surfaces.py` calls `Flow::answer(runtime, definition, command, argument)` and `Flow::job`.
* S7.3b: `github::Jobs` (job object, `NtResumeProcess`).
* S7.3d: `hook::handler::main` as the `hook` role; the live `Hands`; the `HomeMutex`.
* Re-diff for the final: `python -X utf8 tests/rustdiff/rediff_adv73c.py --reference v0.6.26`.
## S7.2c: the advanced edition's codex parts, autocheck, compatdata and inuse (branch `car-v0627-adv72c`, 2026-11-26)

Ported into `car-adv` (D19) from the **v0.6.26 final** itself (D17; `codex/inuse.py` is the final's, FINAL-DELTA rows 20-23):

| Python (`advanced/src/codex_auto_resume_advanced/`) | car-adv |
|---|---|
| `compatdata.py` | `compatdata` (validate, `_read`, adopt, in_force, overlay, table_for, summary, dumps; the five trust rules) |
| `autocheck.py` | `autocheck` (the whole `CHECKS` table by hand, judge, settled, grade, the record, due, `_write`, ask/run/probe_engine, run_once, tend); S7.1b's `seam_autocheck*.rs` are gone, `arming` and `advprobe` name `autocheck` |
| `codex/inuse.py` (final) | `codex::inuse` (tell/told/forget, **saw/elsewhere**, home, `_pinned`, backend over car-codex's `Backend` and car-config's discovery; `Looked` is what `saw` reads of a backend) |
| `codex/protocol.py` (tables, refusals) | `codex::protocol` (MEASUREMENT_/CAPABILITY_METHODS, FORBIDDEN, DECLINE_ANSWERS, ACCEPTING_WORDS, reply_to, methods_for, methods_for_capability) |
| `codex/turns.py`, `lineage.py`, `threads.py`, `conversation.py`, `sessions.py`, `goals.py`, `credits.py` | `codex::{turns, lineage, threads, conversation, sessions, goals, credits}` over car-codex's `paths`, `sql`, `LocalSource`, `values`, `labels`, `eligibility`, `usage` |
| `time.strptime` + `calendar.timegm` for the forms read | `pytime` (CPython's `_strptime` expressions, Unicode digits, backtracking) |
| `str.isalpha` | `codex/alpha_gen.rs` (`tests/rustdiff/gen_advcodex.py --write/--check`, from the reference interpreter) |

**Not ported (left for the next seat, named):** `codex/protocol.Session` and `submitted` (the one-turn app-server helper: the
runtime's channel, S7.2a/S7.2e1, opened only when a person measures or core hands a capability a send), `codex/headless.py`
(450, over `Session`), `codex/ipc.py` (490, the Desktop's named pipe: needs car-platform `ipc_pipe` and a pipe of the test's
own name), `codex/tokens.py` (320, rollouts' token counts, local days), `codex/wmi_escape.py` (287, MW; never run), `win/stopflag.py`
and `win/waketimer.py`, and `turns.booted_of` (core's store read: `Turns::running` takes the boot time as a value). S7.2c's
time ran out before them; nothing in this seat's modules waits on them.

### The seams

* `seam::Edges::table_for` is `compatdata::table_for(Some(state_dir), engine, &measured::table(), now, this_product(version))`;
  `Edges::checked_for` is `autocheck::results_for(advanced_dir, engine)` (an `Err` is Unavailable). A host's `Edges` delegates
  to them as it delegates the views to `compat_views`.
* `codex::inuse::elsewhere(Some(home))` is what `AdvancedPlug.served_elsewhere` answers (S7.2a; any failure the empty set);
  the usage meter (S7.2d) calls `inuse::saw(Some(home), &backend)` after `app_identity()`; the plug's `codex` hook calls
  `inuse::tell`; `autocheck::tend` is the runtime's tick's (S7.2a) and reads `inuse::told`.
* `autocheck::World { system, product_version }` and `inuse::Discovery` are what the entry points hand in: car-codex's
  `Platform` and `config.version()`. Module state (inuse's told/elsewhere, autocheck's looked/running) is per process;
  `inuse::reset`, `autocheck::reset`/`join` are for the harness.

### The diffs (`tests/rustdiff/advcodex.py`, `diffs_advcodex_{compatdata,autocheck,inuse,readers}.py`)

The Rust side is car-adv's example `advcodex` (one request of cases, the world's signers and process list stand in for
Windows: `examples/advcodex/world.rs`); fake engines are car-adv's example `advfake` (a codex.exe stand-in answering
`--version`, `queue --help`, `app-server generate-json-schema` and `features list` from a script, logging every call). The
reference is the tag's advanced edition (`advref.run`, tag `v0.6.26` unless CODEX_AR_REFERENCE names another) with
`authenticode.signer`, `processes_named`, `resource_users`, `process_identity` and `os.getpid` replaced. Cases that write run
the reference then the probe on the same folders (`Scene`): the answers, every file left (byte for byte: the autocheck
record, the adopted data) and every child the engine was asked for are held equal. `core.build_rest` builds both examples.

The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_adv72c.py --reference v0.6.26`.

### For later seats

* S7.2a: `served_elsewhere` = `inuse::elsewhere`; `Plug::codex` = `inuse::tell`; the tick calls `autocheck::tend`; fill
  `Edges::table_for`/`checked_for` as above. `protocol::methods_for_capability` is the allow-list a channel's session checks.
* S7.2b: `inuse::backend`, `protocol`, `turns`, `threads` are here; `autocheck::AUTH_FILE` names codex/authfile's file.
* S7.2d: `credits::parse`/`outcome`/`full`, `turns::Turns::running`, `inuse::saw`.
* The next S7.2c seat: `Session`, `headless`, `ipc`, `tokens`, `wmi_escape`, `win/stopflag`, `win/waketimer` (above).

### Found and not fixed (another seat's crate)

car-config's `Paths::ensure()` ignores `create_dir_all`'s error (`let _ =`): where `config` is a file, Python's
`directory.mkdir(parents=True, exist_ok=True)` raises FileExistsError and stops before `logs/`; car-config goes on, makes
`logs\` and its marker, and answers Ok. `autocheck::write` still answers OSError there (its own folder cannot be made), but
the files left differ, so `diffs_advcodex_autocheck.test_write` leaves that home out. For S1.1/the integration: raise on
the mkdir as the reference does.

### S7.2c's checks (reference v0.6.26, rustc 1.100.0, `CARGO_BUILD_JOBS=4`)

```
diffs_advcodex_compatdata  4 tests OK: ~2,300 validate/summary cases over the advanced data's history, the test file's
                           shapes and their mutants (5 products); 41 tables x 24 documents x 5 engines overlaid; 160 homes
                           adopted and read, the files left byte for byte
diffs_advcodex_autocheck   6 tests OK: CHECKS row by row; judge over ~560 schemas; 64 record files; 600 due cases; _write over
                           4 homes; run_engine/probe_engine over 12 fake engines and tend over 5 x 17 ticks, the record and
                           every child equal
diffs_advcodex_inuse       4 tests OK: 1,500-step walks of tell/told/forget/saw/elsewhere/home; backend told, pinned and
                           discovered under a scratch LOCALAPPDATA; protocol's tables and ~300 replies
diffs_advcodex_readers     3 tests OK: 5 full homes and 10 homes wrong as a whole (every reader), credits, str.isalpha over
                           every code point
advanced/rust, rust        fmt --check, clippy -D warnings, test --locked, deny: all ok
check_groundwork.py OK; gen_advcodex.py / gen_advpolicy.py --check current; check_rebuild.sh: the standard binaries the
same with and without advanced/, no profile path
```

Mutation checks (each alone, release probe, its diff, restored): compatdata rule 1 (a build fail no longer wins), autocheck
SANE_COUNT 49, `inuse.saw` comparing paths as written, `inuse.tell` keeping what was seen elsewhere, turns keeping a
`completed_at` of 0: all caught. A sixth, a `recorded_at` equal to publication refused, survived; the diff now holds a record
made the very minute of publication and catches it.

## S7.2c remainder (seat adv72d, branch `car-v0627-adv72d`, 2026-11-26)

Everything S7.2c's section names under "Not ported", from the **v0.6.26 final**'s `advanced/src/codex_auto_resume_advanced/`
(reference `v0.6.26`, `tests/rustdiff/advref.py`):

| Python | Rust |
|---|---|
| `win/waketimer.py` | car-adv `win::waketimer` (`WakeTimer`, `filetime`: half-even rounding, the c_longlong's low 64 bits) |
| `win/stopflag.py` | car-adv `win::stopflag` (`StopFlag`, `event_name`: core's StopEvent name of the folder as pathlib writes it) |
| their ctypes calls | car-platform `wake` (new, D3): `TimerKernel`, `PowerSettings`, `EventKernel`; `SystemTimer`, `SystemPower`, `SystemEvents` the real ones, built only by the product's entry points |
| `codex/turns.booted_of` | car-adv `codex::turns::booted_of(state_dir)` (core's `Store::open` as `Store(paths.state_dir)` opens it, made and migrated where missing; car-control's link probe) |
| `codex/tokens.py` | car-adv `codex::tokens` (`file_key`, `watched_homes`, `rollouts`, `unchanged`, `read`; the local day from a `LocalClock`: the product hands car-platform's `Crt`) |
| `codex/wmi_escape.py` | car-adv `codex::wmi_escape` (`probe` over a `Chain`, `helper_argv`, `heartbeat_command_line`, `helper_plan`, `heartbeat_record`, the script and bootstrap). **Never run**: nothing implements `Chain` but the diff's stand-in |
| `codex/protocol.Session`, `submitted` | car-adv `codex::session` (`Session`, `Channel` - what `submitted` and `headless` need of a session -, `SessionError`, `Submitted`); over car-codex's `TextReader`/`next_message`, `Backend::{compatible, argv, environment}`, `pairing::own_server[_gone]` and car-platform's starter |
| `codex/headless.py` | car-adv `codex::headless` (`HeadlessRun`, `Follower`, `follower()` - the process's one -, `stop_all`, `live_session`, `settings_allowed`, the readers, `EMPTY_REFUSED`, the retry settings) |
| `codex/ipc.py` | car-adv `codex::ipc` (`stop_turn`, `start_turn`, `steer_turn`, `Channel`, `Gate`, `request_shape`, `filled`, `stopped`); its pipe calls car-platform `ipc_pipe` (new: `open`, `server_trusted`, `Pipe::io`, `uuid4`; the windows crate gained the `Win32_System_Pipes` feature, no new crate) |

car-adv's `win::tests::car_adv_names_no_suspend_or_shutdown_call` holds P7-DESIGN 3.5's rule at the source: no
`SetSuspendState`, `ExitWindowsEx`, `InitiateSystemShutdown*`, `SetSystemPowerState` and no `windows::Win32` anywhere in
car-adv (src and examples); car-platform's `wake` test holds that it writes no power setting. `ipc_pipe::open` refuses
the Desktop's own pipe name in car-platform's own tests and wherever `CAR_NO_REAL_IPC` is set (the ipc diff sets it).

### The seams

* `headless`: `HeadlessRun::new(capability, key, opener, follower())`, the opener `live_session(backend)` (a closure
  making `inuse::backend(...)`); `resume(thread, launch_guard, still_unloaded, words, client_id)` takes core's guard and
  look as closures answering what the reference's `__enter__`/callable gives. `stop_all(follower(), 20.0)` is the
  runtime's to call as the watcher leaves (S7.2a): the reference registers it with `atexit`. `seconds` is an `f64`:
  `owe(thread, model, seconds)` gets `8.0` where the reference passes the int it was given (see AUDIT).
* `session::Session` owns its `Backend` (the follower thread takes the session); `Channel::call` is submit + receive.
* `ipc`: the pipe name is a parameter (None = the Desktop's), the request ids a closure (`ipc_pipe::uuid4` in the
  product), the guard a `Gate` (enter gives `permitted`, exit may fail).
* `wmi_escape::Chain` has no real implementation: MW's live run needs the Rust edition's own helper and heartbeat roles
  (S7.3d's `car-adv-bin`) and car-platform's job-object calls; until then the measurement is the main session's.
* `tokens::read(rollout, known, budget, &Crt)`; `watched_homes(installation, settings_file, env, config_os, os)`.
* `WakeTimer::new(Box::new(SystemTimer), Box::new(SystemPower))`, `StopFlag::new(state_dir, Box::new(SystemEvents))`
  in the product; never in a test.

### The diffs (`tests/rustdiff/advcodexd.py` + `diffs_advcodex_{win,booted,tokens,wmi,session,headless,ipc}.py`)

`advcodexd.py` is S7.2c's harness with its own reference script (the same `advcodex` probe; op families `wn.`, `bt.`,
`tk.`, `wm.`, `ss.`, `hl.`, `ip.`); its `scene` compares a SQLite file by its dump. Nothing real is asked of Windows: the
timer, the power settings, the stop event and the WMI chain are scripted stand-ins on both sides that log each call,
compared in order; the session's engine is car-harness's `car-fake-codex`; the IPC pipe is the test's own (fakeipc).

* `win`: 1,507 timer walks, 160 `filetime` values (half-even ties, 2**80, inf, nan), 806 stop-flag walks, 6 names.
* `booted`: 11 state folders x 2 (none, empty, heartbeats with every boot time, damaged, a file), files as dumps.
* `tokens`: `read` over 220 generated rollouts x 11 `known` rows and budgets plus LOOK_BACK cases, and `unchanged`
  (~4,900 cases), each under TZ unset, `JST-9` and `EST5EDT`; `rollouts` over 7 home lists x 6 clocks (nested folders,
  a junction, `.JSONL`, a folder named `x.jsonl`, files past `keep_days`); `file_key`; `watched_homes` told and not x 8
  `codex_homes` settings.
* `wmi`: the constants, 1,511 probe walks, the helper's `pwsh.run` plan over 150 inputs, the pwsh variables, the
  heartbeat record.
* `session`: 20 sessions on 20 fake engines (measurements, capabilities, both, neither, an unknown word; requests Codex
  makes of every kind, notifications, no-JSON lines, refusals with every code shape, a float id, another call's id, a
  wait that runs out, submitted answered later, initialize answering another home / no home / a non-text home / no
  object / an error, engines that fail the checks): answers, counts and every byte sent (stdin.bin) equal.
* `headless`: 266 runs (turn, compact, fallback; app look, owe, guard, look again; every answer and raise; stops from
  inside a drain) with every call, look, drain and clock reading logged; the pure readers over ~70 shapes.
* `ipc`: 38 calls on fresh scratch pipes (every word: stopped, not_stopped, no_client, version_mismatch, no_pipe,
  no_answer, unconfirmed, refused, broken, held, started, steered) with every request the app saw; the shapes.

Mutation checks (each alone, its diff, restored): the timer's `LocalFree` skipped when the read raises; the stop
flag's handle left open when its wait raises; `booted_of` refusing a missing state folder; a token pass counting a
repeat of the same totals; the probe reading the helper's life after the job closed first; the session counting a
declined request twice; the session's exit not unsubscribing; headless's app look every 5 s; the steer's broken pipe
taken as broken instead of unconfirmed: all caught. One survived and is equivalent: headless's interrupt asking for a
compaction's turn (a compaction never has one: its `turn_id` is always None).

The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_adv72d.py --reference v0.6.26`.

### For later seats

* S7.2a: the runtime calls `headless::stop_all(headless::follower(), 20.0)` at exit; capability channels open
  `session::Session::new(backend, None, Some(capability), config)`; the supervisor (crash_restart) holds a `StopFlag`
  and the wake capability a `WakeTimer`, over car-platform `wake`'s `System*` types.
* S7.2d / S7.2e: `ipc::{stop_turn, start_turn, steer_turn}` with `ipc_pipe::uuid4` as the ids and core's errand guard
  as the `Gate`; `headless::HeadlessRun` for headless_run, compact_continue, model_fallback (`owe` gets f64 seconds);
  `turns::booted_of(state_dir)` for `Turns::running`; `tokens` for usage_analytics (the store's `token_files` rows are
  the `known` maps).
* S7.3d: `wmi_escape::Chain` over car-platform job objects and the edition's own helper/heartbeat roles.

## Integration 8 (branch `car-v0627-rust`, 2026-11-26)

Five branches merged with `git merge --no-ff`, in this order, both sides of every conflict kept, each merge's own diffs run
before the next; then the fold, the wiring and the three fixes, each its own commit.

| Merge | Branch | What came in |
|---|---|---|
| `f49f4cc50` | car-v0627-fix9 `54553021a` | review 9's installer fixes (Undo-Migration, repair without a core, the way back, the double's own names, the release build refusing the test forward) |
| `0ad2f4770` | car-v0627-unicode16 `a59bc6fbf` | the six Unicode tables under the bundled 3.14.10, car-store's DECIMAL_ZEROS 76, `productpy.py`, `diffs_unicode16.py` |
| `ad5c7da71` | car-v0627-mcp `ec2a9aede` | S5.2: car-control `mcp/`, car-bin's roles, argparse, CLI, plugin_setup commands and the MCP launcher bin, car-harness `car-core-stub`/`car-core-world`, `diffs_mcp`/`diffs_cli`/`diffs_legacy` |
| `af54ec665` | car-v0627-adv73c `b3abf63b2` | S7.3c: car-adv `report/` and `hook/`, `engine::hookclaims`, `control::hookplugin`, the `advreport`/`advhook` examples and their diffs |
| `f54536e0d` | car-v0627-adv72d `c43f208d3` (holds adv72c `1540e2683`) | S7.2c and its remainder: `autocheck`, `codex::*`, `compatdata`, `pytime`, `win::{stopflag, waketimer}` |

Conflicts: `rust/GROUNDWORK.md` in every merge (all sections kept, in merge order; fix9 rewrote S8.2's last P6 line, its
version kept); merge 3: car-bin `lib.rs`/`main.rs`/`Cargo.toml` (below), car-config `paths.rs` (Integration 6's
`pyfile::write_text`, CRLF on disk, kept; S5.2's `OWNER_TEXT_ON_DISK` stays as the bytes it names), car-harness
`Cargo.toml`/`lib.rs`, both locks and check_groundwork's car-bin and car-harness edges (the union); merge 5: car-adv `lib.rs`
(both seats' modules). S5.2's section named the Windows user name in a sentence; it says "the Windows user name" now.

### Decided here

* **`codex-auto-resume.exe` stays the stub core** (`car_bin::core_main`, the installer proofs' test forward with it), and
  `car_bin::main_with(&[])` - S5.2's dispatcher - runs through car-harness's `car-core-stub` (the CODEX_AR_CORE=rust shim)
  and `car-core-world`. The release's own proofs run the archive's core on scratch homes (`rust_legacy_bootstraps.check_entry`
  hands it every published bootstrap line, setup included; the installer proofs hand it to the double), and `main_with`'s
  `setup` writes the Run value, the AUMID and the link handler to HKCU through car-platform, which no scratch home redirects.
  The switch is one line in `main.rs` once those proofs run the real core with car-platform's registry stand-in.
* car-bin `setup.rs`: fix4's `addremove::display_name` answers a `Str`; the Outside's writer takes text (a lone surrogate,
  never in the product's own manifest, becomes U+FFFD).

### The fold (S7.3c's ownreport copy, `aae2a5c7c`)

car-control `ownreport::{evidence, reading, document}` is the one port. evidence carries the advanced reader's widening
(`Paid` and `another_route(row, paid)`, `by_route(rows, paid, reach)`, `ledger_reach`/`Reach`, `place`'s `elsewhere`, `body`'s
progress counts); the Dashboard's `read_all` passes an empty ledger and every progress None, as `ownreport.write` does.
reading's functions take `Paths`, the clock and the reader (`log_lines_with`; `WatcherView`, `LEDGER_*`, `VERSION_INVALID`);
`read_all`/`watcher_view` keep the `Control` and hand it the Host's reader and clock. document's `check_parts`, shapes,
`encode`, `Fault`, `Checked` and record keys are public; car-adv's document keeps only the envelope. car-adv
`report/evidence.rs` and `report/reading.rs` re-export car-control's. Proof: `-k diffs_advreport -k diffs_advhook -k
OwnReportDiff` 22 tests OK (the six report goldens byte-equal to `advanced/tests/golden/report/*.json`).

### Fixed here

* **Paths::ensure** (`af24da0ef`): `EnsureError::{Config, Os {class, message}}`; the mkdir's error is raised where it happens
  (FileExistsError where `config` is a file, no `logs/` after it). `os_error_class` is car-machine `pyfile`'s (car-policy
  re-exports it). Callers: the harness's `paths.mutate` (the case raises: the reference catches ConfigError alone),
  `ConfigHome` (`ConfigFailure::Raised`), car-adv session (the class), `autocheck::write` (OSError), car-bin's CLI (the text:
  the reference's uncaught OSError there prints a traceback, the CLI `error: <text>`; same code 1 - a seam for P5).
  Diffs: `diffs_leaves_config` "config a file"; `diffs_advcodex_autocheck.test_write` "config is a file" back in.
* **check_rebuild's profile scan** (`70c59c1d1`): `advanced/rust/tools/profile_scan.py`, one allowance - a needle inside the
  literal publisher handle `songyb111-gachon` (UTF-8/UTF-16LE, ASCII case ignored) - and `--self-test` over 10 planted cases
  before any build. A planted `C:\Users\<name>\.cargo` beside the handle is found (rc 1); the handle alone passes.
* **released.package** (`8ba0ca8c7`): the cache keeps every file name the tag's archive put in the folder and checks them
  before answering; a folder no longer whole is said on stderr, kept in `released.REBUILT` and extracted anew.
* **The reference's boot** (`86db745d2`): the embeddable runtime's boot raises the recursion limit by its own frame, so a
  recursion stops at the depth `-c` gives (the MCP batch depth: 995, 994 under the old boot).
* **diffs_classify_vocab** (`76165f604`): the generated-files check runs `gen_policy.py --check` (under the bundled Python
  whose Unicode tables it holds).

### The 7 old-tag reds of Integration 7 (suspect)

Nothing in tests/rustdiff removes a `released-*` folder (every rmtree there is of its own scratch). The suspect: an
age-based cleaner of %TEMP% - Windows Storage Sense is on here (`StoragePolicy` 01=1, 04=1 "temporary files apps are not
using", 2048=0 "when free space is low"), and the disk is full (2.5 GB free of 838 GB during this seat). `tarfile` gives
each extracted file the tag's commit time, so v0.5.0/v0.6.10/v0.6.13 files look weeks old while the reference tag's do not:
exactly the tags that failed. `released.package` now rebuilds what was taken; The full run's result is in the checks below.

### The seams that stay (the other end is a later seat's)

* car-bin `Outside`: `backend`, `app_paired`, `app_running_now`, `official_engine`, `doctor_live_view`, `resource_users`,
  `history`, `run_watcher`, `announce_cancelled`, `open_dashboard`/`open_chat`, `power_stop` - P6's App and host, the
  Restart Manager, car-surface's notifier; `engine_word` (car-codex `compat::cache::engine_word` is here, but it reads the
  backend's engine path, which P6's App hands).
* `codex-auto-resume.exe` = `main_with(&[])`: when the release proofs can run the real core (above). car-adv-bin's `main`
  passes the advanced roles (the courier, the Stop hook's `hook`) to `main_with` then (S7.3d, S6.2a's launcher).
* car-adv `report::reading::WatcherView` (S3.3's `compatio.reader_view` - SystemHost's `compat_view` is the model),
  `report::document::Facts`, `report::seam::{Runtime, HomeMutex}` (S7.2a, S7.3d), `Edges::table_for`/`checked_for`/
  `hook_follow`, `inuse::elsewhere` as `served_elsewhere`, `autocheck::tend` in the tick (S7.2a).

### The wiring done (both ends here)

* car-control `mcp::seam::mcp_view` -> car-codex `compat::report::mcp_view` (`453cb0c42`; `diffs_mcp` 12 OK).
* `build/rust_release.py`: payload/app/mcp/codex-auto-resume-mcp.exe is car-bin's launcher from the standard workspace's
  build unless `--mcp-launcher` names another (`453cb0c42`).
* car-bin `uris` -> car-surface `notice_uris` and `codex_link` (`a4a354d3c`; car-bin names car-surface now, check_groundwork's edge).
* `codex-auto-resume-setup.exe` is S8.2's `setup_main` (it came in with the merge); `core.build_rest` builds advreport and
  advhook too, so `run.py --build` leaves no advanced example stale.
* car-adv's report reads car-control's ownreport (the fold above).

### Checks

`CARGO_BUILD_JOBS=4`, `CARGO_INCREMENTAL=0`; reference v0.6.26 (the final); rustc 1.100.0; HEAD `d51e367bc`.

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0 (every
                   result ok); cargo deny --locked check: advisories, bans, licenses, sources ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked --no-fail-fast rc=0 (car-adv 9 + 1); cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       (after the disk was freed, HEAD 100ab5b39) rc=0: all 10 binaries the
                                                     same with and without advanced/, profile-path scan none, self-test 10
                                                     cases; its own scratch removed at exit (800e89ac4), no tmp.* of its left
each merge's own diffs (run.py --build --reference v0.6.26, bundled 3.14.10 unless said)
  fix9        test_review9_install test_rust_install test_rust_release test_installer_v0623_audit: Ran 79, 1 FAIL
              (test_rust_release ...the_handover: 2 findings, not 1) under load; test_rust_release alone: Ran 24, OK
  unicode16   -k diffs_unicode16 -k ShippedInterpreterDiff -k TextTables -k BidiDiff -k diffs_codex_pure -k
              diffs_classify_vocab: Ran 21, test_edges_shipped OK; VocabParity's generated-files check fixed (above);
              diffs_codex_pure's ENOSPC (disk full) passed again: -k VocabParity -k diffs_codex_pure Ran 12, OK
  mcp         -k diffs_mcp -k diffs_cli -k diffs_legacy: Ran 20, 1 FAIL (FramingDiff, the boot's frame: fixed above);
              -k FramingDiff Ran 6 OK; after the seam wiring -k diffs_mcp Ran 12 OK; after uris -k diffs_cli -k diffs_legacy
              Ran 8 OK
  adv73c+fold -k diffs_advreport -k diffs_advhook -k OwnReportDiff: Ran 22, OK
  adv72d      rediff_adv72d.py --reference v0.6.26: Ran 13 OK; rediff_adv72c.py --reference v0.6.26: Ran 17 OK
  ensure      -k diffs_leaves_config -k diffs_advcodex_autocheck: Ran 8 OK; mutation (the mkdir's error swallowed again):
              OwnedDiff.test_what_is_owned and AutocheckDiff.test_write both FAIL
Python      test_rust_release test_downgrade test_schema_v4 test_defaults_golden (after released.py, the launcher): Ran 81, OK
```

The long checks (detached, after the reboot; HEAD 100ab5b39..12fd020a3):

```
run.py --build --reference v0.6.26 --reference-python bundled -v   Ran 360 in 8,595 s: 10 FAIL, 1 expected failure, no skip.
    REFERENCE-314 Finding A (json depth, the owner's decision): appserver_lines.test_next_message, codex_homes
    test_cloud_tasks_and_global_state / test_rollout_first_lines, leaves_codex.test_root_version_discovery,
    leaves_domain.test_registry_format, settings_files.test_settings_files (case 232), bridge_commands
    DamagedDiff.test_failure_seen_files [nested 4096]. The final's fresh home, not ported to car-codex yet (both Pythons):
    compat_io ProbesDiff.test_source_and_api_checks (history_schema NOT_APPLICABLE vs UNAVAILABLE), codex_homes
    test_schema_variants (HistoryNotYet vs SourceError). settings_plug.test_generated_files_are_the_tags: fixed (d77a66647).
run.py --reference v0.6.26 --reference-python system -v            Ran 360 in 8,513 s: 7 FAIL, 1 expected failure. The five
    Unicode 16 tables by design (classify_vocab/leaves_machine TextTables, codex_pure labels, BidiDiff, review8 EdgeDiff) and
    the two fresh-home ones above.
the 15 frozen modules (test_parts --worker; CODEX_AR_CORE=rust)    456 pass on both, 0 differ (Python 371 s, Rust 399 s)
Python guards (+ test_review9_install)                              Ran 173: 1 FAIL, test_repo_hygiene's UUID rule on
    diffs_advcodex_tokens.py: fixed (12fd020a3); then test_repo_hygiene 7 OK, -k TokensDiff -k PlugDiff 7 OK
```

The 7 old-tag diffs of Integration 7 (diffs_store x5, diffs_store_values x2 and diffs_settings_files' old tags) pass in both
full runs: no ModuleNotFoundError, and `released.package` never had to rebuild a cache (no `released:` line). With the disk
free, nothing took an old tag's files during the run; the run before the reboot, on a full disk, was where it had
happened. Cause confirmed by the rule set for it (the 7 pass in the full run): an age-based %TEMP% cleaner on a full disk.

## P6 step 0: the host contracts (seat S6.2, branch `car-v0627-p6abi`, 2026-11-26)

Cut from `car-v0627-rust` `ac3a8d612` (Integration 7). `outputs/plans/v0627-rust/P6-DESIGN.md` 1.2 (the exports), 1.3 (panics), 1.5
(the closed tables) and 4.1 step 0, under the owner's answers Q1-Q10 (section 6). Nothing is ported: these are the shapes S6.1,
S6.2a, S6.2b and S6.3 build on. No window was shown, no shipped window source changed (`gui/window.sources` and `build/make_gui.ps1`
are as they were), nothing was pushed.

### What is here

| Path | What |
|---|---|
| `rust/crates/car-host/src/abi.rs` | `ABI = 1`; `EXPORTS` (the six, in 1.2's order); `Factory = fn() -> Guarded`; the event table `EventKind` (8: `surfaces snapshot strings settings notice demo close ended`, each with its `fields()`), `Event` (+ `Surfaces`), `Event::to_json`; the action table `ActionKind` (14: `tray_started closed cards_attached cards_detached toggle stop open_dashboard open_chat notice_action notice_complete popup disarm_power mark_seen failure_seen`, each with its `fields()`), `POPUP_CALLS` (= `CONTROL_CALLS`, ui/popup/model.py:34-35), `Action::parse`; `Refusal` (`bad_request unknown_action not_ported not_started panic`); the six bodies over the empty core; `queue(Event)`, `panics()`, `is_live(ptr)`; and `export_core!($factory)`, the macro that makes the six `#[unsafe(no_mangle)] extern "C"` functions |
| `rust/crates/car-host/src/lib.rs` | `export_core!(car_policy::plug::Guarded::null)` under the feature `exports` (default on) |
| `gui/HostCore.cs` | the six `DllImport`s (`Cdecl`, `ExactSpelling = true`, `EntryPoint` named) and the wrappers `Start`, `Stop`, `Bridge`, `NextEvent`, `PostAction`; `Take` copies a reply out with `Marshal.Copy` and calls `car_free` in a `finally` |
| `gui/ISurfaces.cs` | `HostEvents` and `HostActions` (+ `PopupCalls`): the tables' words as constants and `All` arrays in the tables' order; `IHostActions.Post(action, fields)` (a worker thread's way back); `SurfacesEvent` (`Icon Strings Settings Edition Demo`, + `Actions`, set by the pump); `ISurfaces`: `Start(SurfacesEvent)`, `Snapshot`, `Strings`, `Settings`, `Notice`, `Demo`, `Close` (one per event but `ended`, which is the pump's) |
| `rust/crates/car-host/tests/abi_exports.rs` | the export-table test (the built DLL's PE export directory, never loaded) and the six's fn types pinned |
| `tests/test_host_contract.py` | the `DllImport` test, the names test, the compile check (standard lane; needs the in-box csc) |

Beside them: car-host depends on car-machine (the JSON writer and reader, D5/D12) and car-policy (`Guarded`), so check_groundwork's
`EXPECTED` row says so and both locks list the two; check_groundwork's D3 rule gains `EXPORTERS = {"car-host"}`, where an
`extern "C" fn` **definition** (an export of the DLL) passes and an `extern "C" { ... }` import block still fails;
`advanced/rust/crates/car-adv-host/Cargo.toml` takes car-host with `default-features = false` (inert today: its `lib.rs` is empty);
`tests/guiscan.py` lists the two C# files as `HOST`, inside `SEPARATE`, so `test_guiscan` knows them.

### The contracts

**These change only by the main session's word, and the change goes to every P6 seat** (P6-DESIGN 4.1).

* **The six** (`abi.rs`, `export_core!`; `gui/HostCore.cs`):

  | Rust (`extern "C"`) | C# | Empty core |
  |---|---|---|
  | `car_start(*const u8, usize, *mut usize) -> *mut u8` | `IntPtr car_start(byte[], UIntPtr, out UIntPtr)` | `{"abi": 1, "ok": false, "error": "bad_request"}` unless the request is an object whose `argv` is a list of texts; then `{"abi": 1, "ok": false, "error": "not_ported"}`. S6.1/S6.2b: `{"abi": 1, "ok": true}` |
  | `car_stop() -> i32` | `int car_stop()` | 0 (nothing to stop is stopped at once); -1 after a caught panic |
  | `car_bridge(*const u8, usize, *mut usize) -> *mut u8` | `IntPtr car_bridge(byte[], UIntPtr, out UIntPtr)` | `bad_request` for bytes it cannot read, else `{"ok": false, "error": "not_started"}`. S6.2b: the bytes `bridge serve` writes (car-control `bridge`) |
  | `car_next_event(u32, *mut usize) -> *mut u8` | `IntPtr car_next_event(uint, out UIntPtr)` | NULL with `*out_len = 0` once `timeout_ms` passed (it waits on a condvar, it does not spin); an event queued with `abi::queue` comes out at once as `{"kind": ..., <fields>}` |
  | `car_post_action(*const u8, usize, *mut usize) -> *mut u8` | `IntPtr car_post_action(byte[], UIntPtr, out UIntPtr)` | `bad_request` (not an object with a text `action`), `unknown_action` (a name outside the 14, or `popup` whose `call` is not a text in `POPUP_CALLS`), else `not_started` |
  | `car_free(*mut u8, usize)` | `void car_free(IntPtr, UIntPtr)` | frees a reply it handed out with that length, once; NULL, a pointer it never made, a wrong length or a second free frees nothing |

* **The wire.** UTF-8 JSON both ways; replies are car-machine's `Options::wire()` (`json.dumps(..., ensure_ascii=False)`: `", "` and
  `": "`), keys in the order the tables write them. A request field left out reads as null. Field types are not checked at the
  boundary: each action reads its fields as the reference reads them (`bool(paused)`), so the boundary is never stricter.
* **One allocator.** Every reply is a leaked `Box<[u8]>` whose address and length the core records; `car_free` takes back only a
  recorded pair. A null `out_len` makes the call do nothing and answer NULL (a reply the host cannot measure, it cannot free).
* **Panics (D15).** Every export body runs inside `catch_unwind` (car-machine's `caught::catch`); a caught panic answers
  `{"ok": false, "error": "panic"}` (`car_start`'s with `"abi": 1` first, `car_stop` -1, `car_free` nothing) and counts in
  `abi::panics()`. The exports are `extern "C"`, so anything that escapes aborts rather than unwinding into the CLR. The tests trip
  a panic inside each real body through a `#[cfg(test)]` thread-local (`abi::trip`): nothing of it is in a built DLL.
* **One generic entry (Q3; P7-DESIGN 2.4).** `export_core!(factory)` is the whole difference between the editions' DLLs. The
  standard build is car-host's own (`exports` on). The advanced build is car-adv-host: car-host with `default-features = false`,
  and `car_host_lib::export_core!(<its plug factory>)` in its `lib.rs` (S6.2b with S7.3d). Until that line is written the advanced
  `car_core.dll` exports nothing; the two editions' six never meet in one DLL, which a duplicate symbol would refuse anyway.

### How the two C# files are compiled without changing the window

They are on no compile list the product reads. `tests/test_host_contract.py` `BuildTests` compiles them alone with the in-box csc
(`-target:library -platform:x64 -warnaserror`, into a temporary folder; nothing is run or loaded) and checks they are neither on
`gui/window.sources` nor named in `build/make_gui.ps1`. When S6.2b writes `gui/host.sources` (`[host]`), it takes them there, and in
the same commit turns `BuildTests.test_the_shipped_window_does_not_compile_them` into "on host.sources, not on window.sources"
and moves `guiscan.HOST` from `SEPARATE` to the second list guiscan learns (P6-DESIGN 1.7).

### Proofs

* **car-host's unit tests** (`abi.rs`, 8): each export's reply on the empty core, byte for byte (`start`: `not_ported`, nine
  `bad_request` shapes, bytes that are not UTF-8, a null pointer with a length; `stop` 0; `bridge` `not_started`/`bad_request`;
  `next_event` NULL after its timeout and at 0, and a queued `ended` that wakes a pull already waiting); every one of the 14 actions
  and the ten popup calls `not_started`, six names outside the table `unknown_action`, five shapes `bad_request`; `car_free` once
  (a wrong length, an inner pointer, NULL and a second free leave or free nothing); a panic tripped inside each of the six real
  bodies is answered as above, counted, and the next call runs.
* **`tests/abi_exports.rs`** (2): the built DLL's export directory is exactly the six, no ordinal-only and no forwarded export, its
  DLL name `car_core.dll`; and the six are pinned to their fn types and called through the rlib. Run on the debug DLL and, with
  `CAR_CORE_DLL`, on the release one (`lto = "fat"`, stripped): the same six. `CAR_CORE_DLL` naming a missing file fails the test.
* **`tests/test_host_contract.py`** (11; the compile test needs the in-box csc).
* **Mutation checks** (each alone, restored after): a seventh export `car_send` in car-host -> `abi_exports` fails (the table lists
  it); `car_next_event(int ...)` in HostCore.cs -> `test_host_contract` 2 fails (the type, and csc); `CallingConvention.StdCall` on
  the imports -> 6 fails; `"disarm_power"` renamed in ISurfaces.cs -> fails; an eleventh popup call -> fails; an
  `unsafe extern "C" { fn GetTickCount() -> u32; }` block in car-host -> check_groundwork's D3 FAIL.
* **The window unchanged**: `build/make_gui.ps1` run on `git archive` trees of `ac3a8d612` and of this branch's head, both
  editions, into scratch folders: every `.exe` byte-identical (standard `CodexAutoResumeSettings.exe` `ec1ae342...`,
  `codex-auto-resume-mcp.exe` `382bbb9c...`; advanced `CodexAutoResumeSettings.exe` `101f257d...`).
* **The Python guards** (standard lane, `wait_quiet.sh`, one run): `test_host_contract test_guiscan test_consumer_fields
  test_gui_chrome_sources test_gui_scrollbar_no_light test_l10n test_managed test_release_list_bound test_rtl_values_kept
  test_repo_hygiene test_privacy_claims test_privacy_bare_hosts test_srcscan test_structural_invariants test_rust_release
  test_rust_install`, and the source-scan classes of the window modules that glob `gui/*.cs` (`test_gui_dialog_icons.DialogIconTests`,
  `test_gui_v0624_dialog_corner.SourceTests`, `test_gui_v0624_setup_corner.SourceTests`, `test_gui_v065_controls.SourceRuleTests`,
  `test_gui_window_corner.SwitchTests.test_every_hook_is_behind_the_corner_the_switch_makes`, `test_setup_words.EnglishLookTests
  .test_the_installer_and_the_bootstrap_ask_for_english_and_nothing_else_does`, `test_chosen_runtime.StandardEditionTests`,
  `test_no_console_windows.WindowStartTests`, `test_remote_debug_off.StaticTests`): Ran 264, one red, `test_privacy_bare_hosts`
  (the comments' `abi.rs` read as a host; reworded, `93657f2ad`), then `test_privacy_bare_hosts test_host_contract` Ran 15 OK;
  8 skips, none in `test_host_contract`. No module that opens a window was run (this step shows none); the window's own sources
  did not change, so the GUI set's compiled windows are the ones `ac3a8d612` had (the make_gui comparison above).

### What step 0 did not do

* **Risk 3 of P6-DESIGN 4.2** (the CLR's private commit and start time, "measured in step 0 on the stub core") needs a host
  process that loads the DLL, and the host's `Main` is S6.2b's (`gui/HostMain.cs`). Not measured: it moves to S6.2b's first
  build, against this empty core (which answers `not_ported`, so the host exits 1 at once; a measuring host waits instead).
* No diff and no re-diff command: the six are a new wire with no reference to compare (D12 keeps the bridge's, which `car_bridge`
  will carry unchanged). The one reference value in the tables, `POPUP_CALLS`, is held to the tree's `CONTROL_CALLS` by
  `test_host_contract` (the v0.6.26 final's: nothing in `ui/popup/model.py`'s list moved after beta.2).
* Nothing for AUDIT-v0628.md: no reference behaviour was kept or changed.

### For the next seats

* **S6.1 (car-watcher)**: the watcher is built at `car_start` with `factory()` (`abi::start` holds the place) and speaks through
  `abi::queue(Event::...)`, the table's fields in order; `ended` is queued last, always. Nothing else of `abi.rs` is yours: a new
  event, field or refusal word goes to the main session first.
* **S6.2b (the host shell)**: fills the bodies (`start` -> `{"abi": 1, "ok": true}`, a second start's answer, `stop` -> the
  in-process `StopEvent`, `bridge` -> car-control's `bridge` answer, actions -> car-surface's seam traits over car-control's
  `Control`, each action name one trait method with a test listing both sides, P6-DESIGN 1.5); records every caught panic as
  `App._record_failure` does once there is a home; writes `HostMain.cs` (the `LoadLibraryExW` by full path, the `abi` check) and
  `HostPump.cs` (`HostCore.NextEvent(250)`, a `ConcurrentQueue`, one `PostMessage` per event, a reply without `kind` is a failed
  pull); `gui/host.sources` with HostCore.cs and ISurfaces.cs in `[host]` (and `test_host_contract.BuildTests` and `guiscan`
  moved with them, as above); 1.3's test-only panic feature and the check that the release DLL has none; runs `abi_exports` with
  `CAR_CORE_DLL` on both editions' release DLLs.
* **S6.3 (the designer)**: implements `ISurfaces`; posts through `SurfacesEvent.Actions` (`IHostActions.Post`) on worker threads,
  never the UI thread; reads every event's values as `Json.Parse` gives them (`Dictionary<string, object>`). The names to use are
  `HostEvents`/`HostActions`, never a literal.
* **car-adv-host (S6.2b with S7.3d)**: `car_host_lib::export_core!(<the advanced plug factory, fn() -> Guarded>)` in its
  `lib.rs`; car-host is already taken without its `exports` feature. Then `abi_exports` with `CAR_CORE_DLL` on the advanced DLL.

### Checks (`CARGO_BUILD_JOBS=4`, `. tools/rustflags.sh` first; rustc 1.100.0; code at `93657f2ad`)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0 (car-host 8 + abi_exports 2);
                   cargo deny --locked check rc=0
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0; cargo deny rc=0
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh            rc=0, all 8 binaries the same with and without advanced/ (car_core.dll cfb2d29a...);
                                                     profile-path scan: none
cargo build --locked --release -p car-host, then CAR_CORE_DLL=<target/release/car_core.dll> cargo test -p car-host --test abi_exports
                                                     2 passed: the release DLL exports the same six
```

## Follow Python 3.14.10: the JSON nesting depth, the drive-like realpath tail, the generators (seat follow314, branch `car-v0627-follow314`, 2026-11-26)

Base: Integration 8's tip `800e89ac4`; reference v0.6.26 on the bundled embeddable 3.14.10 (`--reference-python bundled`). The owner decided on 2026-11-26 (DECISIONS.md, "P7 answers and the JSON nesting depth") that Rust follows 3.14.10's main-thread nesting limits per container kind with an iterative parser; REFERENCE-314.md findings A and C are closed, and D (the advanced diffs and the generators on `sys.executable`) is routed.

**A. `json.loads` / `json.dumps` nesting depth.** Measured by this seat on the bundled `python.exe` (25 processes, main thread; `json/depth.rs` carries the table): `json.loads` lists 16,917 (16,909-16,920), objects 14,314 (14,308-14,317), alternating 15,507; `json.dumps` through the C encoder (`indent`, `sort_keys`, `separators` change nothing: 3.14's C encoder takes them) lists 15,506, dicts 9,304, alternating 11,630. Every shape fits one rule: a level costs 1 / (the levels a document of its kind alone reaches) of one stack budget, a mixed document adds its levels up (the alternating limit is the harmonic mean of the two single ones), refused past the whole; ten other patterns (`LLO`, `LOO`, `LLLLO`, ...) land within three levels of the reference. `car-machine::json::depth` holds it as integers (`Budget`: a list costs `OBJECT_LEVELS` units, an object `LIST_LEVELS`, the whole is their product) and the four constants `LOADS_LIST_LEVELS`, `LOADS_OBJECT_LEVELS`, `DUMPS_LIST_LEVELS`, `DUMPS_OBJECT_LEVELS` (re-exported from `compat` and `json`; `MAX_NESTING` and `MAX_DEPTH` are gone). `compat.decode`'s hooks are Python calls made from C at the deepest point and cost room there (measured against the same document without hooks): an object's `object_pairs_hook` 13 object levels (`{}` too), `parse_float` 16 list levels, `parse_constant` 33 (3 without a hook: the plain decoder's table); a document within that room of the limit is `too_deep` in `decode` and taken by `loads`. The empty `[]` and `{}` count as a level in both directions (the C code checks before it looks inside; the old writer returned early). `compat/decode.rs` was iterative already; `json/write.rs` is now (an explicit stack of frames, `Frame::Array` / `Frame::Object`).
  *The part nobody asked for:* the compiler's drop glue for a `Value` recurses (about 150 bytes a level in release): a 17,000-level value needs about 3 MB to drop and `json_edges`' own test aborted at it (measured: 2 MB fails, 4 MB holds). A `Drop` impl on `Value` would end every by-value pattern and every `&Value::Null` of both workspaces (about 200 sites in `rust/`, 650 uses of the variants in car-adv), so the threads that hold a parsed document run on a stack with the room: `car_machine::stack::{DEEP_STACK_BYTES (64 MiB), run_deep, spawn_deep}`, used by `car_bin::main_with`, `core_main`, `setup_main`, the mains of car-harness, car-core-stub, car-core-world and car-fake-codex, car-codex's app-server reader and car-adv's session reader. **A thread that reads documents is made with `spawn_deep` (or its work runs inside `run_deep`); car-host's calls run on the host's thread.**
  *Diffs* (`tests/rustdiff/diffs_nesting_314.py`, two classes): `NestingDiff` 2,216 cases equal to the reference (loads, raw_decode, decode, dumps with plain / indent 0 / indent 2 / sort_keys / compact; six patterns; leaves `0`, empty, float, NaN, infinite; 1 to 40,000 levels and 100 and 48 each side of each limit, decode's by the hook room); `BoundaryDiff` bisects the reference and Rust and holds them within 40 levels (the run-to-run drift is about 20, and the harness's boot puts the reference about 12 lower than a plain process), and holds Rust alone at limit-1, limit and limit+1 for each constant (including an empty innermost dumps container and decode's three hooks). Replies carry `{"$nested": depth}` past 64 levels (`leaves.shallow`, both sides): the runner's own `json.loads` may be 3.13's (2,998 levels) and the old 3,000-5,000-level corpora now answer deep values (appserverdiff's `plain` recursed in the reference's script too). The per-case Rust ops are `car-harness/src/leaves/nesting.rs` (`json.loads`, `json.decode`, `json.raw_decode`, `json.dumps`, `json.bisect`, `json.limits`).

**C. `os.path.realpath` of a drive-like tail.** Nothing left to port: car-config's `winpath` is `pub use car_machine::winpath::*` (review 4, S2), whose `glue` is 3.14.10's local `join` (fix4). `tests/rustdiff/diffs_paths_314.py` is the committed scratch case: 15 homes (`a:b`, `h/a:b`, `h/a:b/c`, `a:`, `h/x:y:z`, `h/a:b:$DATA`, `h/../a:b`, `h/c:/x`, `CON`, `aux.txt`, `nul.x`, a trailing dot and space, `ADS:stream`, `a:b/..`, `z:\q\w`) through `config.Paths`, every name equal to the tag's on the bundled runtime. Under `--reference-python system` (3.13.15) the eight that name a drive-like tail differ BY DESIGN (3.13 joins with `ntpath.join`).

**D. The reference's Python reaches the advanced diffs and the generators.** `refpython.script_command(path, ...)` and `reference.script_command` (a script file under the embeddable runtime: the boot, then `runpy`) beside `command`; `advref.run` / `popen`, `diffs_store.reference_process`, `diffs_engine`, `cliworld`, `gen_cli`, `gen_vocab` and `gen_logbook` start the reference through them, no longer `sys.executable`. `productpy.py` no longer unpacks a runtime of its own: it asks `refpython` for `bundled` (one unpack per run) and stays pinned there whatever `--reference-python` says (a Unicode table is the product's Python's). `gen_advcodex.py` (car-adv's `str.isalpha` table, `alpha_gen.rs`) was the sixth Unicode table nobody regenerated - it said 3.13.15 / 15.1.0 - and now runs under the bundled runtime like `gen_tables`, `gen_codex` and `gen_policy` (regenerated: 22 lines); `parsers_gen.rs` differs by its header's Python version only (`gen_cli` under 3.14.10 gives the same tables). `gen_advcodex`, `gen_tables`, `gen_codex`, `gen_policy --ref v0.6.26`, `gen_advstore`, `gen_advpolicy`, `gen_brand`, `gen_catalogs`, `gen_logbook`, `gen_vocab`, `gen_cli --reference v0.6.26` all `--check` clean under bundled. New Python tests: `tests/test_rustdiff_script_command.py` (script_command, productpy through refpython, no `sys.executable` left in the routed files).

**Under `--reference-python system` (3.13.15) these differ BY DESIGN:** `diffs_nesting_314` (both classes fail at once with a message naming the version), `diffs_paths_314` (the eight drive-like tails), `diffs_unicode16`'s generator checks stay pinned to the bundled runtime and pass; everything else reads the reference only where 3.13 and 3.14 agree.

**Re-diff for the final:** `python -X utf8 tests/rustdiff/rediff_follow314.py --reference v0.6.26` (lists `compat/model.py` and `config.py` if they changed since v0.6.26, runs every generator's `--check` and `-k nesting_314 -k paths_314` on the bundled Python).

**Seams and what later seats need.** (1) A new thread that reads files, Codex's lines or a caller's text: `car_machine::stack::spawn_deep`. (2) `compat::decode` and `compat::loads` are the two readers; a hook-bearing reader of another module (l10n's `_no_duplicates`, the hook handler's `_keep_allowed`, fleet's `parse_constant`) takes the same budget but not `decode`'s hook room unless it asks `Budget::room_for_*` itself. (3) The writer's limit is the C encoder's; `json.dump` to a stream is the pure-Python encoder's 994-995 levels (AUDIT-v0628), nothing the product writes nests past ten. (4) Python threads stop about 19 levels sooner than the main thread (AUDIT-v0628). (5) No `expect`/`unwrap`/`panic!`, and no `#[track_caller]` std call (`thread::scope`), in a function of a standard crate that a stub binary retains: its panic location is an absolute source path, and a crate outside the advanced workspace root (`rust/crates/...`, built by `advanced/rust`) is not remapped, so the edition rebuild check's profile-path scan finds the builder's folder and user name (it found `run_deep`'s `expect` and then its `thread::scope`; `run_deep` is now `spawn_deep` and a join, its body `'static`, so `main_with` and `setup_main` hand it owned copies of their arguments).

**Mutation checks** (a fast no-LTO build, the diffs run, restored): seven rules broken one at a time, each failed by its diff, all passed restored (a fast no-LTO build of car-harness, `CODEX_AR_HARNESS_EXE`; `scratchpad/car-v0627-follow314-mutate.py`): (1) `LOADS_LIST_LEVELS` 16,917 -> 2,998, 3.13's: BoundaryDiff both tests and NestingDiff fail; (2) `DUMPS_OBJECT_LEVELS` 9,304 -> 9,204: the same three; (3) an object costs what a list costs (`enter_object` spends `object_levels`): the same three; (4) the writer's closing line break one level too deep: NestingDiff (indent 0 and 2 dumps); (5) `decode`'s object hook needs no room (13 -> 0 object levels): `test_rust_alone_at_limit_minus_one_limit_and_limit_plus_one` (the reference cannot see 13 levels, Rust alone holds them); (6) `sort_keys` inverted: it first SURVIVED (the nesting diffs' dicts held one key), so each nested dict now holds `b` then `a` and the mutation fails NestingDiff; (7) car-machine's `glue` back to `ntpath.join`, 3.13's: `diffs_paths_314` `test_fifteen_homes` fails.

**Gates** (code HEAD 0f0ea56b6, the commit after it is this text; `CARGO_BUILD_JOBS=2` for the lints, the tests in a target of their own): `cargo fmt --check` rc=0; `cargo clippy --locked --all-targets -- -D warnings` rc=0; `cargo test --locked --no-fail-fast` rc=0 (every result ok; car-machine's new `nesting_314` 7 tests, `stack` 2, `json_edges` 12); `cargo deny --locked check`: advisories, bans, licenses, sources ok, in `rust/` and in `advanced/rust/`; `python -X utf8 rust/tools/check_groundwork.py`: OK (17 standard crates, 3 advanced crates); `check_rebuild.sh HEAD`: rc=0 at `0f0ea56b6`: every .exe and .dll byte for byte the same with and without `advanced/`, profile-path scan none (it found the builder's folder and user name twice before: `run_deep`'s `expect`, then its `thread::scope`, see seam 5). No new dependency. Python: `test_rustdiff_script_command test_rustdiff_reference_python test_rust_power_guard`: Ran 26, OK.

**Diffs** (`run.py --build --reference v0.6.26 --reference-python bundled -v`, the whole harness, 364 tests): 364 tests in 8,983 s on the bundled 3.14.10: 359 OK, 1 expected failure, **4 FAIL, none of them findings A or C**: (a) `diffs_advcodex_session.test_sessions` - the run used a shared `CARGO_TARGET_DIR` and the test reads `car-fake-codex` from `rust/target` (`CODEX_AR_FAKE_CODEX`): OK on rerun with the variable set; (b) `diffs_settings_plug.test_generated_files_are_the_tags` - it regenerated gen_policy's tables in the runner's own Python (3.13.15) and compared them with the files the bundled 3.14.10 made; now the generator's `--check` through `reference.script_command`: OK on rerun, with `diffs_unicode16`, `diffs_classify_vocab`, `diffs_advstore.GeneratedDiff`; (c) `diffs_codex_compat_io.ProbesDiff.test_source_and_api_checks` and (d) `diffs_codex_homes.HomeDiff.test_schema_variants` (case 24, `schema-only-state`) - the reference answers `HistoryNotYet` / `NOT_APPLICABLE` where car-codex says `SourceError` / `UNAVAILABLE`: FINAL-DELTA #1-#5, the car-codex catch-up to the final that REVIEW-int5b recorded as red; (d) fails under `--reference-python system` too, so it is no 3.13/3.14 gap. The REFERENCE-314 table's six tests (`test_next_message`, `test_cloud_tasks_and_global_state`, `test_rollout_first_lines`, `test_root_version_discovery`, `test_registry_format`, `test_settings_files`) and the C home cases pass, and so do both new files (NestingDiff 2,216 cases, BoundaryDiff, DriveLikeTails)

## car-watcher (seat S6.1, branch `car-v0627-s61`, 2026-11-26)

Cut from `car-v0627-p6abi` `b1761926b` (Integration 7 and P6 step 0). P6-DESIGN 2.1 and 4.1 row 1a, under the owner's answers Q1-Q10;
ported from the v0.6.26 final. No window, no tray icon, no real timer, no named object of the product's: every test and diff runs
the watcher over a world of its own; the one end-to-end test (`tests/watcher_api.rs`) points every home variable at a scratch
folder first, so the mutex, the stop and wake events and the Codex home lock are named from that folder.

### What is ported, and where

| Python | car-watcher | Note |
|---|---|---|
| `runtime/loop.py` | `watchloop` | `run`, the double look, the three named objects and the home lock, `_loop`, every per-tick part, `_self_check`, `_layout_said`, `_unknown_errors`, `_between_ticks`, `_poll_interval`, `_open_for_watcher` - over the [`World`] trait (everything `App` hands the loop). D15: each `try:` span is `fail::guarded`, so a panic costs its tick; StateFromNewerVersion and RecordSchemaMismatch stay typed (`Failed::newer`) |
| `runtime/app.py` | `app` (`App`, the real `World`), `events`, `api` | the log (car-config `Logbook`), `errors.log` with its rotation, the settings read and refreshed under the administrator's keys, the named objects (car-platform `sync`, `homelock`), the store, health, waking and the power action with this PC's ports, the failure baseline, the sweep, the self-check and layout files, the icon's events. The engine and what builds it (discovery, the backend, the Compatibility Registry's evaluator, the layout watch, the notifier) come in through `app::EngineMaker` - see "Seams" |
| `runtime/homes.py` | `homes` | over `HomesApp`; `World: HomesApp` |
| `runtime/health.py`, `waking.py`, `afterwork.py`, `toasts.py`, `plugnotices.py` | `health`, `waking`, `afterwork`, `toasts`, `plugnotices` | each over a port trait (`OwnProcess`, `PowerPort`, `PowerControl` + `Powerdown` + `Activity`), with this PC's implementation beside it (car-platform) and `car_control::Control` as the power action's control layer |
| `setaside.py` | `setaside` | its `rmtree` walks as CPython 3.14's does (links and junctions removed as themselves, a read-only file refused as DeleteFileW refuses it - std's `remove_file` would delete it) |
| `checkup.py` | `checkup` | the words and verdicts: `lines` (all 22 languages), `_summary`, `_usage`, `_ago`, `_within`, `_reason`, `%g` |
| `rescan.py` | `rescan` | `proofs`, `persons`, `judge` over `RescanEngine` (the engine's and its source's calls) |
| `scripts/watcher_launcher.py` | `launcher` | the phases, the relaunch mark, AFTER_STOP, P13 (SUPERVISE, RESTART, held, asked again), relaunching once, the plugin root's three-way order (Q6 (a)), launcher.log (200 lines) and errors.log; D8's retired parts are named in AUDIT-v0628 |
| - | `api::Watcher` | `start(request, factory, project_root)` (the launcher on its own thread, the loop over `App` in this process, `ended` last), `stop`, `next_event`, `post_action`, `bridge` - what car-host's exports drive (S6.2b) |
| - | `fail`, `clock` | `Failed {class, message}` with `From` for car-store's, car-control's and the host's errors; the wall, monotonic and log clocks |

### The seams (for the next seats)

* **`app::EngineMaker`** (`engine`, `engine_moved`, `compatibility_tick`, `engine_state`, `codex_exe`, `app_identity`, `recovery_facts`,
  `home_backend`, `home_engine`): what `App.backend()`, `App.engine()`, `_compatibility_tick`, `_layout_look`, `engine_moved` and
  `_recovery_facts` are. The standard maker is `NotJoined`: every build refused, typed `EngineNotJoined`, so the loop logs
  "initialising Codex adapter failed (EngineNotJoined)" and sends nothing. **Not joined here**: car-engine's `Engine::new(store, source,
  Transport, Given)` with the harness's `EngineStore` (car-engine `Store` over car-store), an `OnceWords` over car-control's, `Given::local`
  car-platform's `Crt`, `os` car-control's `PlatformOs` (Integration 6's notes), car-config's `discover_codex_exe` with car-codex's
  `Backend` checks and `app_engines`, car-codex's `Evaluator::tick` and `layout::Watch`. Each of those is ported and diffed; the join is the
  integration's (with S6.2b), and `Watcher::start_with(.., maker)` takes it.
* **The notifier.** `App::watcher_notice` and the engine's notifications go to `events` as `notice` events; the toast (car-surface
  `notifier::deliver`'s toast route) where the host has no card is S6.2b's with car-surface (the host's notifier seam).
* **`Host::checkup`, `checkup_for_bundle`, `rescan_judge`** (car-control): `checkup::lines`/`_summary`/`_usage` and `rescan::judge` are
  ready; `_conversations` (car-codex `passed_over`, the engine's `not_taken_up`/`detection_since`) and `judge_for` (an engine with no
  backend and no store per home) need the engine join above. The `detection-check` golden then runs whole.
* **`api::Watcher::post_action`** answers `tray_started`, `closed`, `cards_attached`, `cards_detached`, `stop`, `toggle` (`set_enabled(bool(paused))`,
  as the reference passes it) and `disarm_power` (actor `tray`); `open_dashboard`, `open_chat`, `notice_action`, `notice_complete`, `popup`,
  `mark_seen`, `failure_seen` answer `{"ok": false, "error": "not_ported"}` until S6.2b maps them onto car-surface's seam traits.
* **Control's plug.** `car_control::Control::new` takes a `Guarded` by value, so the watcher makes one per Control from the edition's
  `fn() -> Guarded` factory; the reference hands every part the same plug object. The standard edition's NULL is the same either way;
  an advanced plug with state wants `Control` to take a shared `Arc<Guarded>` (car-control's, the main session's word).
* **Windows' preferred languages** are not in car-platform yet: the icon's `strings` read the environment's language (as the bridge's
  `SystemHost` does).

### The diffs (`tests/rustdiff/diffs_watcher_*.py`, README "car-watcher"; harness `src/watcher.rs`, `watcher/{batch,launch,check}.rs`)

Debug harness, `run.py --reference v0.6.26 -k diffs_watcher -v`: 6 tests, OK - the loop's 30 scenarios, the launcher's 31, the sweep's 13
fixture homes, 4 plug-notice sequences, 15 power-action sequences, and 1,270 checkup and rescan cases (the check's lines in all 22
languages over 264 results, Rescan's judge over 62 scripted cases). The release run is in the checks below.

Mutation checks (each rule broken alone in car-watcher, the debug harness rebuilt, its diff run, restored; the tree is the committed one):
`MUTEX_RETRY_SECONDS` 0.3, `WAKE_COALESCE_SECONDS` 6.0, the open's backoff tripled, a mid-tick RecordSchemaMismatch read as a failure
(`WatchLoopDiff` each); the install journal not looked for (`SweepDiff`); `SHOWN_KEYS` 65 (`PlugNoticesDiff`); the countdown's look every
16 s (`AfterWorkDiff`: it first survived - every sequence waited on a fresh state's pause - and is what the stores turned on and the two
countdowns run to their end were added for); `LAUNCH_LOG_LINES` 199 (`LauncherDiff`); FIRST's first two swapped and the marker-free
reason dropped (`CheckRescanDiff`): all ten failed their diff.

### The re-diff

`python -X utf8 tests/rustdiff/rediff_watcher.py --reference v0.6.26` lists any ported or read file that changed after v0.6.26 and reruns
every `diffs_watcher_*` diff against the tag.

### Checks (`CARGO_BUILD_JOBS=4`; reference v0.6.26 on the bundled 3.14.10, rustc 1.100.0)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0
                   (car-watcher 3 + watcher_api 1); cargo deny --locked check rc=0
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked rc=0; cargo deny rc=0
python -X utf8 rust/tools/check_groundwork.py        rc=0 (car-harness takes car-watcher: EXPECTED's row says so)
bash advanced/rust/tools/check_rebuild.sh            rc=0, all 8 binaries the same with and without advanced/ (car_core.dll
                                                     cfb2d29a..., unchanged: car-host does not call car-watcher yet);
                                                     profile-path scan: none
python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 -k diffs_watcher -v
                                                     release harness: Ran 6 tests in 32 s, OK
the 15 frozen modules (test_parts --worker tests, Python lane, then CODEX_AR_CORE=rust)
                                                     456 test ids, 456 pass on both, 0 differ (Python 545 s, Rust 591 s)
```

## Integration 9 (branch `car-v0627-rust`, 2026-11-27)

Three branches merged with `git merge --no-ff`, in this order, both sides of every conflict kept; then the plug wiring and
the two guard fixes, each its own commit.

| Merge | Branch | What came in |
|---|---|---|
| `fd998ad94` | car-v0627-cifix `b5369c05d` | car-v0627-ci (`800e89ac4`), the P6 step 0 host contracts (car-v0627-p6abi: car-host's `abi.rs`, `gui/HostCore.cs`, `gui/ISurfaces.cs`, `test_host_contract`), `0a7ba6590` and the CI fixes `3ec506531` `bd311cb10` `8cd43c996` `7918d901f` `6a72bb487` `e82826d6a` `b5369c05d` |
| `1dd286803` | car-v0627-follow314 `1557d2cba` | JSON nesting depth per kind as the bundled 3.14.10 has it (car-machine's iterative reader and writer, `stack::run_deep`/`spawn_deep`), the drive-like realpath tail held by 15 homes, the advanced diffs and generators through `reference.command`/`script_command` |
| `4388484cf` | car-v0627-s61 `6120144ab` | S6.1 car-watcher (watchloop, `app::App`, `api::Watcher`, launcher, homes, health, waking, afterwork, toasts, plugnotices, setaside, checkup/rescan), its diffs, car-harness `watcher.rs` |

Conflicts: `rust/GROUNDWORK.md` in every merge (all sections kept, in merge order; cifix carried Integration 8's earlier
"the full runs run detached" placeholder, which Integration 8's recorded long checks replace). Merge 1: `100ab5b39` and
`0a7ba6590` are the same change; `12fd020a3` and `bd311cb10` chose the same two fixture uuids, so the token diff merged clean.
Merge 2: `diffs_settings_plug` and `diffs_advstore`'s generator checks run through `reference.script_command` (follow314's
form over `d77a66647`'s direct `--check`), the advanced one still naming utf-8 as `3ec506531` asks. Merge 3: car-harness
`Cargo.toml` and check_groundwork's car-harness edge list take car-bin (S5.2) and car-watcher (S6.1) both.

### The plug, shared (`599fe8f1f`)

The reference hands one process's parts the same plug object (`edition.plug(paths)`: "loaded the first time it is asked for,
and the same object every time after"; `Control(self.paths, plug=self.plug)` in App, the icon, the cards). Now:

* car-control `Control::new(paths, host, plug: Arc<Guarded>)`; `plug()` still answers `&Guarded`. car-bin's CLI, the harness's
  bridge and `review_bridge.rs` pass `Arc::new(Guarded::null())`.
* car-watcher `api::SharedPlug` (the edition's `Factory` and a `OnceLock<Arc<Guarded>>`): made the first time a part asks, then
  the same `Arc` for the launcher's P13 questions (`supervise`, `plug_is_null`, `supervise_held`), App (`Start.plug`), each of
  App's Controls (they held a NULL plug of their own before: `App::control` passed `Guarded::null()`), the icon's `toggle` and
  `disarm_power` and the in-process bridge. `Guarded.failures` is then one count for the process where the reference has one
  per `guard()` wrapper over the same plug; nothing in the product reads it.
* Test: `car-watcher api::tests::every_control_of_one_watcher_sees_the_one_plugs_state` - a plug that counts its own
  `supervise_held` answers, asked through the launcher, two of App's Controls, the icon's Control and the launcher again: 1..5.
  Reverted one at a time, each fails it: App::control a fresh NULL plug (`Null` for 2), the icon's control a fresh plug (1 for 4),
  the launcher a fresh plug (1 for 2).
* The deep stack (follow314's rule): car-machine `stack::try_spawn_deep(name, body)` is `spawn_deep` with the thread's name and
  the spawn error kept (deep, else ordinary size, else that error), with a unit test; car-watcher's `watcher` thread (launcher and
  loop) and its `toasts` thread use it. No other thread is spawned in car-watcher, car-control or car-host's exports.

### Fixed here (`fea52e5f6`)

* `test_python315_encoding`: `rediff_follow314.py` and `rediff_watcher.py` (both cut before `3ec506531`) read git's output in
  the locale's encoding; they name utf-8 now.
* `test_rust_release.BudgetTests`: the merged standard binaries weigh 0.709 MiB deflated (car-v0627-cifix alone 0.697, the
  limit 0.7): `codex-auto-resume.exe` +6.8 KB and the setup program +4.9 KB from follow314's JSON reader and writer and its
  deep-stack threads. `standard_binaries_mib` is 0.8 by release_budget.json's margin rule; the measure is in the budget's note.

### Checks (`CARGO_BUILD_JOBS=4`, `CARGO_INCREMENTAL=0`; reference v0.6.26 on the bundled 3.14.10; rustc 1.100.0; code HEAD `599fe8f1f`, guards and frozen at `fea52e5f6`)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0 (every
                   result ok); cargo deny --locked check: advisories, bans, licenses, sources ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked --no-fail-fast rc=0 (car-adv 9 + 1); cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0: all 10 binaries the same with and without advanced/ (car_core.dll
                                                     e9d5629e...), profile-path scan none in any .exe, .dll or .pdb
run.py --build --reference v0.6.26 --reference-python bundled -v
                                                     Ran 370 in 7,585 s: 2 FAIL, 1 expected failure (diffs_review6's fresh
                                                     home), no skip, no `released:` rebuild. FAIL: the two HistoryNotYet
                                                     cases, FINAL-DELTA #1-#5 (compat_io ProbesDiff.test_source_and_api_checks,
                                                     codex_homes HomeDiff.test_schema_variants), the final-port seat's.
                                                     diffs_watcher_* all OK in the release harness.
the 15 frozen modules (test_parts --worker; CODEX_AR_CORE=rust)    456 pass on both, 0 differ (Python 400 s, Rust 428 s)
Python guards (standard lane, wait_quiet.sh): test_repo_hygiene test_privacy_claims test_privacy_bare_hosts test_edition_audit
  test_srcscan test_stack test_layers test_structural_invariants test_rust_release test_rust_power_guard test_rust_install
  test_rustdiff_reference_python test_review9_install test_host_contract test_python315_encoding test_rustdiff_script_command
                                                     Ran 193: 2 FAIL (encoding, budget: fixed above); then
                                                     test_python315_encoding test_rust_release.BudgetTests test_repo_hygiene
                                                     Ran 13, OK
```

### For the next seats

* **Integration 10** (S6.2a, S6.3e, S7.2a): `Control::new` takes `Arc<Guarded>` (a branch cut before `599fe8f1f` that builds a
  Control passes `Arc::new(..)`); car-watcher's `Factory` is called once, through `api::SharedPlug`.
* **S6.2b (the engine join)**: car-engine's `Given.plug` / `Options.plug` are still `Guarded` by value; App's engine is built with
  `plug=self.plug` in the reference, so the join hands the engine App's `Arc` (car-engine takes `Arc<Guarded>`, or a `Plug` over
  it) and `EngineMaker::engine` gets the plug. car-host's `car_bridge` runs on the host's calling thread: a request line it
  parses should be read on a deep stack (`run_deep`), as follow314's rule asks.
* The binaries budget is the stub core's plus the merged code; PLAN 6.6 still has P6 set it from its first full build.
## Seat S7.2a: the P7 skeleton, the plug's two halves, the shared Windows hands (branch `car-v0627-s72a`, 2026-11-27)

From `car-v0627-cifix` `b5369c05d` (Integration 8). Reference: the v0.6.26 final on the bundled Python 3.14.10.
`outputs/plans/v0627-rust/P7-DESIGN.md` 2.1, 2.2, S7.2a's row, 3, 6, 7 (the owner's answers: Q1 (a), Q3 (c), Q7 (a)).

### The skeleton (commit `0a6b752b1`; no later seat edits these lists)

* car-adv `lib.rs` and the `mod.rs` of `engine/` (40 modules), `control/` (19), `courier/` (12), `codex/` (+ `account`,
  `authfile`, `restart`, `swap`), `win/` (+ `appclose`, `dpapi`), `runtime/` (8 files) list every module of the plan.
  Each file a seat has not written names its seat in its first line and, where the registry names a `make`, holds that
  `make(paths) -> Option<Box<dyn Code>>` returning None: a seat fills its own files and touches no list.
* `capabilities/mod.rs`: a capability's code (`Code`: the 18 hooks at the points, whose default is the reference's
  AttributeError - a raise; the 11 optional hooks of `runtime._own`, whose default is "the class has none"), what a hook
  says (`Said`: DEFER, a word, a value, a tuple, a set, core's BACKEND, a channel, a route, an errand, a start route),
  `Raised` (the exception's class, cause and frames, for `_said_raised`), `Binding` (what `bind` hands: the code's own
  `Scoped`, made on demand under the runtime's lock), and **the `make` table over all 53 registry ids** (a test holds it to
  the registry's shown, waiting and installed-only definitions; `python_choice` has no code, Q1 (a)).
* `seam_p7.rs`: every cross-seat edge of the tag's import graph into a module not yet ported (the list is in the file),
  as a trait or a constant; the pure functions S7.2a's P2 needs now (`continued_handed`, `reset_message_handed`,
  `prompt_handed`, `chat_handed`/`chat_watched`/`paused_by_stop`, `for_open_watching`, `answer_key`, `words_pass`) are
  ported there faithfully, and each owner moves its own into its module at the integration that merges it.
* car-platform `lib.rs` (S7.2a's alone) lists `credman`, `dpapi`, `random` (S7.2a), `restart` (S7.2b), `job`, `winhttp`,
  `tls` (S7.3b). The `schannel` crate (Q4 (a)) is not in the locks yet: it is in the local cargo cache (0.1.26) but brings
  windows-sys 0.59 beside 0.61; S7.3b adds it with its first use, behind cargo-deny, in car-platform's `Cargo.toml` alone.

### Ported (module -> crate)

| Python | here |
|---|---|
| `credentials.py` | car-platform `credman` (the `Backend` trait, the real `Windows` one under the caller's prefix - no test reaches it - and `Memory`); car-adv `credentials` (`Secrets`, `SecretError`, the target rule, 2,560 bytes, `SystemTokens` over `random`) |
| `win/dpapi.py` | car-platform `dpapi` (`CryptProtectData`/`CryptUnprotectData`, no prompt, the caller's label; its one test seals random bytes in memory); car-adv `win::dpapi` (the product's label) |
| `secrets.token_hex`, `os.urandom` | car-platform `random` (`BCryptGenRandom`, system-preferred) |
| `runtime.py` (but `run_measurement`, S7.4's) | car-adv `runtime/` (table in `runtime/mod.rs`) |
| `plug.py` | car-adv `plug` (`AdvancedPlug`: the 22 hooks, `PLUG_API`, `NOTICE_KINDS`, `register_notice_kinds`, `create`) |
| `engine/hookclaims.py` `StopHook` | car-adv `capabilities::stophook` (P3 `blocked_at`, P8 `follow_real`) |
| `report/__init__.py` `make` | car-adv `capabilities::report` (`make_with(paths, Config)` = `Flow::new`; `report::seam::Runtime` for the runtime) |
| `engine/storeview.py` | car-engine `storeview` (`StoreView` over the engine's store: the nine reads, this home's alone, `last_usage`, `now`) |
| `engine/__init__.py` `_errand`, `StoreView(...)` at P8/P22 | car-engine `lib.rs` (`view`, `errand`: the view and the guards, a raise or a panic logged `plug_errand_failed`) |
| `store/plugclaims.py` `errand_guard` | car-store `plugclaims` (and car-harness's `EngineStore`) |
| `domain/plug.py` `View`, `_LedgerConnection`, `served_elsewhere`, a channel's `pools` | car-policy `plug` (`View`'s reads, `ReadFailed`, `Ledger::execute`/`sqlite`, `Plug::served_elsewhere`, `Guarded::served_elsewhere` (not counted, as `runtime/app.py` reads the property), `Channel::pools_said`, `Errand::run(view, guards)`) |

How the runtime is held: Python runs it under the GIL, and a code may call back in (its `Scoped`). `runtime::Shared` is the
runtime's fields in cells and a lock its own thread may take again (`Gil`); `Arming<'static>` borrows the boxed state,
registry, catalogs and edges it is declared before (dropped first). Errands run outside the lock, then take it to trip.

### Not ported, and why

* ~~The core side's carrying of a record of the plug's own, P12's pool, P11 inside car-store's claim, the launch guard
  on a channel's send and a route's resume~~: done by S7.2a2 (section below).
* **The advanced proxy (Q3 (c))**: not built. What is here is its ledger (`tests/rustdiff/advledger_s72a.py`) and the
  runtime it will drive. The proxy needs a serve loop in `advtrace` (one runtime per test, its codes the test's own Python
  objects asked back over the pipe, as `engineproxy.py` asks the store) and forwarders for `runtime.state.*` (car-adv
  `state::calls`) and `runtime.arming.*` (advprobe's ops). **Of the 146 `advancedcase` files only 26 need nothing but S7.2a
  and the done seats** - the design's 146 assumed every capability test needs only the runtime; by import, 120 also need a
  capability module of S7.2b-S7.3a or S7.4 (the table below).
* `surfaces.answer` (P10): S7.3a's; the plug answers DEFER there (NULL's) until it is ported.
* `runtime.run_measurement`/`complete_measurement`: S7.4's (`runtime/measurement.rs`).

### The advanced tests by the seat that unlocks them (`python -X utf8 tests/rustdiff/advledger_s72a.py --markdown`)

| unlocked by | files | of them advancedcase |
|---|---:|---:|
| S7.2a (the proxy over this runtime) | 68 | 26 |
| S7.3b | 14 | 11 |
| S7.2b | 9 | 3 |
| S7.2d | 9 | 2 |
| S7.2e1 | 19 | 13 |
| S7.2e2 | 14 | 4 |
| S7.3a | 79 | 51 |
| S7.4 | 21 | 13 |
| S6.2a (the C# page, `pagecase.py`) | 48 | 23 |
| **all** | 281 | 146 |

The per-file list: the script without `--markdown`. `test_advanced_shots*` are in S7.2a's row by import but are the main
session's pictures.

### The proof

* **`diffs_advplug.py` (`AdvPlugDiff`, `advplug.py`, example `advtrace`)**: 37 scenarios, 128 steps (none an error on
  the reference), 67 hooks asked, 179 rows of advanced.sqlite at the end, every answer, every hook asked and every row
  equal to the v0.6.26 tag's `Runtime` on the bundled 3.14.10 (Ran 1, OK, 112 s on the debug `advtrace`). The first run
  differed in one scenario, in the harness (the Rust script noted a hook it did not have before raising; the reference's
  `__getattr__` raises first): fixed in `advtrace/scripted.rs`.
* **The engine's traces after the core side (risk 1)**: `run.py --build --reference v0.6.26 -k EngineTraceDiff -k
  EngineReview6 -k EnginePanicDiff -k EngineInputsDiff -k LaunchGuardHeld -k EnginePlugDiff -k ScriptDiff -k RefusalDiff`:
  Ran 24, OK (expected failures=1, B1 as before), 834 s; corpus 81 / 1,023 steps, walks 60 / 5,153, scripted plug 63 /
  878, deferring plug 81 / 1,023, walks with a plug 40 / 3,429 - all equal. The standard edition's equality did not move.
* **Mutation checks** (each alone, `advtrace` rebuilt, `AdvPlugDiff` run, the file restored; scratchpad `mutate.py`): a
  watched answer taken (`watched_is_a_would_have`), a raising hook leaving its capability on (`a_code_that_cannot_be_made`),
  P2 handing a record twice (`records_of_the_edition_s_own`), P18 taking a list (`sessions_take_a_set_or_a_tuple`), Send
  now never preferred over EARLY (`send_now_is_preferred_over_an_early_look`), keep on never passing a record over
  (`kept_on_passes_over_the_record_alone`): **6 of 6 caught**, none survived.
* Unit tests: car-platform `credman` 2, `dpapi` 1 (random bytes in memory), `random` 1; car-adv `credentials` 1, the make
  table 1.
* The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_adv72a.py --reference v0.6.26`.

### Seams left

* (filled by S7.2a2: car-store `ledger::ledger_holds` hands the claim's own `sqlite3*` and `execute`.) car-policy `Ledger::sqlite`: car-store's claim must hand its connection's `sqlite3*` under the authorizer and savepoint
  of `_ledger_holds` (and implement `execute` for a plug written otherwise). `runtime.claim` opens it with
  `Connection::from_handle` (never closed there).
* car-engine `Store::errand_guard` has a default (AttributeError) for stores that have none; car-harness's `EngineStore`
  and car-store implement it. The proxy's `AskStore` does not yet (an errand under the proxy raises, as before).
* `runtime::Options` is what an entry point hands: `edges` (the real `Edges` is the integration's, S7.3d), `maker`
  (`capabilities::make`, or `make` with the world for `stophook`/`report`), `auto_check` (`autocheck::tend` with its
  `World`), `log` (the logbook), `tokens` (`SystemTokens`). `plug::create(paths, options, os)` is the factory's call.
* `capabilities::report::make_with(paths, Config)` and `stophook::make_with(paths, home_of)`: the entry points pass the
  live world (S7.3d); the table's plain `make` has none for the report and the told home alone for the Stop hook.
* `headless::stop_all(headless::follower(), 20.0)` at the watcher's exit (adv72d's note) is the watcher's (S6.1) to call
  as it leaves; the runtime holds no exit of its own.

### For later seats

* Every capability seat: implement `Code` on your type; return `Said::Word` for an `Alternative` (the runtime's `is`
  checks read it), `Said::Value` for anything else, `Said::Tuple`/`Set` where the reference returns one; bind through
  `Binding::with`. Your `make` is already in the table.
* Move your function out of `seam_p7.rs` into your module at the integration (and point the runtime at it).
* The proxy seat: `advtrace` is the runtime over a scripted code; turn its step loop into a serve loop (`proxy.rs` of
  car-harness is the model), and move files from "waits" to "green" in `advledger_<seat>.py`.

### Gates (HEAD `5793a3f02`'s code, `CARGO_BUILD_JOBS=4`, rustc 1.100.0)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0; cargo deny: all four ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh            rc=0, every standard binary the same with and without advanced/; profile-path scan: none
Python (standard lane, wait_quiet.sh)                 test_repo_hygiene test_privacy_bare_hosts test_privacy_claims test_no_console_windows: Ran 51, OK
```

## Seat S7.2a2: P2's records, P12's pool, P11 inside the claim, the launch guards (branch `car-v0627-s72a`, 2026-11-27)

Finishing S7.2a in its worktree from `d70ef6bbf`. Reference: the v0.6.26 final on the bundled Python 3.14.10.

### Ported (module -> crate)

| Python | here |
|---|---|
| `store/ledger.py` `_ledger_holds`, `_ledger_authorizer`, `_attachable`, `_same_file`, `_LedgerConnection` | car-store `ledger` (SAVEPOINT claim_ledger; the authorizer set with `sqlite3_set_authorizer` on the claim's own connection; `execute` and the raw handle, both dead once the ledger answered; a hold, or a raise on a claim that carried an answer, rolled back) |
| `store/claims.py` `reserve_detailed(ledger=)`, `_resend_claim` | car-store `Store::reserve_ledgered` (`reserve_detailed` is it with no ledger); the engine asks it through `Store::reserve_ledgered(..., &plug)` |
| `store/plugclaims.py` `reserve_record`, `record_guard` | car-store `plugclaims` (beside `errand_guard`); car-engine's `Store` seam carries both (default AttributeError) |
| `engine/plugrecords.py` (all) | car-engine `plugrecords` (`plug_records`, `try_record`, `dispatch_record`, `record_claim`, `record_problem`, `record_sent`, `watch_record`, `paused_records`, `persons_turns`); NOTED_LIMIT is the tag's 512 (the port had 4096) |
| `engine/recordchannel.py` | car-engine `recordchannel` (`Carrier`, `marker_free`, `record_carried`, `record_queued`, `RESTART_GRACE`, `record_client`/`proof`/`words`, `take_back`) |
| `engine/launches.py` + delivery.py `_take_slot`/`_pooled`/`_launched`/`_free_slot`/`_settle_launch` | car-engine `launches` (`LaunchPool`, `Slot`, `WorkerStore`, `Opener`, `Call`) and `delivery.rs`; the tick opens the pool when P12 answers 2-8 and an opener is set (`Engine::set_opener`) |
| `plughands.Channel.send`, `plughands.Route.resume` (the guard entered first) | car-engine `plugrecords::guarded_send` (core's channel sends and a record's), `routes.rs` (`submission_guard` before `Route::resume`) |
| `os.stat().st_dev/st_ino` | car-platform `files::file_identity`, through car-store's `Links::file_identity` (default None: paths compared) |

### Seams left

* `Engine::set_opener(Opener)`: the watcher (S6.1) hands a function opening a car-store `Store` for a worker
  (`WorkerStore`: `submission_guard`, `close`); without one every send is inline (P12 answered 1), as before.
* `Backend::worker_send()`: the real backend (car-codex's transport, wired by S6.1) must hand its send as a
  `Send + Sync` function for a pooled send; a backend with none sends inline and the claim carries no CONCURRENCY
  (AUDIT line). car-harness's backends have none (their traces never open a pool: `open_store` false).
* The proxy's `AskStore` keeps the default `reserve_ledgered` (no ledger asked) and has no `reserve_record`/`record_guard`:
  a record under the proxy costs itself, as an errand does.

### The proof

* **`diffs_engine_records.py` (`EngineRecordsDiff`)**: the scripted plug of `diffs_engine_plug` now also answers P2
  (`records`) and P11 (`claim_ledger`, on both sides: `enginerun.scripted_plug` and car-harness `plugscript.rs`); 16 scenarios, 112 steps, 9 sends, 211 plug questions, all equal to the v0.6.26 tag on the bundled 3.14.10 (17 s): sent
  and delivered, kept while queued, unproven a day on, a Pause watching it, the ledger holding/raising/deferring at
  the claim and holding at the launch, every gate's wait, observe only noted once, bad words and damaged records
  dropped, a send not started/raising/unknown, a hook raising, a marker-free message in flight.
  The first run differed twice and found a port bug each time: `_worded` took car-policy's PromptError *codes* for other
  exceptions (fixed), and the scenarios' conversation (fixed in the test, `fail_usage`).
* **The engine's traces after the core side (risk 1)**: `run.py --build --reference v0.6.26 --reference-python bundled -k EngineRecordsDiff -k EngineTraceDiff
  -k EngineReview6 -k EnginePanicDiff -k EngineInputsDiff -k LaunchGuardHeld -k EnginePlugDiff -k ScriptDiff -k RefusalDiff
  -k AdvPlugDiff`: Ran 26, every family equal (corpus 81 / 1,023 steps, walks 60 / 5,153, deferring plug 81 / 1,023,
  walks with a plug 40 / 3,429, scripted 63 / 878, AdvPlugDiff as S7.2a left it; B1 the expected failure as before) -
  the standard edition's equality did not move. Its one red, LaunchGuardHeld, was the harness: the engine harness now
  writes a send down before its guard (`backend.send_noted`, so a record's launch ledger question follows it on both
  sides) and the test's probe had not learnt the flag; fixed, rerun alone: OK.
* **Mutation checks** (scratchpad `car-v0627-s72a-mutate.py`, each alone, car-harness rebuilt, EngineRecordsDiff run,
  the file restored): the launch guard ignoring the ledger, a raising ledger no longer holding a claim that carried the
  plug's answer, observe only writing its line every tick, a send never started told SENT, a continuation's turn never
  looked at, a record a day old never unproven: **6 of 6 caught**, none survived.
* Unit tests: car-engine `launches` 2 (claim-order settling with every worker store closed; not_started where the store
  cannot open, unknown where the send raised or answered no mapping).
* The re-diff: `python -X utf8 tests/rustdiff/rediff_adv72a.py --reference v0.6.26` (scope and families now include
  S7.2a2's files and `EngineRecordsDiff`).

### Not done here (the advanced proxy, owner Q3 (c))

Not built in this seat (the time went to the core side and its proof). What it needs, in order: (1) a serve loop in
`advtrace` (`examples/advtrace/`), one `Runtime` per test whose capability codes are the test's own Python objects asked
back over the pipe (car-harness `proxy.rs` and `tests/rustdiff/engineproxy.py` are the model); (2) a package
`codex_auto_resume_advanced` under `CODEX_AR_CORE=rust` (a `tests/rustdiff/advproxy/` tree put first on the path, as
`shim.py` does for core) whose `runtime.Runtime`, `plug.AdvancedPlug`/`create` and `registry.make` forward to it, and
whose other modules re-export the tag's own until their seat ports them; (3) forwarders for `runtime.state.*` (car-adv
`state::calls`) and `runtime.arming.*` (advprobe's ops); (4) the 26 files of `advledger_s72a.py`'s S7.2a row run through
it, moving each from "waits" to "green". The ledger (`python -X utf8 tests/rustdiff/advledger_s72a.py`) is unchanged.

### Gates

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0 (after abb4bbba4); test --locked --no-fail-fast rc=0; cargo deny: rc=0
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny: rc=0
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates), with the one
                                                     SQLite callback car-store defines named in SQLITE_CALLBACKS (b2cde55c5)
bash advanced/rust/tools/check_rebuild.sh            rc=0, every standard binary the same with and without advanced/; profile-path scan: none
Python (standard lane, wait_quiet.sh)                 test_repo_hygiene test_privacy_bare_hosts test_privacy_claims test_no_console_windows: Ran 50, OK
```

## Seat S7.2a3: the advanced proxy (owner Q3 (c)) (branch `car-v0627-s72a`, 2026-11-27)

From `8e6362cbf` (S7.2a2). Reference: the advanced lane's own Python (the v0.6.26 tree), test by test. P7-DESIGN 3.1 and 7
(Q3 (c): every advanced test file runs unedited on Rust, module by module, S4.2's method widened).

### What is built

* **`advserve`** (car-adv example, `examples/advserve/`: `main.rs` the loop, sessions and calls; `wire.rs` the pipe and the
  nested asks; `proxied.rs` what is asked back). One process per test process, a JSON line each way, one session per
  object the test made: a `Runtime` (car-adv `runtime::Shared`) or a standalone `AdvancedState`. Calls: `open`, `close`,
  `runtime` (every `Runtime` method by its Python name; `make` = `_code_of`, `action`, and `fault`), `state`
  (`state::calls`), `scoped` (a code's own `Scoped`, through its `Binding`), `made_scoped` (a `Scoped` the test made with
  callables of its own), `arming` (every `Arming` method by its Python name and keywords), `object` (the errands of a
  tick, run with the test's guard), `told` (`acted_when_told`), `op` (advprobe's pure ops: registry, statement, words,
  policy). car-adv asks back: the clock, the policy, the view, the live view and the measurements handed in, the language,
  a capability's `make` (the test's own definitions; a shipped definition's `make` is car-adv's `capabilities::make`
  table - `registry.make` forwarded), every hook of the code made (`ProxyCode`: the 18 hooks at the points and the
  optional ones its class defines, `runtime._own`), the objects a hook answers with (`ProxyThing`: channel, route,
  errand, start route - the same Python object comes back to the caller), core's view (`ProxyView`), `Arming`'s edges
  into modules not ported yet (`AskEdges`, each the reference's own function: `hookplugin.follow`, `powertasks.follow`,
  `account.forget`, `usage.*`, `wrapwords.*`, `compatdata.table_for`, `autocheck.results_for`/`tend`, `_view_of`,
  `_live_view_of`) and the watcher's log line (`_said_raised`).
* **car-adv `runtime`** (S7.2a's own files): `Runtime::make(capability)` (`_code_of` for a caller that only needs it
  made) and `runtime::faults` - `Faults`, the state methods a test made raise (`patch.object(runtime.state, "arming",
  side_effect=StateError(...))`), and `Faulted`, the `StatePort` `Arming` reaches the state through (every method checks
  `Faults` first; empty in the product, so every call goes on unchanged); the runtime's own direct calls that tests patch
  (`admit`, `admission`, `record_moved`) check it too.
* **`tests/rustdiff/advproxy/`** (loaded by path as `rustdiff_advproxy` by the core shim, `tests/rustdiff/shim.py`, whose
  finder now also passes every `codex_auto_resume_advanced.*` module): `table.py` (THE table: all 149 modules of the
  package at the tag, the seat of each, and what of it is FORWARDED, THROUGH, HANDED, DATA or WAITS), `pipe.py` (the
  pipe, the JSON rule, the counts of calls a file made), `runtime.py` (S7.2a3's forwarders: `Runtime` - and so
  `AdvancedPlug`, which builds `runtime.Runtime` lazily - `StateProxy`, `ArmingProxy`, `AdvancedState`, `ScopedProxy`,
  `MadeScoped`, the edges), `ledger.py` (the per-file table of all 281 files). `CODEX_AR_ADVPROXY=0` leaves the advanced
  edition the reference's under `CODEX_AR_CORE=rust` (core's proxies alone, to tell which side a difference is on).
* `tests/rustdiff/rediff_advproxy.py --reference v0.6.26 [--build]`: the final's re-diff (the scope's changed files, then
  every GREEN file on both lanes again).

What a test reads of the reference's private names is kept where it is the test's arrangement, not its subject:
`state._transaction()` / `_read()` are a connection of the test's own to the file car-adv keeps, with the reference's
transaction rule; a fixture writer on that connection (`record_spend(connection, ...)`, `_prune`, `_prune_spend`,
`AdvancedState._tables`) is the reference's own; `runtime.arming._policy` / `_view` / `_measured` / `_live` are the
sources car-adv asks at each use, so a test's replacement takes effect; `runtime.arming.catalogs = other` refills the
runtime's own catalogs folder before car-adv reads a language; `runtime._code` is the codes made.

### Not forwarded (named in table.py and in the per-file table's reasons)

* **P11 (`Runtime.claim`)**: it runs on core's own SQLite connection inside core's claim (car-store's `ledger_holds`
  hands the raw `sqlite3*`), which a second process cannot share; held by `diffs_engine_records` (S7.2a2). Files whose
  subject is the claim (`test_advanced_ledger`, `test_advanced_hook_claim`, the claim halves of `test_advanced_admission`)
  wait for the integrated host (P6/S7.3d), where car-adv runs in core's process.
* **A module constant a test patches** (`patch.object(session, "SCHEMA_VERSION", ...)`: "a build of version N" in
  `test_advanced_state_v5`/`_v6`/`_v7`, `test_advanced_schema_v8`): car-adv's schema version is compiled in; these tests hold
  the reference's own migration constants and stay on the reference (car-adv's migrations are held by `diffs_advstore`).
* `run_measurement` / `complete_measurement` (S7.4), every module table.py marks WAITS.

### The 26 files of S7.2a's row (advledger_s72a.py), run with `ledger.py --run` (both lanes, test by test)

| result | files |
|---|---|
| **green on Rust** (7 files, 204 tests; every test equal to the Python lane, calls to advserve made) | `test_advanced_arming` (53), `test_advanced_registry` (65), `test_advanced_autocheck` (44), `test_advanced_state_v4` (17), `test_advanced_requires` (15), `test_advanced_window_switches` (6), `test_advanced_keep_on_every` (4) |
| green but for the claim (P11 host) | `test_advanced_state` (61 of 63: AttachTests, RecordTests attach to core's connection), `test_advanced_hook_claim`, `test_advanced_ledger` |
| green but for core's engine proxy (S4.2's, not this proxy: they fail with `CODEX_AR_ADVPROXY=0` too) | `test_advanced_admission` (21 of 27; EngineCase's 6) |
| a shipped capability's code not ported yet | `test_advanced_goal_verified_resets` (goal_continuation, S7.2e1) |
| the reference's own constants patched (reference only) | `test_advanced_state_v5`, `_v6`, `_v7` (12 of 13 green), `test_advanced_schema_v8`, `test_advanced_state_options` (17 of 20) |
| pass under the proxy but reach no forwarded code: their subject is another module's own functions, which waits for its row | `test_advanced_credits`, `_headless` (codex.*, S7.2c), `_hook_input` (hook.*, S7.3c), `_credentials` (credentials, S7.2a), `_examples`, `_hidden` (statement, registry, S7.1b), `_word_keys` (statement, images), `_measure_m4b`, `_usage_refusal` |

The design's estimate (P7-DESIGN 3.1, "146 advancedcase files only drive the runtime") does not hold by run either: a file
that builds over `advancedcase` often tests a module's own function, a shipped capability or the claim.

### How a later seat adds its modules (the how-to)

1. **Serve it** in advserve: a session kind for a class (`open`'s `kind`, as `runtime` and `state`), or a `call` for its
   methods, or an `op` of a probe already in the example (advprobe's families are compiled in; S7.2c's `advcodex` ops can
   be added the same way, by `#[path]`).
2. **Forward it**: a module of your own in `tests/rustdiff/advproxy/` (`<seat>.py`) with the reference's signature,
   calling `pipe.PIPE.request(session, call, ...)`; what car-adv asks back is answered by the session owner's `answer`.
   Values cross by `pipe.plain`; give answers their Python shapes back (tuples, frozensets, enums) as `runtime.py`'s
   `TUPLES`, `STATE_SHAPES`, `ARMING_SHAPES` do - a test compares `(False, 0)` and `[False, 0]` as different.
3. **Name it** in `table.py`: `forwards={"Name": "<seat>.Name"}` on its module's row - the one place per module.
   A shipped capability's code needs nothing here: `registry.make` is car-adv's table already, so filling `make` in
   car-adv makes it reach the proxy.
4. **Prove it**: `python -X utf8 tests/rustdiff/advproxy/ledger.py --run <files>`; a file printed GREEN goes into
   `GREEN`, one that still waits into `RUN_WAITS` with its reason; break one rule of your Rust and see a proxied test fail.
   `python -X utf8 tests/rustdiff/advproxy/ledger.py --seat S7.2b` lists what waits for your seat.

### The proof that the proxy runs on Rust (mutation checks)

Scratchpad `car-v0627-s72a-mutate3.py`: each rule broken alone in car-adv, advserve's release rebuilt, one GREEN file's
tests run with `CODEX_AR_CORE=rust`, the file restored. Caught: Arming refusing a forbidding policy as "not allowed"
(`test_advanced_arming.RemainingRefusalTests`: 3 failures), the statement check of `arm` refusing an incomplete
statement as stale (`DashboardOnlyTests`), the prompt queue's limit one short (`test_advanced_state_v4`), a stored
Keep on read inverted (`test_advanced_keep_on_every`), the window switches never carried (`test_advanced_window_switches`:
4 failures), the tick no longer tending the automatic check (`test_advanced_autocheck.WatcherOnlyTests`) - each green on
the Python lane. One mutation survived, and says where the corpus is thin, not the proxy: `arm`'s own
STATEMENT_INCOMPLETE return after the requirement check (arming.rs, the `refuse(...)` path) is reached by no test of
these files, since `check` refuses first.

### For later seats

* Every seat: your done-check includes your modules' advanced tests through the proxy (Q3 (c)); the how-to above, and
  `ledger.py --seat <you>` for your list. A shipped capability you port reaches the proxy with no proxy edit (its
  `make` is car-adv's table).
* S7.3d / P6 (the host): P11 through the proxy needs car-adv in core's process; until then the three claim files wait.
* S4.2's proxy: `test_advanced_admission.EngineCase` (6 tests) fails on core's engine proxy with an advanced plug
  (`CODEX_AR_ADVPROXY=0` shows it is core's side): the proxy's AskStore has no `reserve_record`/`record_guard` and keeps
  `reserve_ledgered` without a ledger (S7.2a2's seams left).
* The 25 "ready" files (no advancedcase, nothing they import waits) have not been run; most reach no forwarded code and
  will go to RUN_WAITS with their module's seat.

### Gates (`CARGO_BUILD_JOBS=4`, `. tools/rustflags.sh` first, rustc 1.100.0)

```
## advanced/rust   fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0 (after the `Told` alias); test --locked --no-fail-fast rc=0; cargo deny: all four ok
## rust            fmt --check rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh            rc=0, every standard binary the same with and without advanced/; profile-path scan: none
Python (standard lane, wait_quiet.sh)                 test_repo_hygiene test_privacy_bare_hosts test_privacy_claims test_no_console_windows: Ran 50, OK
privacy_scan.py on every file added                   clean
```

## Seat S7.3b: the courier and the remote reach (branch `car-v0627-s73b`, 2026-11-27)

From `car-v0627-s72a` `d70ef6bbf` (the S7.2a skeleton). Reference: the v0.6.26 final on the bundled Python 3.14.10.
`outputs/plans/v0627-rust/P7-DESIGN.md` S7.3b, 2.2, 3, 4, 6, 7 (the owner's Q4 (a) WinHTTP + `schannel`, Q5 (a) a hand-written
HTTP/1.1 server, Q3 (c) the proxy).

### Ported (module -> crate)

| Python | here |
|---|---|
| `courier/address.py` | car-adv `courier::address` (with `urlsplit` and `ipaddress` as these checks read them: 3.14's bracketed-netloc and NFKC checks, IPv6's 45-character limit) |
| `courier/keep.py`, `outbox.py`, `feed.py` | car-adv `courier::{keep, outbox, feed}`; `Scoped::outbox()` / `Scoped::feed()` in `state/scoped.rs` |
| `courier/http.py` (but `stream`, D8) | car-adv `courier::http` (`Opener` = urllib's opener seam, `Failure`, `request`/`post`/`get`, `SystemOpener` over WinHTTP) |
| `courier/channels.py` | car-adv `courier::channels` (`lines`, `webhook_body`, `send`, `mail`, `test`, `drain`, `pair`), `channels::mime` (set_content's transfer encoding, quoted-printable, base64, the flattened message, HMAC-MD5), `channels::smtp` (smtplib's dialogue; `Wire` = socket + Schannel) |
| `courier/telegram.py` | car-adv `courier::telegram` (`parse`, `readable`, `first_update_id`, `Poller` with `once`/`answer`/the commands, `run`, `Stop`) |
| `courier/api.py`, `page.py` | car-adv `courier::{api, page}` (routes, Host gate, `Gate`, http.server's request reading and refusals, `Service`, `start_on`/`Running`; the page template byte for byte in `page_template.html`) |
| `courier/resident.py` | car-adv `courier::resident` (`Roles`, `serve`, the mutex name, `running`) |
| `courier/launch.py` | car-adv `courier::launch` (`codex-auto-resume.exe courier --home H ...`, suspended, adopted into the job) |
| `courier/__main__.py` | car-adv `courier::main` (`parse`, `main_with` over a `World`, `work`, `check`; `Runtime` = what the parts ask of the runtime, implemented for `runtime::Runtime` and, across threads, `SharedAdapter` over `runtime::Shared`) |
| `control/courier.py`, `control/remote.py` | car-adv `control::{courier, remote}` (`remote::Layer` = core's Control as these use it) |
| `engine/{feed, push, remote}.py` | car-adv `engine::{feed, push, remote}`; their `make` in the table now answers a code |
| (Windows) | car-platform `winhttp` (`send`, `exclusive_listener`), `tls` (`client` over the `schannel` crate 0.1.26, MIT, in both locks with windows-sys 0.59), `job` (`adopt`: KILL_ON_JOB_CLOSE + NtResumeProcess; `mutex_exists`) |

### The proof (`tests/rustdiff/advcourier.py`, `diffs_advcourier_{pure,state}.py`, example `advcourier`)

Run with the tag v0.6.26 on the bundled 3.14.10 (each case's request and answer both sides; both advanced.sqlite files table by
table where a case has a home): addresses 160 cases (urls, tokens in three shapes, mailboxes, SMTP blobs, hosts, web view);
chat names, digests, 20 status-page bodies, 13 e-mail messages flattened against BytesGenerator byte for byte; 27 Telegram
texts, update ids, readable replies, remote listing/resolve/acts/metrics, 20 routes, 12 Host headers, 9 clients, 13 header
blocks against `http.client.parse_headers`, the Gate over 274 steps (lock, expiry, 256-client eviction), dates, push events
and constants; the outbox over 38 steps; 120 sends (every channel x rows x two languages, 12 scripted replies, 8 kept-secret
shapes) compared at the opener byte for byte; push lines in five locales; 3 drains (sent, refused, tls, dropped, expired,
tripwire); 6 pairings (code found, five bad codes tripping telegram_remote, 409 then 401, no token, no code, expiry); the
loopback API over 44 raw requests (every route, 401/403/404/405/409/413/421/431/400/501/505, HEAD, bodies, the lock after
ten wrong tokens, lan Host) with the Date masked. **All equal: Ran 8, OK.** Found and fixed by them: 3.14's bracketed-netloc
check, urllib's `full_url` keeping the fragment, KeyError for a record without its ids, NaN/infinite times, http.server's own
answers (headers on every refusal; nothing for an HTTP/0.9 GET).

Mutation checks (each alone, the example rebuilt, its diff run, the source restored; scratchpad `car-v0627-s73b-mutate.py`):
HOURLY 30 -> 31 (test_outbox), a label of 64 characters (test_addresses), LOCK_AFTER 10 -> 11 (the Gate), a task number with
a leading zero (Telegram parse), TRIPWIRE 20 -> 21 (test_drain), BAD_CODES 5 -> 6 (test_pair), two Host headers taken
(test_loopback_api): see the RETURN for the counts.

Unit tests: car-platform `winhttp` 4 (address parts, loopback-only plain HTTP, a loopback request's headers/body/cap, the
exclusive listener), `tls` 1 (a server that speaks no TLS is refused), `job` 1 (a throwaway cmd.exe adopted, exit code read);
car-adv `address` 2, `mime` 2 (MD5/HMAC RFC vectors, base64).

The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_adv73b.py --reference v0.6.26`.
The ledger of the 25 test files: `python -X utf8 tests/rustdiff/advledger_s73b.py --markdown`.

### Not done, and why (exactly what is left)

* **The advanced proxy** (Q3 (c)) does not exist yet (S7.2a's note): none of the 23 courier/remote test files runs unedited on
  Rust. `advledger_s73b.py` names, for each, the diff that holds its rules now and what it waits for.
* **The courier role of car-adv-bin**: `courier::main::main_with(argv, &dyn World)` is the role's body, but the product's
  `World` (the runtime over the home with the real maker, policy and catalogs - `runtime::Options`, the integration's Edges -
  the Credential Manager backend, `SystemOpener`, a `TcpWire` with the FQDN, `report::reading::paused`, the two mutexes, the
  resident's server over a core-Control `Layer`) is not written, and car-adv-bin's `main` still calls `core_main`. S7.3d:
  write `SystemWorld`, then `main_with(&[Role { word: "courier", run }])` in car-adv-bin.
* **`remote::Layer` over core's `Control`** (status document from `statusfile::content`, pending rows, set_enabled, cancel,
  release, watcher_running) is the trait only; the diffs use a scripted layer. S7.3d/S7.3a writes `CoreLayer`.
* **Not diffed** (written, unit-tested or not): `Poller::once` scenarios, `resident::Roles` follow/unreadable, the SMTP dialogue
  on a loopback wire (smtplib with an identity TLS on the reference side), `control::courier` and the cards of
  `control::remote` over a runtime, `engine::{push, feed, remote}` through the runtime's points (S7.2a's advtrace with the
  real codes), `courier::main::work`.

### Seams left

* `courier::main::World` (above); `courier::http::Opener` (`SystemOpener` is the product's); `channels::smtp::Wire`
  (`TcpWire::new(fqdn, None, MAIL_SECONDS)` is the product's); `control::remote::Layer`; `resident::{ServerFactory, Poller}`;
  `engine::push::{Paused, Launch}`, `engine::feed::Launch`, `engine::remote::{Running, Launch}` (defaults wired to
  `report::reading::paused`, `courier::launch`, `courier::resident::running`).

### For later seats

* S7.3a: the courier's and remote's bridge commands call `control::courier::{view, save, forget, test, feed_refresh}` and
  `control::remote::{api_view, api_token_new, pair_state, pair_start}` with a `Runtime` (the bridge's `runtime::Runtime`
  is one) and the seams; `Refusal` words are the tag's.
* S7.3c: `report::github::Jobs` can be `car_platform::job::adopt` (a `std::process::Child` started with `CREATE_SUSPENDED`).
* The import-table test (P7-DESIGN 3.5): car-platform now holds WinHTTP, WinSock and Schannel calls; only `courier::*` calls
  them, so the standard binaries must still import none (dead code) - check_rebuild's run below says they are unchanged.

## Seat S7.2b: the saved accounts - the account switch and its Windows acts (branch `car-v0627-s72b`, 2026-11-27)

From `car-v0627-s72a` `8e6362cbf`. Reference: the v0.6.26 final on the bundled Python 3.14.10 (the diffs start it
through `refpython.command`, so `--reference-python` decides). `P7-DESIGN.md` S7.2b's row, 2.2, 3, 4, 7.

### Ported (module -> crate)

| Python | here |
|---|---|
| `codex/authfile.py` | car-adv `codex::authfile` (`store_mode`, `usable`, `check`, `read`, `write_atomic`, `replace`, `own_folder`, `confined`, `private`/`private_dacl`, `remove_tree`, `sweep`, `Scratch`; `Fault`, the reference's exception by class) and `codex::authfile::toml` (Python 3.14's `tomllib` whole: statements, keys and their flags, nests and arrays of tables, strings and escapes, numbers, dates checked as `date()` checks them, times, inline arrays/tables, and every Python frame counted so a document nested past the recursion limit is the RecursionError the reference lets out) |
| `codex/account.py` | car-adv `codex::account` (`plan_word`, `parse`, `identity`, `digest` - HMAC-SHA256 over car-machine's SHA-256, `bytes.fromhex` as CPython reads it -, `new_salt`, `mask`, `read`, `run_codex`, `switch`; the seams `Session`/`Opener`, `Backend`, `Runner`; `Live`: the product's own sessions through `inuse.backend` or core's Backend on a scratch home, `ProcessRunner` over report/github's runner) |
| `codex/restart.py` | car-adv `codex::restart` (`busy`, `restart`, the `Hands`, `BusyStore`, `Activity` seams; `LiveHands`: core's process list read afresh, Windows' process identity, `win::appclose`, the newest own conversation, `codex_link.open_in_codex`) |
| `codex/swap.py` | car-adv `codex::swap` (`other_engines`, `engines_gone`, `meters`, `usage_of`, `has_room`, `read_profile`, `switch`, `recover`, `unwind`, `save_current`, `add_by_login`, `known`, `read_answer`, `put_back`, `previous_of`, `is_in_place`; `World` - the module's own seams; `Live`) |
| `win/appclose.py` | car-adv `win::appclose` (`ask_close`, `end_process`, the reference's checks and its masking of a pid and a FILETIME as ctypes masks them) over car-platform `restart` (`Manager`: RmStartSession, RmRegisterResources, RmShutdown, RmEndSession; `Kernel`: OpenProcess, WaitForSingleObject, GetProcessTimes, TerminateProcess, CloseHandle; `private_folder`: the folder's DACL `D:P(A;OICI;FA;;;<sid>)`) |
| `engine/account.py` | car-adv `engine::account` (`AccountWatch`: P8's errand, the look, `_hold_waiting`, `_hold_rules`, `notice_view` for the surfaces; `forget`; `SaltStore` over `credentials::Secrets`; `live_seams`) |
| `engine/autoswitch.py` | car-adv `engine::autoswitch` (`AutoSwitch`: P8's look, P7's `schedule`, `tend`/`settle`, `put_in` (the person's own switch), `choose`, `best`, `seen`, the 24-hour ceiling, the told list; `live_seams`, `live_busy` over car-store and car-codex's LocalSource) |
| `profiles.py`'s `_seal`, `_open`, `_mutex`, `authfile.private`, `authfile.sweep`, `swap.unwind` (S7.1a's `Host`) | car-adv `state::seam::accounts::Windows` (DPAPI with the product's label, car-platform's named mutex `account-switch:<normcase(folder)>`, the private DACL, the sweep, the put-back over the live world) and `live_profiles(home)` |

How a code is held: `AccountWatch` and `AutoSwitch` keep their state in an `Arc<Mutex<_>>` the P8 errand shares
(the errand runs outside the tick, as the reference's `_Errand` holds the code); each look takes the capability's own
`Scoped` through its `Binding`, so a probe hands a `Scoped` over a real advanced state and drives the same function.

### The proof (`tests/rustdiff/advaccount.py`, `diffs_advaccount_{pure,files,swap,engines}.py`, example `advaccount`)

* 11 test classes, **1,538 cases**, every answer, every call a stand-in was asked, and every file left (profiles sealed with
  S7.1a's stand-in, the intent, Codex's sign-in file, scratch homes; the advanced state as its SQL dump) equal to the
  v0.6.26 tag on the bundled 3.14.10: account pure 166, sessions and switch 171, Restart Manager and kernel32 141, busy
  129, restart 60, checks and names 31, store_mode 386 config files (a corpus of TOML edges, nesting at the recursion
  limit both ways, 200 random documents), usable 8, swap readings 39, other engines / engines gone / read answer 159,
  owned folder 13, read/replace 16, scratch home 60, sweep 10, read_profile 17, save_current/add_by_login 16, recover 22,
  unwind 9, switch 32, the watch 20, autoswitch 33. Each side runs on its own copy of the folders the test made;
  junctions are the test's own.
* Found and fixed by the diffs: none in the port after the first full run (the reds were the harness: the boot's own
  argv, surrogates in the request, a cwd written two ways, a case-insensitive name twice in a setup) - and one that
  mattered: the reference's `account.switch` with no backend fell into core's real discovery and asked this PC's
  installed engine for its version (`codex.exe --version`, once, read-only, under scratch homes; nothing else ran: the
  runner was the stand-in). The reference script now replaces `inuse.backend`, `pairing.processes_named`,
  `resource_users` and `process_identity` with refusals before anything runs.
* The first mutation round caught 5 of 9 and the 4 survivors showed the swap and engine families hollow: their saved
  accounts were seeded as hex text (refused by `check` on both sides) and the watch's arming seed used an actor that is
  no word, so every case of those families raised the same error before it reached the code. Seeds fixed; `same()` now
  fails a family whose every case raised; a survey of the reference's answers per family (switch: 13 outcomes over 28
  cases, recover: 9 over 22) is in the commit's run.
* `engine/account.forget` let every exception go as false; the reference lets anything but SecretError, StateError and
  OSError out: fixed (it returns a Result now; `Edges::account_forget` reads false for a caught one, as before).
* **Mutation checks** (scratchpad `car-v0627-s72b-mutate.py`, each alone, `advaccount` rebuilt, its family run, the
  file restored): a date the month has not taken as a date (tomllib), an address of 321 characters kept
  (`account.parse`), an app that closed unasked not seen closed (`restart`), a window at 95 with room (`has_room`),
  another account signed in meanwhile saved back (`swap.switch`), a reused id ended (`appclose.end_process`), a switch
  of the edition's own holding core's waits (engine/account), eleven switches a day (engine/autoswitch), a put-back over
  a file the switch did not put there (`swap.recover`): **9 of 9 caught** (after the seed fix above; 4 had survived the
  hollow families).
* Unit tests: car-platform `restart` 3 (a throwaway `cmd.exe` child of the test's own: its handle, its creation time,
  TerminateProcess; the Restart Manager registered with that child alone; a scratch folder made private and its DACL
  read back), car-adv `codex::account` 1 (RFC 4231 HMAC vector).
* The ledger: `python -X utf8 tests/rustdiff/advledger_s72b.py` - 23 advanced test files import this seat's modules;
  all wait for the advanced proxy (S7.2a3), and 14 of them also for S7.2d, S7.2e1, S7.2e2, S7.3a, S7.3b or S7.4.
* The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_adv72b.py --reference v0.6.26`.

### Seams left

* `pairing._OWN`: car-codex keeps the app servers this process holds but has no reader of their pids, so
  `swap::Live::world().own` is empty: an app server of our own counts as another engine (ENGINE_ALIVE, nothing written)
  until car-codex gives one (`pub fn own_pids()` beside `own_server`, the integration's to add).
* `seam_p7::ResetWatch`: `engine::account::TagCount` is the tag's two-line `count`; the integration points it at S7.2d's
  `resetwatch`. `seam_p7::OpenTarget` (idle seconds) is not used: `live_seams` reads car-platform's `idle_seconds`, which is
  what `opentarget.idle_seconds` itself calls.
* `account::Live::product_version` is `config.version()` of the folder holding the running exe; the entry point (S7.3d)
  may hand the installation's own.
* `state::seam::accounts::Host::unwind` answers a bool, so a put-back that raised what the reference lets out of
  `delete_all` (a RecursionError of a crafted sign-in file) is a put-back that waits (PutBackWaits) here.
* `Edges::account_forget` (arming's sweep) is the integration's to point at `engine::account::forget` with
  `credentials::Secrets::windows`.
* The surfaces (S7.3a) read each code's `notice()` through `Code::as_any` downcast to `AccountWatch`/`AutoSwitch` and
  `notice_view()`; `control/autoswitch.switch` calls `AutoSwitch::put_in(target, now, true)`.

### For later seats

* S7.3a: `engine::autoswitch::best` is the card's next candidate; `swap::read_profile` the card's Read usage (it holds
  the saved accounts' lock itself); `codex::account::switch` with `account::Live` and `ProcessRunner` is the card's
  Switch; `swap::add_by_login` and `swap::save_current` the card's Add and Save.
* S7.4: the measurement hands (`MPROFILE`, `MSWAP`, `MALR`) take `swap::World`, `restart::Hands` and `account::Opener`
  as their seams; `account::Live::for_capability` makes a session of a capability's own, a measurement's is S7.4's.

### Gates

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast: every crate ok
                   after 71c00e4e9 (car-platform's golden test had caught the restart tests' own Command::new; car-platform
                   rerun alone: all ok); cargo deny: all four ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh            rc=0 at 71c00e4e9: every standard binary the same with and without advanced/;
                                                     profile-path scan: none
diffs (wait_quiet.sh)                                diffs_advaccount_{pure,files,swap,engines}: 22 tests, 1,538 cases, OK
Python (standard lane, wait_quiet.sh)                test_repo_hygiene test_privacy_bare_hosts test_privacy_claims test_no_console_windows: Ran 50, OK
privacy_scan.py on every file added                  clean
```

## Seat S7.2d: the usage meter, the wrap-up and the forced stop (branch `car-v0627-s72d`, 2026-11-27)

From `car-v0627-s72a` `8e6362cbf`. Reference: the v0.6.26 final on the bundled Python 3.14.10 (`engine/usage.py` is the
final's: FINAL-DELTA rows 25-30). P7-DESIGN 2.2 (this seat's nine files), 3.1, 7.

### Ported (module -> crate)

| Python (`advanced/src/codex_auto_resume_advanced/engine/`) | car-adv `engine::` |
|---|---|
| `continued.py` | `continued` (`answer_key` over any values as `str()` writes them, `words_pass`, `handed`; the one body is still `seam_p7`'s, S7.2a's port, so the two cannot differ - the integration points `seam_p7` here) |
| `wrapwords.py` | `wrapwords` (`check_custom`, `window_words`, `reset_words`, `render` with `Ask`/`Words`; Python's dict-by-hash lookups as `lookup`/`num_eq`) |
| `capacity.py` | `capacity` (`CapacityRetry`: P17, P3) |
| `earlyreset.py` | `earlyreset` (`EarlyReset`: P7, P3, `not_taken`, the four stamps and `check_asked`) |
| `resetwatch.py` | `resetwatch` (`blank`, `by_time`, `closed`, `advance`, `family_window`, `count`, `due`, `Watch` over `Resets` - the reset actions' `scoped.resets` with its writing/own guards -, `signal`; `Counter` is `seam_p7::ResetWatch` for S7.2b) |
| `credits.py` | `credits` (`ResetCredit`: P7, P8's errand; `Lazy`, `Opener`, `Keys`) |
| `resetmessage.py` | `resetmessage` (`ResetMessage`: P8, P2, P3, `watched_due`; `carried_by_stop`, `same_reset`, `handed`; `LongMessages`) |
| `usage.py` (**final**) | `usage` (`UsageMeter` with `SKIP_WAIT`, the backend kept for the told engine and `inuse::saw`; `UsageWrapUp`; `PauseCore`/`UsagePause`; `percent`, `reached`, `windows`, `credit_resets`, `changed_at`, `of_account`, `stale`, `reset_since`, `acting`, `touched`, `order_problem`, `previews`) and what the seat's codes share: `Bound`, `World`, `CodexReads`, `MeterBackend` |
| `usagestop.py` | `usagestop` (`UsageStop`: P8's errand, P3, `holds`; the stop, the continuation after the reset, the carried message (R2), `counts_here`, the notices; `Ipc`) |

Every registry `make` of these ids now answers a code (`usage_meter`, `usage_wrap_up`, `usage_pause` - the forced stop -,
`reset_credit`, `reset_message`, `long_reset_message`, `early_reset`, `capacity_retry`).

### How the codes are held

* A code's `Scoped` is reached through `usage::Bound` (the runtime's `Binding`, or a probe's own scope); a code whose
  P8 answer is an errand keeps its state in `Arc<Mutex<_>>` the errand shares (core runs errands last, on the tick's
  thread; the runtime's Gil is re-entrant there).
* What the reference reads of the outside is one `usage::World`: the catalogs, the local clock (`time.localtime`), the
  continuation language (`resolve_locale(settings.load(...))`), Codex's own files (`CodexReads`: `Turns(home)` and core's
  `LocalSource` with P19's widening), `inuse.home`, `inuse.backend` (`MeterBackend`), the capability's own session
  (`credits::Opener` -> `codex::session::Channel`), the spend key (`str(uuid.uuid4())`), the saved accounts' switch and
  the app's IPC channel (`usagestop::Ipc`).

### Seams left

* `usage::install_world(World)` is the entry points' (S7.3d): until it is called, `World::installed()` answers the
  product's defaults - catalogs in `<exe dir>\locales`, `l10n.current` "en", car-platform's `Crt`, the process's
  environment with no Windows language list (as car-control's system host), car-codex's reads over `PolicyOs`, the live
  discovery (`usage::system_backend`, product version from `car_config::codex::version(<exe dir>)`), real sessions, the
  Desktop's pipe - and **no saved-accounts switch** (`switched` answers None until S7.2b's `Host` is handed: the
  reference reads `profiles.last_switch_at()`/`intent()` there).
* The tests' own seams (`UsageMeter(app_running=)`, `session=`, `UsageStop(stop=, start=, home=)`, `UsageWrapUp(home=)`)
  are the World and the `home` fields; `app_running` has none (the product always looks through the backend) - the
  advanced proxy needs it for the tag's tests that pass one (AUDIT).
* Core's errand guard is a body scope; the IPC gate is asked mid-request: the request runs inside the guard (AUDIT).
* `seam_p7::{continued_handed, reset_message_handed, answer_key, words_pass, ResetWatch}` move here at the integration.

### The proof (`tests/rustdiff/advusage.py`, `diffs_advusage_{pure,codes}.py`, example `advusage`)

One request of ops runs through the tag's advanced edition (its classes, with the module attributes named in
`advusage.py` replaced by the same scripted world) and through car-adv's `advusage` example, on one scratch home made
again for each side; every answer, the world's log (each session call, IPC request with the gate's answer, Codex read
with its widening, backend check, in order), what each code keeps and `advanced.sqlite`'s dump are compared.

* `diffs_advusage_pure` (5 tests, ~9,800 cases): `render` over 900 generated asks (every style, window, locale, used,
  stop, reset, Custom text and their edges) + `check_custom`, `window_words`, `reset_words`; `answer_key`, `handed`,
  `words_pass`; 700 `advance`/`by_time`/`closed`/`count`/`due` walks + `family_window`; 300 option sets through
  `percent`, `acting`, `reached`, `order_problem`, `stale`, `reset_since` + `touched`; 500 `carried_by_stop`,
  `same_reset`, `counts_here` cases.
* `diffs_advusage_codes` (19 tests): capacity over 13 failures x 6 records x 4 clocks, bound and unbound; 6 early-reset
  walks of 160 steps and unhashable ids; the meter by test_advanced_meter_skip_wait's and ..._engine_elsewhere's steps
  (spaced skips, the kept backend checked again and dropped, a read within a wait of the app opening, unmatched with
  elsewhere kept/forgotten, warnings, samples, the account change) and 4 walks of 70 looks; the wrap-up (found, still
  due, superseded, Continue after the reset continued / superseded / handed over, every wording and locale, every read
  that fails); the stop (stop, hold, gate, holds, continue, every stop and start word, Continue off, a guard that
  refuses, the carried reset message for every start answer); the reset credit (spent, Use now, Ask me first, every
  consume answer, the session and guard failures, no count, no credit); reset_message (due, expired, cancelled, too long,
  watched, P3 holds, held by the stop).
* Mutation checks (scratchpad `car-v0627-s72d-mutate.py`: each alone, `advusage` rebuilt, the diff that holds it run,
  the file restored): the final's SKIP_WAIT shortened to 30 s; the backend kept for the told engine made afresh every
  look; `inuse.saw` left out of the meter's look; the weekly reset said without its date; a refused start of the carried
  message taken as sent; any refusal by Codex read as no such method; the capacity retry's default two hours made three;
  a message due before the stop carried by its turn: **8 of 8 caught**. Two survived the first pass and the diffs were
  widened until they were caught: DEFAULT_HOURS (a bound code reads the option's registry default - only an unbound one
  reads the constant: the diff now asks one 2.5 hours on the wall clock) and REFUSED_STARTS (a start word answered
  before the gate launches nothing, and the carry scenarios had no rule: `add_reset_rule` refuses a message without a
  record id - the diff now gives one and answers every start word after the gate).
* The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_s72d.py --reference v0.6.26`.
* The ledger: `python -X utf8 tests/rustdiff/advledger_s72d.py [--markdown]` - 25 advanced test files import an S7.2d
  module; their subjects are held by the two families above; none runs unedited on Rust yet (the advanced proxy is
  S7.2a3's, being built in car-v0627-s72a; 10 of the 25 also wait for S7.3a, one for S7.2e1).

### For later seats

* The integration: point `seam_p7::{continued_handed, reset_message_handed, answer_key, words_pass}` at
  `engine::continued`/`engine::resetmessage::handed`, and `seam_p7::ResetWatch` at `resetwatch::Counter`; S7.3d calls
  `usage::install_world` with the live world (S7.2b's accounts `Host` for `switched`).
* S7.3a (surfaces): `usage::{touched, order_problem, previews}` are `Edges::usage_touched/usage_order_problem/
  usage_previews`; `wrapwords::check_custom` and `PLACEHOLDERS` are `wording_problem`/`wording_placeholders`
  (`MAX_CUSTOM_LENGTH` the limit); the tray's meter and stop notices read `UsageStop::with(|s| s.notices(now))`.
* The proxy seat: `examples/advusage` already drives every S7.2d class from a request; the tag's tests that pass
  `app_running=` need a seam the World does not have yet.

### Checks (`CARGO_BUILD_JOBS=4`, reference v0.6.26 on the bundled 3.14.10, rustc 1.100.0)

```
diffs (scratchpad runner = run.py without its check for the standard harness, which these diffs do not use)
    diffs_advusage_pure + diffs_advusage_codes: Ran 24, OK (378 s)
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0; cargo deny rc=0
## advanced/rust   fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0 (car-adv 11 + 1); cargo deny rc=0
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh            rc=0, every standard binary the same with and without advanced/; profile-path scan: none
Python (standard lane, wait_quiet.sh)   test_repo_hygiene test_privacy_bare_hosts test_privacy_claims test_no_console_windows: Ran 50, OK
privacy_scan.py on every file added: clean

## Seat S7.2e1: what a carried turn does - the engine's capabilities for sends and turns (branch `car-v0627-s72e1`, 2026-11-27)

From `car-v0627-s72a` `8e6362cbf` (Integration 8 + S7.2a/S7.2a2). Reference: the v0.6.26 final. P7-DESIGN 2.2 and
S7.2e1's row (twenty `engine/` modules, 3,555 Python lines). **Nine of the twenty are ported and diffed; eleven are left**
(below, with what each needs).

### Ported (module -> crate)

| Python (`advanced/.../engine/`) | here (car-adv `engine::`) |
|---|---|
| `silent.py` | `silent` (P15: SILENT unless `codex::headless::EMPTY_REFUSED`) |
| `everyconversation.py` | `everyconversation` (P19: `{every_desktop}`) |
| `sessions.py` | `sessions` (P18 `{cli, ide}`, P16 TO_SESSION for `holder == "session"` without `queued_since`) |
| `parallel.py` | `parallel` (P12; `chosen_in`/`option_in`: Python's `in` over a tuple of ints, used by every Workers/Hours/Attempts option) |
| `oncemore.py` | `oncemore` (P7: car-policy `gates::resend_candidate`, `resent`, `channel_paid`) |
| `headless.py` | `headless` (P16 route, P8/`tend` `follow_up`; `RunWorld` - the seams; `Follows`, `TurnsReader`, `SharedRoute` = core's `Route` over S7.2c's `HeadlessRun`) |
| `compact.py` | `compact` (P17, P3 known_failure/thread_available, P16 compact/turn mode, P8) |
| `fallback.py` | `fallback` (P16 fallback mode with `owe`, `_defaulted`, P8 and the `Restore` errand inside core's guard) |
| `retries.py` | `retries` (`toml`, `overrides`, `fits`, `account_kind` - the one field of S7.2b's `codex::account::parse` read here -, P8 holding `codex::headless::hold_retry_settings`) |

### Left (not ported here: the seat's context ran out after the nine) - what each needs

`emptyreply` (P8 errand + P2; needs core's `LocalSource` (car-codex) judging a person's own conversation, `Goals`,
the continuations handle's `mine/get/note/add/end/last`, the global statement catalogs' text, seam_p7's
`continued_handed`/`answer_key`/`words_pass`), `keepgoing` (same family: `kept`, `stop_kept`, `plan_statuses`,
`View::thread_enabled`), `goal` (350), `subagent` (258), `markerfree` (202), `foropen` (150; seam_p7 `for_open_watching`),
`opentarget` (289), `steer` (224; the steers handle), `promptqueue` (372; seam_p7 `prompt_handed`, images), `chat` (145;
seam_p7 `chat_handed`/`chat_watched`/`paused_by_stop`), `admitted` (261; the four admission capabilities'
`make_*`). Each `make` is still the skeleton's None. The continuations handle methods missing from car-adv's
`Scoped::handle()` (S7.1a's: only `continuation`/`continuations_writing` are there) are best written beside the first
of these modules, as `follow_up` here calls the runs table's state functions directly.

### The proof

* **`advturns`** (example, `examples/advturns/{main,world}.rs`) and **`tests/rustdiff/advturns.py`** +
  **`advturnsworld.py`**: car-adv's runtime over the *shipped* definitions of the scenario (`capabilities`), each code
  made with the scenario's fakes (`seams`: a session's scripted answers, a conversation's turns and turn codes, the run
  follower's live run and ends, the unheld look), against the tag's `Runtime` over its own classes made with the same
  fakes. Arming confirms the statement's own warnings (`"AUTO"`); every compat capability the definitions name is in the
  view. Compared: every answer, every call a fake was asked (routes noted as capability, key, seconds, mode), every
  advanced.sqlite row at the end.
* `diffs_advturns_small.py` (AdvTurnsSmallDiff): 9 scenarios; `diffs_advturns_runs.py` (AdvTurnsRunsDiff): 23 scenarios
  (headless 3, compact 6, fallback 7, retries 6) - all equal (rc 0). The edges: off/watched/on, a record not a dict, a
  bad key, `app` 0 vs False, an option of 7 or "8", MQ passed, a claim time past a float, a failure not a dict, an
  ordinal that cannot be compared, turns that raise, a session that cannot enter, an update Codex refuses, a debt tried
  again within RESTORE_EVERY, settings lapsing after FRESH_SECONDS.
* Mutation checks (scratchpad `car-v0627-s72e1-mutate.py`: each rule broken alone, `advturns` rebuilt, its scenarios
  run, the file restored): silent answering SILENT after Codex refused an empty turn, other_sessions taking an item
  queued for opening, parallel_dispatch not held to 2 before MQ, once_more taking an int past a float as a claim time,
  follow_up never ending a row no thread follows, compact holding after a completed compaction, model_fallback trying
  a restore every tick, the retry settings held past FRESH_SECONDS: **8 of 8 caught**, none survived.
* The re-diff: `python -X utf8 tests/rustdiff/rediff_adv72e1.py --reference v0.6.26`. The ledger:
  `python -X utf8 tests/rustdiff/advledger_s72e1.py` (35 advanced test files reach an S7.2e1 module; 8 reach only ported
  ones; all wait for the proxy, S7.2a3).

### Seams left

* `RunWorld::bare()` (what `make(paths)` gives headless_run, compact_continue, model_fallback): the process's follower,
  no session (each open fails), app and unheld looks that raise, no turns. The entry points (S7.3d) hand the live world
  through `make_with`: `codex::headless::live_session` over `inuse::backend`, `Turns::new(inuse home)` as a
  `TurnsReader`, the app look and `Backend.holder` for `unheld_now`. Likewise `retries::make_with(open, monotonic)`.
* `SharedRoute::resume` hands `HeadlessRun::resume` no launch guard (core entered it first; AUDIT line).
* `capabilities::make` already names every one of these `make`s; nothing in the table changed.

### Gates

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0; cargo deny: rc=0
## advanced/rust   fmt --check rc=0; clippy rc=0 (after a62f53fd0); test --locked --no-fail-fast rc=0; cargo deny: rc=0
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh            rc=0, every standard binary the same with and without advanced/; profile-path scan: none
diffs (after a62f53fd0)                               AdvTurnsSmallDiff + AdvTurnsRunsDiff: Ran 2, OK (32 scenarios)
Python (standard lane, wait_quiet.sh)                 test_repo_hygiene test_privacy_bare_hosts test_privacy_claims test_no_console_windows: Ran 50, OK
```


## Seat S7.2e1b: the other eleven capabilities of sends and turns (branch `car-v0627-s72e1`, 2026-11-27)

Finishes S7.2e1 in the same worktree, from `1cfe007f8`. Reference: the v0.6.26 final through `advref` (the advturns
entry the first nine use; no interpreter of its own). **All twenty of S7.2e1's `engine/` modules are now ported and
diffed**; every `make` of table 2.2 for this seat answers a code.

### Ported (module -> crate)

| Python (`advanced/.../engine/`) | here (car-adv `engine::`) |
|---|---|
| `emptyreply.py` | `emptyreply` (P8 errand, P2) - and the family's seams: [`Looks`] (`Turns(home)` recent/latest/between/plan_statuses, `Goals(home).read`, core's `LocalSource(home).latest` with P19's widening, `Lineage(home).children`), `Words` (`statement.CATALOGS.text`), `LookWorld`, and `Continuations` (the reference's `ContinuationsHandle`: on/get/mine/last/add/note/end/kept/stop_kept) |
| `keepgoing.py` | `keepgoing` (P8, P2; `allowed`, every KeepReason stop) |
| `subagent.py` | `subagent` (P4 lines + `words_sent`, P8 follow-up once MS, P2) |
| `markerfree.py` | `markerfree` (P5 `MarkerFreeChannel`, P15, `carries`, `pools`; `send`/`queue_id`/`Open` reused by goal, promptqueue and chat) |
| `goal.py` | `goal` (P16 `GoalRoute`, P3 hold + VERIFIED_RESET, P5 `GoalChannel` where M2b passed; `GoalWorld`, `GoalLook`, `m2b_passed`) |
| `foropen.py` | `foropen` (P16 QUEUE_FOR_OPEN and its watch; `watching` - `seam_p7::for_open_watching` re-exports it) |
| `opentarget.py` | `opentarget` (P8 errand under core's guard; `OpenWorld` also implements `seam_p7::OpenTarget` for autoswitch) |
| `steer.py` | `steer` (P8 errand; `SteerWorld`; `outcome`) |
| `promptqueue.py` | `promptqueue` (P2, `watched_due`, P5 `ImageChannel`, P15, `images_of`; `handed` - `seam_p7::prompt_handed` re-exports it) |
| `chat.py` | `chat` (P2, P5 `ChatChannel`, P15; `handed`, `watched`, `paused_by_stop`, `TAKEN_WITHIN` - `seam_p7` re-exports them) |
| `admitted.py` | `admitted` (structured_rules, unknown_failure_budget, codex_gave_up, sign_in_retry: P17, P3, `rule_for`, `taken`) |

The core gaps the S7.2e1 section named: the continuations handle is `engine::emptyreply::Continuations` over
`Scoped` (S7.1a's `Scoped::handle()` is another seat's file: a named seam, nothing added there); core's `LocalSource`
and the goals reader are behind `Looks`/`GoalLook` (the live readers are the entry points', below); the global
catalogs' text is `Words`.

### The proof

* `tests/rustdiff/diffs_advturns_cont.py` (**AdvTurnsContDiff**): 64 scenarios over the same `advturns` example and
  `advturns.py` entry - empty 10, keep 6, subagent 7, marker-free 7, goal 6, for-open 5, open-to-send 6, prompts 7,
  steer 3, chat 2, admitted 5 - all equal: every answer, every call a fake was asked, every advanced.sqlite row. New
  fakes and steps (`advturnsworld.py` docstring, `world.rs`): the looks (`recent`, `between`, `plans`, `goals` - a
  list read in turn for goal_continuation -, `own`, `children`), the view's `thread_enabled` (`enabled`) and
  `records_in` (`core_records`, replaceable by a `seam` step), the PC (`pc`), the steer seams, `running`; the steps
  `seam`, `keep`, `kept_used`, `override`, `steer_add`, `prompt_add`, `chat_add`, `rule`, `admit`, `send`/`pools` (the
  P5 channel sent through once), `resume` (the P16 route resumed once). A session answer "timeout", "refused" or "no"
  (Codex's own refusal of that method) raises as the reference's does; a fake session with no `submit` is called
  whole, as `protocol.submitted` does (the first nine's scenarios still equal after that change: AdvTurnsSmallDiff
  and AdvTurnsRunsDiff rerun, OK).
* The edges: empty/damaged/wrong-type records and failures, a thread that is no text, kinds of count 0 and met
  twice, a turn too fresh, a shape that changed between looks, unreadable turns/goals/plans/lineage/between, goals
  active/blocked/paused, chains of one, two and three, words past 2,000 code points (é counted once), NUL, 30,000 and
  30,001 code points, upper-case uuids, every pipe word, caps of opens a day/record/conversation, watched and off.
* Mutation checks (scratchpad `car-v0627-s72e1-mutate2.py`, each rule broken alone, `advturns` rebuilt, its scenario
  run, the file restored byte for byte): empty_response making a chain's third, continuing past a goal Codex's loop guard stopped; keep_going sending past three before MK; subagent_parent counting its words in bytes; marker-free taking a queue id that is no uuid; goal_continuation holding half as long; queue_for_open keeping one queued on its last second; open_to_send opening a minute apart; steer_send writing a steer asked over two minutes ago; prompt_queue keeping an occurrence two days; codex_chat leaving a message in Codex's queue five minutes; codex_gave_up taking a task up three times: **12 caught**. Two survived, both unobservable through the runtime: subagent_parent's 2,000-character limit raised to 2,100 (the runtime checks P4's words against core's own limit too) and queue_for_open's DEFAULT_DAYS (arming stores the option's default, so the fallback is never read).
* Not reached by the harness (named, not diffed): subagent_parent's `words_sent` (core's claim is not driven by
  `advturns`; P11 is S7.2a2's), unknown_failure_budget's `taken` sample, a P3 known_failure answer that the runtime
  holds to its admission row, Longer messages on for prompt_queue (long_reset_message's own P2 is S7.2d's, still None),
  sign_in_retry's `categories` (an array here, a tuple there: AUDIT line), pictures (no copy is staged in a trace).
* The re-diff: `python -X utf8 tests/rustdiff/rediff_adv72e1.py --reference v0.6.26` (now with the eleven modules,
  what they read and AdvTurnsContDiff). The ledger: `PYTHONPATH=tests python -X utf8 tests/rustdiff/advledger_s72e1.py`
  - 35 advanced test files reach an S7.2e1 module, all 35 now reach only ported ones; all wait for the proxy (S7.2a3).

### Seams left (the entry points', S7.3d, through each module's `make_with`)

* `LookWorld` (emptyreply, keepgoing, subagent): the live `Looks` over car-adv's `codex::turns::Turns`,
  `codex::goals::Goals`, `codex::lineage::Lineage` and car-codex's `LocalSource` of `inuse::home`; `Words` over the
  shipped catalogs' directory (`statement::Catalogs::new`, the host's). Bare: every read raises, no words.
* `markerfree::Open` (marker-free, goal, prompt queue, chat): `codex::headless::live_session`-style opener over
  `inuse::backend` restricted to each capability's methods. Bare: no session ("not started").
* `GoalWorld` (goal, and its `goal` reader for queue_for_open): goals of `inuse::home`, M2b from the view and
  `compatdata::table_for`, `wall_clock`. `OpenWorld`: core's idle time, `control::opencodex::handler_registered`
  (S7.3a), `app_running_now`, `codex_link`, the loaded check. `SteerWorld`: `codex::ipc::steer_turn` with a bridge from
  car-policy's `Guards` to `ipc::Gate`, the turn history, `resource_users`, the loaded check. `TurnRunning`
  (prompt_queue). `admitted::Items` (`inuse::told` + `turn_item_counts`). Every bare world refuses or reads nothing.
* `seam_p7`'s chat/prompt/foropen helpers now re-export their modules (the runtime's names kept); its continued
  helpers stay (`engine/continued.py` is S7.2d's).

### Gates

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0; cargo deny: rc=0
## advanced/rust   fmt --check rc=0; clippy rc=0 (after 301f6af7f); test --locked --no-fail-fast rc=0; cargo deny: rc=0
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh            rc=0, every standard binary the same with and without advanced/; profile-path scan: none
diffs (release, run.py --build -k AdvTurns)           AdvTurnsSmallDiff + AdvTurnsRunsDiff + AdvTurnsContDiff: Ran 3, OK (96 scenarios)
diffs (debug, after 301f6af7f's safety prelude)       the same three families again: OK (9 + 23 + 64)
```
Safety (the main session's notice of 2026-11-27): every trace now runs with `CODEX_AUTO_RESUME_CODEX_EXE` at a path
where no codex.exe is, on both sides, and the reference's `inuse.backend`, `processes_named`, `resource_users` and
`process_identity` refuse wherever they were bound (`advturnsworld.refuse_discovery`). No Rust code of this seat
discovers or starts Codex: every `make` is bare (no session, no home), every trace's world a fake.

## Seat S7.2e2: time, fleet and the weekly look (branch `car-v0627-s72e2`, 2026-11-27)

From `car-v0627-s72a` `8e6362cbf` (Integration 8 + P6 contracts + S7.2a/S7.2a2). Reference: the v0.6.26 final
(`tests/rustdiff/advref.py`, the tag's advanced edition on `sys.executable`). P7-DESIGN S7.2e2's row, 2.2, 3, 4, 7.

### Ported (module -> crate)

| Python (`advanced/src/codex_auto_resume_advanced/engine/`) | car-adv |
|---|---|
| `supervise.py` (crash_restart, P13: SUPERVISE, RESTART, CAP in the HOUR, the stop flag waited on, `restart_gave_up`, `view`) | `engine::supervise` (`CrashRestart`, `Flag` over `win::stopflag::StopFlag`, `view`) - and `Bound`, what every S7.2e2 code is bound to: the runtime's `Binding`, or a harness's own `Scoped` (`Direct`) |
| `powertasks.py` (power_after_tasks, P21: the list file, `valid`/`read`/`write`/`remove`, `end_of`, `judge`, `PowerAfterTasks`) | `engine::powertasks` (`TurnHistory` over `codex::turns::Turns`; core's records through car-store's `Store::all_records`; the named lock car-platform `sync::Mutex`) |
| `wake.py` (wake_for_reset, P8: `earliest`, `apply`, `_windows_allows`, the watch) | `engine::wake` (`WakeForReset`, `Timer` over `win::waketimer::WakeTimer`) |
| `analytics.py` (usage_analytics, P8: the pass over rollouts, `pace`, `route`) | `engine::analytics` (`UsageAnalytics` over `codex::tokens`, `ProjectSource` over car-codex `LocalSource`) |
| `updatecheck.py` (idle_update_check, P8: `offer`, `said`, `english`, `encode`/`decode`, `run_check`, the kept offer) | `engine::updatecheck` (`IdleUpdateCheck`; `run_check` over car-platform `pwsh::executable` + `spawn::SystemStarter`; `communicate`, shared with the anchor) |
| `fleet.py` (fleet_view, P8: `clean`, `document`, `shown`, `folder_problem`, `write`, `read_peers`, the seen file, the bounded pass, `bounded` is the Dashboard's and not ported) | `engine::fleet` (`FleetView`, `Worker`, the file calls; statusfile through car-policy `settings::statusfile`) |
| `anchor.py` (window_anchor, P8: every pure function, `declared_servers` over tomllib, the request, `WindowAnchor`, `view`) | `engine::anchor` (`WindowAnchor`, `RequestBackend` over car-codex `transport::Backend`, `UsageSession`; `anchor::toml` - tomllib's TOML 1.0, written here: no crate in the locks reads TOML and no seat adds one) |

No new dependency, no `mod.rs`/`lib.rs`/`Cargo.toml` touched. Nothing real is armed in a test: the stop flag and the wake
timer are made over car-platform `wake`'s `System*` only by the product's `make`, lazily, as the reference makes them;
every diff hands its own.

### Seams left (the product's `make` names a default for each)

* crash_restart `notify` (`gave_up_notice`: `config.load_settings`, `settings.notification_enabled`, `notifier.build` /
  `deliver`): `no_notice` (not shown) until S6.1/S7.3d hand core's notifier.
* idle_update_check `installed` (`config.version()`) and `log` (core's logbook): None and not written until the entry
  points hand them; `managed` reads car-platform's policy places as an installed copy does.
* fleet_view `status` (`_status_now`: core's store, settings and version through `statusfile.content`): `no_status`
  (every pass HELD) until the entry points hand it; `guarded` is `guarded_homes` (the home, `inuse.home`, `codex_home`).
* window_anchor `session` (`protocol.Session` entered), `backend` (`inuse.backend` over the live `Discovery`) and `log`:
  none until S7.3d (no read: every occasion held `unreadable`; `told` is `inuse.told`).
* wake_for_reset and window_anchor's watch/wait threads: `thread_start`/`thread_begin`; fleet's `thread_spawn`.
* `bounded(call, bound)` (fleet.py) is the Dashboard's save (control/fleet, S7.3a): not ported here.

### The proof (`tests/rustdiff/advtime.py` + `diffs_advtime_{supervise,power,wake,analytics,update,fleet,anchor,anchor_code}.py`; example `advtime`)

One request of cases answered by the tag's own classes (the reference script in `advtime.py`) and by car-adv's example
`advtime`; capability cases bind the code to a real `AdvancedState` on a scratch home through `state.scoped(...)`
(Rust: `Bound::Direct`), every seam a scripted stand-in that logs its calls, and the harness compares every answer,
every call in order, every row of advanced.sqlite (dumped by the harness) and every file a case names, byte for byte
(`Scene`: the same folders, seeded again between the sides; `first_difference` names where two answers part).

All against the v0.6.26 tag, 19 tests, every one OK (scratchpad logs `car-v0627-s72e2-d1..d7.log`):

```
diffs_advtime_supervise    2 OK: 406 walks of P13 facts (start, ended with every exit code and `clean`, garbage), flag
                           scripts (hold/signalled/wait answers and raises), restart rows in and out of the HOUR, the notice;
                           47 `view`s over every shape of unsupervised.txt
diffs_advtime_power        5 OK: `valid` over ~1,100 documents and mutants; `read`/`write`/`remove` (~95: BOM, not UTF-8,
                           too large, deep, a folder, the bytes left); `end_of` over 900 generated chains; `judge` 401; P21 300
diffs_advtime_wake         1 OK: 503 walks (rules, meter pauses, anchor stamps, lead, timer set/cancel/allowed and raises,
                           the watch's looks past STALE, ASK_EVERY, turned off, window_anchor armed and not)
diffs_advtime_analytics    2 OK: 250 walks over generated rollouts (pinned mtimes, PASS_SECONDS cuts, MTOK failed, project
                           keys short/none/raising); 505 `pace`/`route`
diffs_advtime_update       2 OK: 400 walks (offers kept, dropped by the version installed or put away, LOOK_EVERY, WEEK,
                           the administrator's switch, a start that raises, a check never run); ~1,250 `offer`/`said`/
                           `english`/`encode`/`decode`
diffs_advtime_fleet        3 OK: ~300 pure and file cases (clean/document/shown/within/folder_problem/write/read_peers/
                           remove_old_name/seen), a junction; 300 walks (LATE past BOUND, held passes, wordings, NOT_OURS)
diffs_advtime_anchor       1 OK: ~1,450 pure cases under the process's zone, JST-9 and EST5EDT (summer-time changes)
diffs_advtime_anchor_code  3 OK: 941 config.toml documents (tomllib's every acceptance and refusal), 237 walks of the
                           capability with 12 whole request paths (a real child of the test's own, its argv compared), 6 views
```

The first runs differed three times: once in the port (`powertasks::cut_off` took the earliest by a scan, where the
reference's sort raises TypeError on keys that cannot be ordered - fixed in `5a92ed130` by replaying CPython's sort), and
twice in the harness (the wake timer stand-in forgot its time before its raise; the junction case's expectation).

### Mutation checks (scratchpad `car-v0627-s72e2-mutate.py`: each alone, `advtime` rebuilt, its diff run, restored)

`CAP` 3 -> 4 (SuperviseDiff), a failed task always counted (PowerTasksDiff.test_judge), the lead a person chose ignored
(WakeDiff), PASS_SECONDS 2 -> 3 (AnalyticsDiff), a pre-release offered on `current` only (UpdateCheckDiff.test_pure),
QUIET two passes instead of three (FleetPureDiff), STEADY_GAP 20 -> 10 (AnchorPureDiff), a repeated TOML key accepted
(AnchorTomlDiff): **8 of 8 caught**, none survived.

### For later seats

* S7.2a / S7.3d: each capability's `make` is in place; hand the seams above where the entry points have the world.
  `supervise::view`, `anchor::view` take what the runtime knows (armed, the stamps) - S7.3a's surfaces call them.
* S7.3a: `fleet::{read_seen, waiting_word, shown, clean, alias_valid, folder_problem, remove_old_name}`,
  `updatecheck::IdleUpdateCheck::offered`, `analytics::{pace, route}`, `powertasks::{read, write, remove}` are the
  control side's.
* The proxy (S7.2a3): `tests/rustdiff/advledger_s72e2.py` lists the 24 advanced test files these modules unlock and what
  each waits for; the classes' seams are the constructors' keyword arguments, one for one.
* The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_adv72e2.py --reference v0.6.26`.

### Gates (`CARGO_BUILD_JOBS=4`, `. tools/rustflags.sh` first; rustc 1.100.0; code at `03ab637c4`)

```
## advanced/rust   fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0 (after 03ab637c4); test --locked
                   --no-fail-fast rc=0; cargo deny --locked check: all four ok
## rust            fmt --check rc=0; clippy rc=0; test --locked --no-fail-fast rc=0 (73 results, all ok); cargo deny: ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh            rc=0, the standard binaries the same with and without advanced/;
                                                     profile-path scan: none in any .exe, .dll or .pdb
after the clippy fix, its paths re-diffed            wake, anchor pure, anchor code (3), update (2): Ran 7, OK
privacy_scan.py on every file added                  clean
Python (standard lane, wait_quiet.sh)                 test_repo_hygiene test_privacy_bare_hosts test_privacy_claims test_no_console_windows: Ran 50, OK
```

## Integration 10 (branch `car-v0627-rust`, 2026-11-27)

Six branches merged with `git merge --no-ff`, both sides kept, in this order; then one commit per step.

| Merge | Branch | What came in |
|---|---|---|
| `46c8fdb20` | car-v0627-s72a `694216d34` | S7.2a's skeleton, the plug's two halves, P2's records, P12's pool, P11 inside the claim, the launch guards, the advanced proxy (advserve, `tests/rustdiff/advproxy/`) |
| `becc889b9` | car-v0627-s73b `c610f41c1` | S7.3b: the courier and the remote reach (WinHTTP, Schannel, the hand-written server) |
| `cb09e44e8` | car-v0627-s72b `55cfaef03` | S7.2b: the saved accounts, the account switch, its Windows acts |
| `1f3aa982c` | car-v0627-s72d `b3fb850db` | S7.2d: the usage meter, the wrap-up, the forced stop |
| `402b6a221` | car-v0627-s72e1 `a8469f3b1` | S7.2e1/e1b: the engine's capabilities for sends and turns |
| `33614be47` | car-v0627-s72e2 `25c353ad3` | S7.2e2: time, fleet, the weekly look |

Conflicts: `rust/GROUNDWORK.md` alone, in every merge (each seat's sections appended in merge order; where two copies of one
section differed, the newer one - Integration 9's Integration 8 section, s72a's finished S7.2a section - was kept). No P7
seat builds a car-control `Control`, so nothing needed Integration 9's `Arc<Guarded>`.

### The bundled 3.14.10 for every advanced family (`a779234d3`)

The P7 families (`advaccount`, `advusage`, `advturns`, `advtime`, `advcourier`, `advplug`, `advreport`, `advhook`, `advcodex`)
start the reference through `advref.run` / `refpython.command`, which Integration 9 routed; `test_rustdiff_script_command`
now holds each of their files. The advanced proxy's two lanes (`advproxy/ledger.py --run`) run scripts/test_parts.py's worker
through `refpython.script_command` on the reference's Python (bundled by default, `--reference-python`); a bare `--run` runs
every GREEN and ready file and prints the GREEN count. `core.build_rest` builds `advserve`, `advcourier`, `advaccount`,
`advusage`, `advturns` and `advtime` with the other examples.

### No reference run reaches this PC's Codex (`fdb1aadba`, `c68c34f4a`; `tests/rustdiff/refguard.py`)

Every process `refpython.command` / `script_command` starts (so `reference.run`, `advref.run`, `popen`), on any runtime, and
tests/released.py's `run`, runs refguard's program before the script: `win.kernel.processes_named`, `process_identity`,
`package_roots` and `win.inventory.resource_users` - and every module's binding of them - and the advanced
`codex.inuse.backend` refuse with the tag's AdapterError; `CODEX_AUTO_RESUME_CODEX_EXE` points where no codex.exe is
(`reference.scratch_environment` sets it for both sides over whatever the runner inherited); no codex program starts from
outside the temporary folder (`subprocess.Popen` refuses it). A stand-in a script sets wins. Two named ways out:
`live-processes` (platform_live_diffs alone: the lookups are the tag's, the rest stays) and `discovery` (the files of
`refguard.DISCOVERY_SUBJECTS` alone - `tests/rustdiff/advcodex.py` - through `refguard.discovery_environment`: every home and
program-files root inside the scratch tree, PATH Windows' own folders, checked before the script (exit 97); the real
`inuse.backend`, no engine path, the lookups still the script's stand-ins; whatever `config.discover_codex_exe` finds and
whatever codex starts must lie inside the tree). The proxy's lanes are test lanes with tests/no_real_codex.py (`guard=False`).
`tests/test_rustdiff_refguard.py` (16 tests) holds all of it on the system and bundled Pythons, a planted real-looking engine
outside the tree included. Mutation checks: 7 of 7 (resource_users not refused, inuse left alone, the runner's engine path
inherited, an early stand-in refused, an installed interpreter without the boot, released.run without it, the live variable
lifting inuse) and 4 of 4 (an engine outside the tree handed back, the Popen door open, a home off the tree unchecked,
package_roots not refused). The first full run went red on `diffs_advcodex_inuse` (inuse.backend is its subject): the
discovery opt-in above is the fix (InuseDiff 4 OK); no other family needed it.

### The seams between the P7 seats (`09fc4ab32`)

engine/continued and engine/resetmessage hold their bodies (moved out of `seam_p7`); the runtime's P2, emptyreply,
keepgoing and subagent call them; the runtime reads each S7.2e1 module's `CAPABILITY`, `chat::watched`,
`promptqueue::handed`, `foropen::watching`. engine/account counts a rule by `resetwatch::count` (the `ResetWatch` trait,
`TagCount` and `Counter` are gone); engine/retries reads `codex::account::parse`; anchor's `ON` is `wrapwords::ON`; chat
reads `usage::PAUSE`, emptyreply `usage::EVERY_CONVERSATION`. car-codex `pairing::own_pids()` (with a unit test) is
`swap::Live`'s `own`. `engine::account::forget_real(state)` is what `Edges::account_forget` calls (the host's Edges, S7.3d).
`seam_p7` keeps `OpenCodex` (S7.3a) and names the S7.4 rows. Mutation checks, 5 of 5 (debug examples, each diff run):
own_pids empty (car-codex unit test), a reset message handed as a continuation (MessageDiff), a held rule counted from
nothing (AccountWatchDiff), retries seeing no account kind (AdvTurnsRunsDiff), a continuation in flight sent at its claim
first (ContinuedDiff); all green restored.

### Checks (`CARGO_BUILD_JOBS=4`, `CARGO_INCREMENTAL=0`; reference v0.6.26 on the bundled 3.14.10; rustc 1.100.0)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0; cargo deny: all four ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
run.py --build --reference v0.6.26 --reference-python bundled -v
                                                     Ran 448 in 8,659 s: 2 FAIL, 1 expected failure (diffs_review6's
                                                     fresh home), no `released:` rebuild. FAIL: the two HistoryNotYet cases
                                                     (compat_io ProbesDiff.test_source_and_api_checks, codex_homes
                                                     HomeDiff.test_schema_variants), the final-port seat's (Integration 11).
                                                     No red from the guard.
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0: every standard binary the same with and without advanced/,
                                                     profile-path scan none in any .exe, .dll or .pdb
the 15 frozen modules (test_parts --worker; CODEX_AR_CORE=rust)    456 pass on both, 0 differ (Python 239 s, Rust 236 s)
advproxy/ledger.py --run (bare: GREEN + ready, bundled 3.14.10)    GREEN 9 of 32: the 7 GREEN files again, and two ready
                                                     ones newly green (test_advanced_agent_thread_trigger,
                                                     test_advanced_package: into GREEN). The 23 others are ready by their
                                                     imports but reach S7.2b/d/e1/e2 code no table.py row forwards yet (16
                                                     differ) or no forwarded code at all (7, calls {}): their seats' proxy
                                                     rows are still to write.
InuseDiff after the discovery opt-in                 Ran 4, OK
Python guards (standard lane, wait_quiet.sh): test_repo_hygiene test_privacy_claims test_privacy_bare_hosts test_edition_audit
  test_srcscan test_stack test_layers test_structural_invariants test_rust_release test_rust_power_guard test_rust_install
  test_rustdiff_reference_python test_review9_install test_host_contract test_python315_encoding test_rustdiff_script_command
  test_rustdiff_refguard test_no_console_windows        Ran 233: 1 FAIL (test_python315_encoding: advledger_s72a.py's
                                                     git ls-tree named no encoding; fixed), then test_python315_encoding
                                                     test_repo_hygiene OK
```

### For the next seats

* **Integration 11** (S6.2b3, S6.4b, the final-port, S7.4): the two HistoryNotYet reds are the final-port's. A diff whose
  subject is core's discovery goes into `refguard.DISCOVERY_SUBJECTS` and builds its environment with
  `refguard.discovery_environment` - nowhere else; every other reference run refuses the lookups and the engine.
* **S7.2b/d/e1/e2's proxy rows** (Q3 (c)): `ledger.py --run` lists 23 ready files not green; each needs its module's
  forwarders in `advproxy/table.py` (S7.2a3's how-to). `ledger.py --seat <seat>` lists what waits.
* **S7.3a**: `seam_p7::OpenCodex` is the one edge left; **S7.3d**: the host's `Edges` calls
  `engine::account::forget_real`, `control::hookplugin::follow_real`, and hands the runtime its state.

## Final port (seat finalport, branch `car-v0627-finalport`, 2026-11-27)

Base: Integration 9 `cfdabfe59`. The rows of `outputs/plans/v0627-rust/FINAL-DELTA.md` whose crates exist, ported from the v0.6.26
tag itself; FINAL-DELTA section 12 says where every row stands and who owns the rest. Reference v0.6.26 on the bundled 3.14.10.

| FINAL-DELTA | Python (v0.6.26) | Rust |
|---|---|---|
| #1, #10 | `codex/errors.py` `HistoryNotYet(SourceError)` | car-codex `errors.rs`: `SourceError(message, not_yet)`; `SourceError::history_not_yet`, `is_history_not_yet`, `class()` "HistoryNotYet"; `Error::history_not_yet`, `Error::is_history_not_yet`. It stays `Error::Source`, so every catch of the refusal catches it, as `except SourceError` does |
| #2-#4 | `history.py` `_no_conversation`, `schema.py` `resolve`'s `elif`, `_history_not_made` | `source.rs` `no_conversation` (through `with_db("state")`), `history_not_made` (any error: no), `resolve` (only where no history file exists) |
| #5 | `compat/probes.py` `source_checks` | `compat/probes.rs`: `threads: Option<bool>`; a missing history with `Some(false)` is NOT_APPLICABLE for `history_schema` and `projection_table`; the lock folder FAILs on `Some(true)` only |
| #6 | `win/kernel.py` `package_roots` | car-platform `kernel::package_roots` (GetPackagesByPackageFamily, GetPackagePathByFullName; `Win32_Storage_Packaging_Appx` was already a feature); car-codex `System::package_roots` |
| #7 | `codex/pairing.py` `package_engines`, `PACKAGE_ENGINE_DEPTH` | `pairing.rs` `package_engines`: scandir as CPython (a junction is a folder, a symbolic link neither, partial listings kept), then `package_file` + `engine_row` + `!main_place` as written and resolved |
| #8, #9 | `probes._package_engines`, `views._binding_holds` | `probes::package_engines` + `probes::official` (the generator's lazy filter); `views::binding_holds` asks the package's engines between the candidates and the served ones |
| #11 | `engine/detect.py` `collect` | car-engine `detect.rs`: `Err("HistoryNotYet") => return Ok(())` |
| #15 (+ #12) | `control/watcher.py` `get_status`, `domain/usage.newest` | car-control `status.rs`; car-machine `domain::usage::newest_made` (Some only where the rule made a new object: the reference tests `is not`), `newest` over it |

**Seams.** (1) `System::package_roots` is a required method: every world names its own package folders (car-harness `World` and car-adv's
example world read `packages`; the test stands and car-engine's/car-adv's empty systems answer none). A new `System` must answer it, never
with this PC's packages (`tests/no_real_codex.py` `_guard_packages`). The reference worlds stub `pairing.package_roots` the same way
(appserverdiff, advcodex, advcodexd): before this seat they asked this PC's real package manager. (2) A caller that tells HistoryNotYet
apart asks `Error::is_history_not_yet()` (or meets the class "HistoryNotYet" where errors are class names, as car-engine's `Py`).

**For the next seats.** S6.2b: `Outside::history` (car-bin doctor, #19) maps `is_history_not_yet()` to `History::NotYet`; the watcher's
`checkup::_conversations` (#17) skips a home on it before the generic "cannot be read"; `_served_elsewhere` (#18) is the EngineMaker's, with
S7.2a's plug hook. S7.2a/S7.2: rows 24-30 (AdvancedPlug.served_elsewhere, the UsageMeter's SKIP_WAIT, `_skipped_at`, `_held`, `_backend`).

**Mutation checks** (one rule broken at a time, a debug car-harness in a target of its own, its diff run, restored;
`scratchpad/car-v0627-finalport-mutate.py`): (1) an unknown `threads` counted as none: ProbesDiff; (2) resolve without
HistoryNotYet and (3) `history_not_made` yes where the state cannot be read: HomeDiff.test_schema_variants; (4) car-engine's
catch dropped: EngineReview6; (5) get_status never rewriting the usage - it first SURVIVED (every meter's `reset_at` was the
golden float clock, which core never keeps, so neither side rewrote anything); the diff's times are whole now and it fails
unless more than 20 cases say the meter's reading (54 of 170), and then 51 cases failed; (6) PACKAGE_ENGINE_DEPTH 3, (7) a
junction not followed, (8) the binding not asking the package: PackageEnginesDiff. All eight fail their diff.

**Checks** (rustc 1.100.0; reference v0.6.26 on the bundled 3.14.10; run with `CODEX_AUTO_RESUME_CODEX_EXE` naming a path that
does not exist, the main session's rule of 2026-11-27):

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0;
                   cargo deny --locked check: advisories, bans, licenses, sources ok
## advanced/rust   fmt --check rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny: all four ok
python -X utf8 rust/tools/check_groundwork.py        OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0, every binary the same with and without advanced/; profile-path scan none
run.py --build --reference v0.6.26 --reference-python bundled -v
                                                     Ran 372 tests in 8,642 s: OK - no FAIL, no expected failure (the two
                                                     HistoryNotYet reds and diffs_review6's expected failure are gone)
Python (standard lane, wait_quiet.sh): test_repo_hygiene test_privacy_claims test_privacy_bare_hosts test_python315_encoding
  test_rustdiff_script_command test_rustdiff_reference_python test_rust_release test_stack test_srcscan   Ran 95, OK (1 skip)
```
## P6 S6.2a: the window's switch from Python to the Rust core (seat S6.2a, branch `car-v0627-s62a`, 2026-11-26)

Cut from `car-v0627-cifix` `6a72bb487` (Integration 8 + P6 step 0 + the CI fixes). P6-DESIGN 1.7 (every row), 1.8, 4.1 row
1b, the owner's Q4 (a Rust launcher at today's path) and Q6. The wire does not change (D12): `tests/test_consumer_fields.py`
and `tests/golden/bridge` are untouched (`test_window_core` checks it against the base). Nothing pushed; no window shown
outside the GUI lock; no picture made.

### What is where

| Today (v0.6.26) | Now |
|---|---|
| `RuntimeChoice.Python`/`BundledPython` (the bridges, the launchers) | `gui/CoreExe.cs`: `CoreExe.Path(root)` = `root\app\bin\codex-auto-resume.exe`, in `[installer]` (the setup programs are compiled with it too). `RuntimeChoice.cs` deleted, its `[settings]` line gone |
| one-shot bridge `python -X disable-remote-debug -c CODE app\src <cmd> [-]` | `codex-auto-resume.exe bridge <cmd> [-]`: the argument on stdin as before, `UseShellExecute=false`, `CreateNoWindow=true`, the same limits; `Bridge.Available` = the core is there; `Bridge.Core` for the long-lived one |
| long-lived `... serve`, and after three failures the move from a chosen Python to the bundled one (v0.6.23) | `codex-auto-resume.exe bridge serve` from `once.Core`; three failures give it up for `RetryMilliseconds`, as before v0.6.23 (no other program to move to; `UseBundled` gone) |
| Repair `runtime\python.exe app\scripts\plugin_setup.py setup --keep-state` | `codex-auto-resume.exe setup --keep-state`; the install lock, `CODEX_AUTO_RESUME_PLUGIN_HOME`, the five outcomes unchanged; "incomplete" = no core |
| the Desktop shortcut `python plugin_setup.py desktop-shortcut make|remove` | `codex-auto-resume.exe desktop-shortcut make|remove` (`DesktopShortcut.Change`); no core = `NotChanged` |
| strings cache key `"2"`, plugin.json, five `.py`, the catalogs | `"3"`, plugin.json, `app\bin\codex-auto-resume.exe`, the catalogs at `app\src\codex_auto_resume\locales` (their shipped path) |
| `ChildTree.Spared = "pythonw.exe"` | `Spared = { "CodexAutoResume.exe", "pythonw.exe" }`, `IsSpared(image)` (ordinal, case ignored) |
| `gui/McpLauncher.cs` (+ `RuntimeChoice.cs`) built by `make_gui.ps1` | car-bin's `codex-auto-resume-mcp.exe` (D18, already Integration 8's); `McpLauncher.cs` deleted; `make_gui.ps1` builds the window alone; `gui_stamp.py` has the one kind `window`; `make_release.collect_gui` takes the launcher from `rust/target/release` (`RUST_BUILT`), as `rust_release.py` does |
| `gui/HookLauncher.cs` (advanced, never packed) | car-adv-bin's `codex-auto-resume-hook.exe` (`src/bin/hook.rs` over `src/hook_launcher.rs`): `codex-auto-resume.exe hook --home <home>` through car-platform's one starter, three piped streams, input on its own thread, stderr dropped, the 8 s bound, only an exit 0 relayed, every way out 0 (a panic too). Built in the advanced workspace only and **not packed**, as v0.6.26's advanced archive does not carry the C# one; car-adv-bin gains the car-platform edge (check_groundwork) |

No `.py` is named in a string the window's code holds but the advanced sentinel `__init__.py` (InstallerFlow's
`EditionOfSource`/`EditionOfArchive`); comments still cite the Python a rule was ported from. `advanced/gui/AdvancedPythons.cs`
is S7.3's (D8) and untouched.

### The tests (each fails with the change reverted)

* `tests/test_window_core.py` (new): the four starts read from the source (`bridge`, `bridge serve`, `setup --keep-state`,
  `desktop-shortcut`), the key, the spared images, the `.py` scan, the compile lists, the wire untouched; a probe compiled
  from CoreExe.cs, ChildTree.cs, WindowJson.cs and HostApp.cs runs the path, `Under` over a made-up process table (host and
  car-legacy's pythonw spared with their subtrees, any case) and `StringsCache.Key` over a scratch installation (starts
  `"3|"`, follows the core's and the catalogs' bytes, not a `.py` of the old package, a missing core is `-`).
* `tests/corestandin.py` (new, not a test module): the window tests' stand-ins take only `bridge serve` / `bridge CMD [-]`
  (anything else exits 64) at `app\bin\codex-auto-resume.exe`; the one-shot audit's tree also starts a `CodexAutoResume.exe`,
  which must be spared (`test_gui_v0620_audit`).
* `tests/test_hook_launcher.py` (rewritten): source rules of the Rust launcher, and the built `codex-auto-resume-hook.exe`
  run against a C# stand-in core in the C# launcher's five cases (relayed whole with its input and the role's words, failed,
  quiet, nothing installed, hung past the bound); skipped by name where cargo has not built it. car-adv-bin's own 10 unit
  tests (cmd.exe children: relay, stderr, failure, bound, endless input, a pipe held past the exit, cannot start).
* Retargeted: test_chosen_runtime, test_remote_debug_off, test_no_console_windows, test_structural_invariants,
  test_convergence, test_guiscan, test_tooling_round2, test_edition_build, test_edition_window, test_reproducible,
  test_gui_layout, test_gui_decisions, test_desktop_shortcut, busycase and six window modules' stand-ins.

### The re-diff

`python -X utf8 tests/rustdiff/rediff_window.py --reference v0.6.26`: the window's ported files and the bridge's wire changed
since the final (`git diff --stat`), then test_window_core, test_hook_launcher, test_consumer_fields and `cargo test --locked
-p car-adv-bin`.

### For the next seats

* **The integration / S6.2b**: `codex-auto-resume.exe` is still the stub core (`car_bin::core_main`, Integration 8), so an
  installed window's bridges get `NOT_PORTED` until `main.rs` runs `main_with(&[])`; the window is ready for that switch and
  needs nothing else. `bridge serve`'s set-aside sweep is the watcher's (S5.2's list).
* **S7.3d**: register the `hook` role in car-adv-bin's `main` (`main_with(&[Role { word: "hook", run }])`, `run` over
  `car_adv::hook::handler::main(argv, stdin, stdout, None, Some(live hands))`), and pack `codex-auto-resume-hook.exe` at
  `payload/app/hook/` with the release's word when the capability is shown.
* **S8 (the release)**: `.github/workflows/release.yml`'s Python archive steps now need car-bin's launcher in
  `rust/target/release` (make_release says how to build it); the Rust release is `rust_release.py`.
* car-bin's `launcher::install_home` answers a relative path with no USERPROFILE (AUDIT-v0628, S6.2a); the hook launcher asks
  `home_dir` as the C# launchers did.
## P6 seat S6.3: the surfaces the C# host draws, their plans (branch `car-v0627-s63`, 2026-11-26)

### S6.3 done (seat S6.3f, 2026-11-27): what is proved, by which test, and what B and C need

Every surface P6-DESIGN 2.3 names is C# on `gui/host.sources` `[surface]` (38 files), `HostSurfaces` implements
`ISurfaces`, and the host's render mode and probe mode are in (`SurfaceRender.Run()`, `SurfaceRender.Probe(args)`).
Nothing was shown, captured or drawn on a screen; no picture was made; nothing was pushed.

| What is proved | By |
|---|---|
| Comparison A, the plans: popup, menu, tip, card (+ shadows, stack, lives), placement, popup motion, icon frames, paint, shape, GDI+ painter, elevation, days, bidi at Unicode 16.0.0, and every surface's pixels drawn offscreen by the reference's renderer and by the C#'s, byte for byte, 0 GDI+ objects left | `tests/test_surface_parity.py` (21 tests, exact) |
| The windows' halves over windows never shown, the reference driven with its window calls stood in: the icon's words, where Windows keeps the icon, the tip card, the popup, the drawn menu, the card stack, the icon (shell, session, tooltip fallback, menu, MSAA), the surfaces' class | `tests/test_surface_windows.py` (8 tests, exact) |
| The live-path proof (P6-DESIGN 3.3's last paragraph) for every window: its own paint offscreen == the render mode's drawing of the same input == the reference's paint, byte for byte, the plans equal, 0 GDI+ objects left - the tip (`tipwindow/`), the popup (`popupwindow/`), the drawn menu and its submenu (`menuwindow/`, six proofs a run, five runs) and the notification cards (`cardstack/`, ten proofs a run over every card on screen, four runs; each proof also holds in the reference itself) | `test_surface_windows` |
| The retargeted picture makers: over the committed popup-en and hover-card plans' frames the popup's and the hover card's makers call the render mode with the same calls and arguments as the reference's renderer; the card's maker says the reference's motion, marks, breaths and paints; a real render-mode session lays the popup out as the reference does, answers every call and leaves 0 GDI+ objects | `tests/test_surface_render_retarget.py` (4 tests) |
| The re-diff against the final | `python -X utf8 tests/rustdiff/rediff_host_surface.py --reference v0.6.26` (exact) |
| The shipped window unchanged | `make_gui.ps1` on `git archive` trees of `b1761926b` and of this head, both editions: every `.exe` byte-identical (`ec1ae342...`, `101f257d...`, `382bbb9c...`) |

**What comparisons B and C need from the main session** (on the picture machine; agents never run them):

* **B (stills)**: `CODEX_AR_SURFACE_RENDER=1 python build/make_screenshots.py` - `render_popup`, `popup_picture` and
  `_SettledCard` (so `render_card`/`card_pixels`) then draw through the render mode (`build/surface_render.py`; the
  surfaces compiled once into `%TEMP%\car-surface-render\<digest>`, or `CODEX_AR_SURFACE_EXE` naming a built host). Each
  committed `tray-popup*.png`, `notification-card*.png`, `design-{classic,plain}-{popup,card}.png` must come out byte for
  byte; any frame that differs is a finding for the owner (Q9), never a tolerance. `status-light.png` and `icon.png` are
  drawn from brand's own arithmetic and the icon's frames, not by a renderer: they are unchanged by the switch (the icon's
  frames are held by comparison A's `icon` cases). Then move each picture's staleness digest (`POPUP_CODE`, `CARD_CODE`,
  `popup_drawing`, `card_drawing`) from the `.py` files to the `[surface]` C# sources - not done here (it is the pictures').
* **C (motion)**: `CODEX_AR_SURFACE_RENDER=1 python build/make_motion.py <plan>` for `popup-*`, `card-*` and `readme-*`:
  `PopupFrames`, `TipFrames` and `CardFrames` get one session (their `render=`), the plans unchanged; the APNG bytes must
  equal the committed ones. A card frame whose motion the render mode answers otherwise than the reference's arithmetic
  stops the run (`surface_render.Card.paint`).
* **Expected stale until then**: this part edited `build/make_screenshots.py` (an input of every window still) and
  `build/make_motion.py`, `motion_card.py`, `motion_popup.py`, `motion_tip.py` (inputs of the motion pictures), so
  `test_motion_fidelity`'s made-picture digests (readme, card, popup x en/ko) and `test_screenshots`' recorded inputs read
  stale until the main session makes the pictures again; no picture was regenerated here (rule 4).
* **Left for later seats**: the ledger rows (`tests/rustdiff/surface_ledger.json`) are S6.4's; the host's `Main` (S6.2b)
  asks `SurfaceRender.Run()` and `SurfaceRender.Probe(args)` before any DLL loads.

Cut from `car-v0627-p6abi` `b1761926b` (Integration 7 + P6 step 0). `outputs/plans/v0627-rust/P6-DESIGN.md` 2.3 (the module map),
3 (the proofs) and 4.1 row 1c, under the owner's Q1 (C# owns layout, motion, stack, shadow and corner), Q8 (the same flat GDI+/GDI
calls) and Q9 (pictures byte for byte). No Rust changed. No window was shown, nothing was drawn on the screen or captured, no picture
was made; `gui/window.sources`, every file it lists and `build/make_gui.ps1` are byte-identical to `b1761926b`, so the window both
editions build is the one the base built. Nothing was pushed.

### What is here: every pure half of the surfaces, ported call for call and held exact

| C# (`gui/host.sources` `[surface]`) | Python ported | State |
|---|---|---|
| `SurfaceJson.cs` | `gui/WindowJson.cs`'s `Json`, byte for byte (the window's file needs Windows Forms) | held equal by test |
| `SurfaceNative.cs` | `ui/popup/win32.py` (+ the tray's and the card's few calls): the declarations, the structures, the scoped Per-Monitor-v2 context, `screen_at`, `gui_resources`, `icon_rect`, `_icon_from_pixels` | compiled |
| `PopupWords.cs` | `ui/popup/words.py`'s drawing half: `say`, `one_line`, `unbroken`, by code point and on Python's spaces | via the plans |
| `SurfaceFonts.cs` | `ui/popup/fonts.py`, `win/typeface.py`'s `ui_face`/`lacks`/`face_for`/`letters`, `Renderer.lines`/`measure`, `TipRenderer.metrics`/`ink`; `ITextCalc` (GDI or a job's table) | via the plans |
| `SurfaceTheme.cs` | `ui/popup/theme.py`, `win/textsize.py`, `brand/colour.py`'s `mix`/`luminance`, `palette(theme, design)[token]` | via the paint |
| `PopupLayout.cs` | `ui/popup/layout.py` (`layout`, `mirror`, `share_columns`), `brand.day_band`, `glow_extent`; `SurfacePlan`/`PlanItem`/`SurfaceTarget`; `SurfaceMath` (floored `//`, round half even, the C runtime's `cos sin pow atan2 sqrt`) | exact |
| `PopupPlace.cs`, `PopupMotion.cs` | `ui/popup/placement.py`; `ui/popup/motion.py` (+ `brand.glow`/`glow_phase`) | exact |
| `MenuPlan.cs`, `TipPlan.cs`, `CardPlan.cs` | `ui/popup/menuplan.py`; `ui/tray/tipplan.py` + `TipRenderer.tip_layout`; `notice_card.py`'s drawing half (Q1: layout, motion, `CardMotion`, stack, float shadows) + `Card.fitting` | exact |
| `TrayMotion.cs` | `ui/tray/motion.py` + `brand/mark.py`'s rasteriser (`math.hypot` as CPython computes it) | exact, pixels by digest |
| `SurfaceRenderer.cs` | `Renderer`'s look half: `_theme _design _depth smoothing _radii _corner _control_radius _rgb _argb _colorref face_colours _lifted` | exact (paint) |
| `SurfaceRender.cs` | P6-DESIGN 3.2's render mode: `CODEX_AR_RENDER_PLAN` names a job, `CODEX_AR_RENDER_OUT` the answer; cases `popup menu tip card card_room card_life place popup_motion icon paint` | the harness |

### Comparison A (`tests/test_surface_parity.py`, standard lane, in-box csc; 12 tests, ~5 s)

The reference lays out every case through a stand-in for `DrawTextW(DT_CALCRECT)` (and the tip's `GetTextMetricsW`/`GetGlyphOutlineW`)
that answers by arithmetic; every question and answer goes into the job's table, and the C# answers from that table only (a question
it has no answer for is an error). So fonts drop out and CI can run it. The C# is compiled with a two-line driver and run once as a
console program with `CREATE_NO_WINDOW`. Cases: popup 4 scales x en/ko/ja/de/ar x 6 views (120); menu 3 lists (60, with places,
submenu places, steps, Home/End, letters, MSAA children); tip 6 snapshots (120, two special days, chip and meter); card 6 views (120)
+ shadows/stack/text size + 5 lives replayed; placement 720 places, hits, focus; popup motion 16 moments x 9 states x 3 designs;
icon 6 states x 2 fines x reduce x 17 moments, colours, frames at 16/20/24/32 px; paint: the popup, card, tip and menu plans at 150 %
and 200 % in en/ko/ar in light/dark x Soft/Classic/Plain x High Contrast off/on (a fixed system-colour table). **All exact.**

* **Found on the way**: .NET Framework's `Math.Cos`/`Math.Pow` are not the C runtime's, which Python's `math` calls: a light frame came
  out one place off (attention at 2200 ms). `SurfaceMath` calls `ucrtbase.dll`'s. `gui/Brand.cs`'s generated `Glow` and `Mark` (the
  window's light and taskbar button) use .NET's and are left as they are (AUDIT line).
* **Mutation checks** (each alone, restored): `SwitchGap` 10->11 (popup), `MenuCheck` 24->25 (menu), `TipPadY` 13->14 (tip), `SwapMs`
  130->131 (card life), `GlideFrameMs` 31->30 (icon), hover's edge `accent_hover`->`accent` (paint), the nearest-edge tie `<`->`<=`
  (placement), floored `//` -> truncated (placement; the first run missed it, so the cases gained an anchor left of the primary
  monitor), `round(x, 4)` away from zero (shadows), a single letter match not chosen (menu keys): each fails its test.
* **Re-diff**: `python -X utf8 tests/rustdiff/rediff_host_surface.py --reference v0.6.26` (the ported files that differ from the tag -
  only `ui/popup/model.py`, the view model's input - then comparison A with the tag's own package as the reference): exact.

### What S6.3 has not done yet (the rest of 2.3)

* **The drawing**: `SurfaceGdip.cs` (`ui/popup/gdiplus.py`), `SurfaceElevation.cs`, `SurfaceLight.cs`, and `SurfaceRenderer.cs`'s
  drawing half (`_ground`, lifts, wells, switches, meter, buttons, scene, text, halo). Until then the render mode writes plans and their
  paint, no pixels, and `build/motion_{popup,tip,card}.py` and `make_screenshots.py`'s surface functions are **not** retargeted
  (there is no pixel to retarget them to); comparisons B and C wait for it.
* **The windows and `ISurfaces`**: `PopupWindow.cs`/`PopupMessages.cs` (`layers window messages hidden`), `MenuWindow.cs`, `TrayIcon.cs`
  (`icon win32 clicks cards __init__`), `TrayMenu.cs`, `TipCard.cs`, `TrayWords.cs`, `TrayPlace.cs`, `CardWindow.cs`/`CardStack.cs`
  (with the card's corner: `corner_coverage`/`premultiply`, which need `brand/shape.py`), `SurfaceAccess.cs` (MSAA), the probe mode
  (`--probe <job>`), and the class that implements `ISurfaces` over them. No `ISurfaces` is implemented: a `Start` that posted
  `tray_started` with no icon would tell the core a lie.
* **A special day's motif on the icon's badge** (`brand.mark_colour`, `IconFrames(look=...)`): `IconFrames` refuses a look.
* **The ledger rows** (`tests/rustdiff/surface_ledger.json`, P6-DESIGN 3.4) are S6.4's file (Q5 a); every *drawn* row whose plan
  half is here is now held by comparison A, the pixel half by nothing yet.

### Seams for the next seats

* **S6.2b (the host shell)**: the host's `Main` asks `SurfaceRender.Run()` first (`int?`: null when no job is named, else the exit
  code) and loads no DLL when it answers. `gui/host.sources` exists with `[surface]` and `[generated]`; `[host]` goes above
  `[surface]`. `[shape]` is not in it: `gui/SoftShape.cs` reads the window's `Palette` and `Design` (`Shape.Smoothing`) and does not
  compile without the window - a decision for the main session (split `Smoothing` out, or the host's own port of `brand/shape.py`).
  The host's JSON is `gui/SurfaceJson.cs` (`Json`, the window's byte for byte); `HostCore`'s replies can use it.
* **The core (S6.1/S6.2b)**: the surfaces draw from the reference's view models (`popup_view`, `notice_card.view`,
  `tooltip_parts`, `menu_items`/`row_menu`) as `Json.Parse` gives them. The event table carries a `snapshot`, not the popup's view: the
  core must hand the host the popup's view model (car-surface's `PopupModel.view`) and the strings' locale (the host has no
  `locale_of`), and English for `say`'s fallback (`PopupWords.English`). Named here, not decided: the tables are the main session's.
* **S6.4 (the UI tests)**: comparison A's job format (`car-surface-job/1`) and `TableTextCalc` are how a *drawn* row is rewritten
  against the render mode; `test_surface_parity.StandIn` records any reference measure into a table.

### Checks

```
test_surface_parity (12) + the guards (wait_quiet.sh, one run): see the seat's return
python -X utf8 tests/rustdiff/rediff_host_surface.py --reference v0.6.26     exact
```

### S6.3 second part (the main session's go-on, 2026-11-26): the drawing, begun

Three more `[surface]` files, each held to the reference by comparison A (now 16 tests, all exact, ~6 s):

| C# | Python | Held by |
|---|---|---|
| `SurfaceShape.cs` | `brand/shape.py` whole (corner, outline, flatten, profile, edge_at, inside, distance) - the host's own, since `SoftShape.cs` needs the window | 9 boxes: every segment, flattened points, distance and inside at 10 points |
| `SurfaceGdip.cs` | `ui/popup/gdiplus.py` whole: startup by users, the leak counter (`GdipObjects`), `_Canvas`, `_Painter`, `_ShadowImage` + stamp | 16 painter calls into an offscreen 160x120 canvas on the reference's own `_Painter` and on the C#'s: pixels by SHA-256 equal for both smoothings x both formats x kept brushes, and 0 objects left per paint (pixel offset mode 0 instead of 4 fails it) |
| `SurfaceElevation.cs` | `ui/popup/elevation.py` whole, the masks' one memory and turned-twin reuse kept; the C runtime's `erfc` | 14 masks in one order, by SHA-256; recipes in every theme and design; `shadow_step` |

**Exactly what is left of the go-on (in this order; nothing of it is started):**

1. `SurfaceLight.cs` (`ui/popup/light.py`, the status light: `StatusLight`, `draw_halo`, the halo band) and `SurfaceRenderer.cs`'s
   drawing half (`renderer.py` 145-693: `draw`, `_seal`, `draw_scene`, `_ground`, `_scene`/`_scene_shape` with brand's
   `scene_frame`/`speck_frame`/`element_at` from `brand/days.py`, `_ground_item`, `_accent_bar`, `_use_scale`, `_image`, `_lift`,
   `_inner`, `_well`, `_switch`, `_meter`, `_button`, `_text` with DrawTextW). Then the render mode writes pixels per plan (a
   `pixels` case beside `paint`), and a test draws each plan of the matrix on the reference's `Renderer` (offscreen, its own
   fonts, as `make_screenshots` does) and on the C#'s, byte for byte, with `GdipObjects` back at 0 after each draw.
2. The windows: `PopupWindow.cs`/`PopupMessages.cs` (`layers window messages hidden`), `MenuWindow.cs` (+ `MenuRenderer.draw_menu`),
   `TipCard.cs` (+ `TipRenderer.draw_tip`), `TrayWords.cs`, `CardWindow.cs`/`CardStack.cs` (`ui/card/*`, `notice_window.py`,
   `notice_card.corner_coverage`/`premultiply`, which `SurfaceShape` now makes possible), `TrayIcon.cs` (`ui/tray/icon win32 clicks
   cards __init__ animation`), `TrayMenu.cs`, `TrayPlace.cs`, `SurfaceAccess.cs` (MSAA); the probe mode (`--probe <job>`, windows
   unshown, no dialog); the class implementing `ISurfaces`; the icon's day motif (`brand.mark_colour`, `IconFrames(look)`).
3. The live-path proof (P6-DESIGN 3.3's last paragraph): each window's own paint into its buffer offscreen against the render
   mode's, byte-equal, over the matrix.
4. Retarget `build/motion_{popup,tip,card}.py` and `make_screenshots.py`'s surface functions to the render mode (not run).
5. `make_gui.ps1` once at the end: both editions' windows byte-identical to the base (the window's inputs are still 0 diff lines).

### S6.3 third part (seat S6.3b, 2026-11-26): the drawing, done for the popup

Item 1 of the list above is **done**; comparison A is now 20 tests (+ the table guard), ~40 s, all exact:

| C# | Python | Held by |
|---|---|---|
| `SurfaceDays.cs` | `brand/days.py`'s drawing half: `path_points`, the elements (read from `Brand.DayScene`/`DaySpecks`, whose numbers days.py rounded to three places, so the text is exact), `element_at` (`_wave _drift _centre _placed`), `scene_frame`, `speck_frame` with `within` (`_reach speck_reach _height`), `MARKS`/`mark_colour` (computed, its turned points are not rounded) | `days/<look>`: 9 moments x 6 `within`s, the reach, the mark on a 43x43 grid, 5 paths |
| `SurfaceBidi.cs` (generated by `tests/surfacebidi.py`) | `l10n.first_strong` (unicodedata's L / R+AL runs; .NET Framework has no bidi class) | `bidi/all` over a code point of every 173; the file equals what the script writes under the bundled Python 3.14.10 (Unicode 16.0.0; S6.3c: it runs itself under `refpython`'s bundled runtime and `--check` refuses any other stamp), and the expected answers are that Python's |
| `SurfaceLight.cs` (partial `SurfaceRenderer`) | `ui/popup/light.py` whole + `brand.sweep_at`, `glow_stops`, `glow_radius`, `status_fill`/`status_system` | the pixels below |
| `SurfaceRenderer.cs` drawing half | `renderer.py` 96-693: `Open`/`Dispose` (`__init__`/`close`), `use`, `layout`, `draw`, `_seal`, `draw_scene`, `_ground` (kept pixels, same key), `_scene`, `_scene_shape`, `_ground_item`, `_accent_bar`, images, `_lift`, `_inner`, `_well`, `_switch`, `_meter`, `_button`, `_text` | the pixels below |
| `SurfaceLayers.cs` | `ui/popup/layers.py`: `float_reach`, `card_shadows`, `card_radius`, `stamp_shadows`, `cut_card`, `_over`, `still_pad`, `card_still`, `update` (UpdateLayeredWindowIndirect), `CardLayers` | the still and the shadow picture below |

`pixels/<view>/<locale>/<scale>/<look>-<lone>` (192 cases): the reference's own `Renderer` and fonts (UI face pinned as
`make_screenshots.pinned_face`, the system colours a fixed table) and the C#'s draw the popup offscreen, en/ko/ar, six
views + the four other special days, 1.25/1.5/2.0, all twelve looks for the picture view: a whole frame, the light alone
(`draw_halo`), the day alone, a frame with a hover, a focus, a glide and a face part way, a press, the seventh press's sweep,
and (lone) `card_still` and `CardLayers.shade`'s picture - each step's pixels by SHA-256 and `halo_rows`; the plan the
real fonts laid out; 0 GDI+ objects left after `Dispose`. **All equal.** Mutations (each alone, restored, each fails):
the glow's near stop alpha, `DT_RTLREADING` for a left-to-right name, the sweep's arc width, `_seal`'s last pixel, the
mirrored knob, the shadow cut's `== 0xFF`; days: `_drift`'s 24; bidi: the run search's `<=`. (`originY` for seollal
from the top is an equivalent mutation: `bottom - 66 * unit` is `top`.)

**Then (the same seat, the same day)** - every surface's drawing is now in C#, each held byte for byte offscreen:

| C# | Python | Held by |
|---|---|---|
| `SurfaceDrawn.cs` (partial `SurfaceRenderer`) | `MenuRenderer` (`menu_layout`, `draw_menu`, `_menu_words`) and `TipRenderer`'s drawing (`tip_layout`, `draw_tip`, `draw_tip_light`, `_opaque_words`, `tip_day`) | `drawn/menu/...` and `drawn/tip/...` (216 cases): the comparison-A menus and tips at 1.25/2.0 in en/ko/ar x 4 looks, the menu at four selections, the tip whole and two frames of its light; 0 objects left |
| `CardWindow.cs` | `ui/card/card.py`'s `Card` (`NoticeCard`: `_draw_card`, `_draw_light`, `redraw`, `breathe`, `_paint_body` scaled, `_paint_shadow`, `_cut_under_body`, `paint`, `present`, `hit`, `close`; its windows made through `ICardHost`, the stack's class), `ui/card/surfaces.py` (`CardLayer`, `CardSurface`, `CardImage`; `_CardRenderer._halo` is the popup's own rule), `notice_card.corner_coverage`/`_round_corner`/`_squircle_corner`/`premultiply` (`CardCorner`) | `cards/...` (37 cases): `make_screenshots`' settled card offscreen (`windows=False`) at 144/192 dpi, a text size, a special day, en/ko/ar x 4 looks - the entrance part way (scaled body, shallower shadow), settled, a breath, a hover redrawn, a breath by the stack's rule, each layer by digest, the frame keys; the corner at 15 radius/smoothing pairs |
| `TrayMotion.cs` | `IconFrames(look)`: the day's body, `_mark_cover`/`_marked` from `MOTIF_LEAST` | `icon/<look>` x 5 at 16/24/32/48 px |

`SurfaceShadowImage.StampOn(graphics, ...)` is the stamp for any GDI+ graphics (the card's layers stamp through
`CardSurface`). Mutations added (each fails): the menu's raised pill without its lift, `premultiply`'s `+127`, the
squircle corner's `- 0.125`, the head-over-mark test. `tests/rustdiff/rediff_host_surface.py --reference v0.6.26` now
also watches `ui/popup/light.py gdiplus.py elevation.py layers.py ui/card/surfaces.py`: exact (21 tests). `make_gui.ps1` on
`git archive` trees of `b1761926b` and of this head, both editions: every `.exe` byte-identical (`ec1ae342...`,
`101f257d...`, `382bbb9c...`, as in S6.0's record).

**Left, in this order (nothing of it started):** the windows with a message loop - `PopupWindow.cs`/`PopupMessages.cs`
(`window.py`, `messages.py`, `hidden.py`, layers' `PopupCard` half; `SurfaceLayers`' `CardLayers` and `Update` are ready),
`MenuWindow.cs` (`menuwindow.Menu`; its drawing is `DrawMenu`), `TipCard.cs` (`tipcard.TipCard`, `tip_place`/`tip_screen`/
`tip_away`; its drawing is `DrawTip`), `TrayWords.cs`, `CardStack.cs` (`ui/card/stack.py`, implementing `ICardHost`),
`TrayIcon.cs`, `TrayMenu.cs`, `TrayPlace.cs`, `SurfaceAccess.cs` (MSAA); the probe mode (`--probe <job>`); the class
implementing `ISurfaces`; then items 3-4 (the live-path proof, each window's own paint against the render mode's bytes;
the retargets of `build/motion_{popup,tip,card}.py` and `make_screenshots.py`'s surface functions, which need the render
mode to write each frame's BGRA, not only its digest - not started, not run). Item 5 is done (above).

### S6.3 fourth part (seat S6.3c, 2026-11-26): the bidi table at Unicode 16.0.0, and the first windows

**Step 0, done.** `tests/surfacebidi.py` now runs itself under the bundled CPython 3.14.10 (`refpython.command(...,
which="bundled")`, always bundled whatever `--reference-python` says, as the other Unicode generators are), refuses a
runtime whose `unicodedata` is not `UNICODE = "16.0.0"` (exit 2), and `--check` refuses a file that names another stamp or
differs (exit 1). `gui/SurfaceBidi.cs` is regenerated at 16.0.0. comparison A's `bidi/all` takes its expected answers from
the same runtime (`surfacebidi.first_strong`), not from the test's interpreter: 27 of its sampled code points read
differently at 15.1.0, so the case now proves the 16.0.0 table. `SurfaceSourceTests` runs `--check` (no skip any more).
AUDIT-v0628's S6.3b bidi line says what is true now.

**Step 1, begun** - three of the windows' files, each held exact by a new module, `tests/test_surface_windows.py` (standard
lane, in-box csc, one compile, ~30 s; 3 tests, all exact):

| C# (`[surface]`) | Python ported | Held by |
|---|---|---|
| `TrayWords.cs` | `ui/tray/words.py` whole (`tooltip_parts`, `tooltip` with the v0.6.26 N1 cut, `tooltip_joined`, `meter_rows`, `meter_line`) + `ui/words.py`'s `countdown`, `share`, `left`, `window_name`; lengths and cuts by code point | `traywords/`: 22 catalogs + 4 odd ones x 20 snapshots x 4 editions, and 14 countdowns (2,094 cases) |
| `TrayPlace.cs` | `tray_place.py` whole: `IconPlacement` over `ICurrentUserKeys` (the real one is `Registry.CurrentUser`, read only, REG_DWORD unsigned and REG_EXPAND_SZ unexpanded as winreg gives them), `overflow_open` over `IOverflowWindows`, `battery_saver`, `known_folder`, `process_image`, `_same_path` (ntpath `splitroot`/`normpath` and `normcase` through `LCMapStringEx`, as CPython calls it) | `trayplace/` (16 cases): 15 runs of registry states and clock readings, 22 paths, 12 flyout window sets |
| `TipCard.cs` | `ui/tray/tipcard.py`'s window half: `tip_light` (+ `model.snapshot_activity`), `tip_place`, `tip_away`, `tip_pointer`, `tip_screen`, `TipCard` (create, destroy, show, hide at once or fading, tick, the backstop's watch, `_lay` with the text-size fit, frame, render, the light's band, fade in/out, gone, the window procedure); `brand.day_look_at` | `tipwindow/` (17 runs): the reference's own `TipCard` driven by a script (its user32 window calls stood in, nothing shown) and the C#'s over a window made and **never shown** (`OnScreen = false`), messages sent to its procedure: after each of 70 steps shown/alpha/fade/frame timer/place/size/text/picture digest and the answers to WM_MOUSEACTIVATE and WM_NCHITTEST; and the **live-path proof** (step 3) for the card: its own `Render()` == the render mode's `DrawTip` for the same parts and frame == the reference's, byte for byte, 0 GDI+ objects left |

`SurfaceRender` is now `partial`: the windows' cases are in `gui/SurfaceRenderWindows.cs` (`tray_words`, `tray_place`,
`tip_window`; a case it does not know falls through to "no surface"). Mutations (each alone, restored, each fails):
`TipChars` 127, the meter's `<= LOW_LEFT` as `<`, the cut's row-first order, the strip's U+202F; `LOOK_AGAIN_S` 29, the
promoted entries' `or`, the flyout's 16-window bound, normpath's `..` at the root, a bool UID; `TIP_AWAY_S` 0.9,
`MA_NOACTIVATE`, the fade-out from the alpha it left at, the zero-alpha hide, the light held by `reduced` alone, the fit's
`> 1.0`. `make_gui.ps1` on `git archive` trees of `b1761926b` and of this head, both editions: every `.exe` byte-identical
(`ec1ae342...`, `101f257d...`, `382bbb9c...`). `rediff_host_surface.py` now also watches `ui/tray/words.py`,
`ui/words.py`, `tray_place.py` and runs `test_surface_windows`.

Seams this part leaves (the main session's, not decided here): the tip card's content carries the catalog's `Locale` and
`Letters` (the host has no `locale_of` and no catalogs - AUDIT line); the icon's words read the snapshot's numbers as
doubles (the window's `Json`), so a whole float reads as an int (AUDIT line). `TipCard.Accessible` and
`SurfaceAccessHooks.Disconnecting` are the hooks `SurfaceAccess.cs` fills (null until then: Windows answers WM_GETOBJECT).

**Left, in this order (nothing of it started):** the rest of step 1 - `PopupWindow.cs`/`PopupMessages.cs` (`window.py`,
`messages.py`, `hidden.py`, layers' `PopupCard` half; it needs the popup's model as the host gets it - `PopupModel.view`,
rows/status, `perform` posting `popup` actions - a seam to settle first), `MenuWindow.cs` (`menuwindow.Menu`),
`CardStack.cs` (`ui/card/stack.py` + `ui/card/win32.py`, implementing `ICardHost`), `TrayIcon.cs`, `TrayMenu.cs`,
`SurfaceAccess.cs` (MSAA, then TipCard's hooks); each the way `TipCard` is held: the reference driven with its window
calls stood in, the C# over a window never shown, the same script, state and digests after each step. Then step 2 (the
probe mode as the host's own entry - today the probe is the render mode's `*_window` cases - and the class implementing
`ISurfaces`), step 3 for the popup, menu and card windows, step 4 (BGRA frames; the retargets, not run). Step 5 is done
for this head (above).

### S6.3 fifth part (seat S6.3d, 2026-11-26): the decided seam, and the popup, menu and card windows

**The contract change (the main session's decision, DECISIONS.md "The popup's model at the host boundary"), done.**
car-host `abi.rs`: `EventKind::fields` gives `snapshot` `[snapshot, popup]` and `strings` `[strings, locale, letters]`;
`Event::Snapshot`/`Event::Strings` carry and write them in that order (an abi unit test writes both). `gui/ISurfaces.cs`:
`ISurfaces.Snapshot(SnapshotEvent)` and `Strings(StringsEvent)`, whose properties `test_host_contract` holds to abi.rs's
fields (13 tests). Nothing else in the tables moved. `gui/ISurfaces.cs` is now the `[contract]` group of `gui/host.sources`
(the surfaces post through `IHostActions` and will implement `ISurfaces`); the comparisons compile `[contract]` first.

**The popup field's shape** (what the core must put in `snapshot.popup`; the host draws from it and computes nothing):
`{"view": PopupModel.view(now), "menus": [[interruption id, PopupModel.menu_for(id)], ...], "read": <the first read is
done>, "attention": PopupModel.attention()}`. `read` false makes a first opening wait up to 300 ms (FIRST_READ_WAIT_MS) for
a snapshot whose `read` is true, as `show` waited for its first read. A click posts `popup {call, args}` with `args` the
action's own fields after its kind (`["recovery", id, thread, enabled]` -> `set_interruption_recovery` with
`[id, thread, enabled]`; postpone/unpostpone/release/tier/project/unsay alike; the core rebuilds `(kind, *args)` and runs
`perform` with the popup's own pending source); the Dashboard's two post `open_dashboard {page: "pending", row: null |
[dialog, id, thread]}`. Until the first snapshot after the core's answer the window shows the action as under way itself
(begin's busy: a task's `busy`, `toggle_busy`), as the reference's model does from the click to its outcome; the core's
own `begin` refuses a second one. The `strings` event's locale/letters are the popup's and the menu's; `Start` has the
catalog but no locale: until the first `strings` event the surfaces use "en" and no letters (a seam: the core sends
`strings` right after `surfaces`, or the main session adds the two to `surfaces`).

**The notice event's shape** (CardStack.Show): `{"id", "key", "title", "stays", "view": notice_card.view(notice),
"letters"}`; a button or the card's face posts `notice_action {uri}`, an ended notice `notice_complete {id, shown}`, each on
a worker thread.

| C# (`[surface]`) | Python ported | Held by |
|---|---|---|
| `SurfaceScreen.cs` | every call by which a window reaches the screen (show, place, fade, `UpdateLayeredWindow(Indirect)`, focus, foreground, timers, posts, DWM, region, class style, TrackMouseEvent, GetKeyState): Windows' on a live host; in the probe a record in the reference's words, not made, and the posts queued for the script. `SurfaceLayers.Update`, `CardLayers.Show/Hide` and `CardLayer.Push` go through it | the records below |
| `PopupWindow.cs` + `PopupMessages.cs` | `ui/popup/window.py` (`Popup`), `messages.py` (`PopupMessages`), `hidden.py`, `layers.py`'s `PopupCard`; model.py's `select_action`, `busy_key`, `action_for`/`menu_for`/`begin` over the drawn view | `popupwindow/` (7 runs) |
| `MenuWindow.cs` | `ui/popup/menuwindow.py`'s `Menu` (its drawing was `DrawMenu`): open/close/dismiss, fade in/out, keys, letters, pointer, rest timer, submenus; implements the popup's `IRowMenu` | `menuwindow/` (5 runs) |
| `CardStack.cs` | `ui/card/stack.py` (`CardStack`, implements `ICardHost`) + `ui/card/win32.py`'s `screen`, `look`, `focus_snapshot`, `taskbar_corner`, `focus_line`, `hold` (SPI_GETMESSAGEDURATION) | `cardstack/` (4 runs) |

How they are held (`tests/test_surface_windows.py`, now 6 tests, ~40 s, all exact): the reference's `Popup` and `Menu` are
driven by a script with every user32 call that would make, show, place, fade, upload or time a window answered by a
stand-in that records it in the same words `SurfaceScreen` records (`layers.update` too), their clocks, threads and the
look questions fixed; the C# runs the same script over windows made and never shown. The popup's core half is the
reference's own `PopupModel`: its view after each answer the reference took is handed to the C# as that snapshot (a
read's result one snapshot, an action's its answer then a snapshot), and the action the reference performed is compared
with what the C# posted (`popup {call, args}`, `open_dashboard`). After every step: shown, opening alpha and rise, home,
frame timer, waiting, hover/press/focus, size, painted plan, the picture's digest and the calls in order; the menu's and
its submenu's likewise, what was chosen and who was told it closed. `popupwindow/` 7 runs x 125 steps, `menuwindow/` 5 runs
x 63 steps, `cardstack/` 4 runs x 44 steps (six notices: a replacement about the same
conversation, a fourth pushing out, one that stays, hover, a press, a button, the face, a right click, the focus asked
again and its log line, the end; each card's phase, place, edge and marks, the posts); the popup's live-path proof (step 3) three times a run: its own `Render()` == a fresh renderer's `Draw` of
the same view, plan and frame == the reference's `render()`; 0 GDI+ objects left. Mutations (each alone, restored, each
fails): click-away 0.5 -> 0.1 s, the opening's rise xs + 1, the begun action's busy not drawn, WM_POPUP_PAINT pushing when
nothing is owed, the menu telling its owner it left when the focus went back to it, the menu's fade frame 16 -> 17 ms,
the stack not seeing a notice about the same conversation, FOCUS_AFTER 0.6 s. Not caught: the fourth card kept past
MAX_CARDS - in these runs the work area has room for three cards only, so the room rule retires it the same way.
Found on the way: the snapshot must bring an open popup up to date whatever changed (the reference's read result always
does), and the posted strings message must not draw the old view in the new words (AUDIT lines).

**Left, in this order:** `TrayIcon.cs` (`ui/tray/icon.py`, `win32.py`, `clicks.py`, `cards.py`, `__init__.py`, `animation.py`) and `TrayMenu.cs`
(`ui/tray/menu.py`: `menu_items`, the drawn menu through `MenuWindow`, Windows' own as the fallback, `_act` posting
`toggle`/`stop`/`open_dashboard`/`disarm_power`); `SurfaceAccess.cs` (`ui/popup/access.py`: MSAA, then the hooks already
in place - `TipCard.Accessible`, `PopupWindow.Accessible`/`Speaking`/`Spoken`, `MenuWindow.Accessible`/`Speaking`/
`Telling`, `SurfaceAccessHooks.Disconnecting`); step 2 (the probe mode as the host's own entry; the class implementing
`ISurfaces` over TrayIcon, PopupWindow, MenuWindow, TipCard and CardStack); step 3's live-path proof for the menu and card
windows (the popup's is in `popupwindow/`: its own `Render()` against a fresh renderer's `Draw` of the same view and plan);
step 4 (BGRA frames; the retargets, not run); step 5 (one `make_gui.ps1` at the end).

### S6.3 sixth part (seat S6.3e, 2026-11-26): the surfaces event's locale, the icon, its menu and MSAA

**The addendum (DECISIONS.md, "The popup's model at the host boundary", ~22:30), done.** car-host `abi.rs`:
`EventKind::fields` gives `surfaces` `[icon, strings, settings, edition, demo, locale, letters]` and `Surfaces` carries and
writes the two (the abi unit test writes them); `gui/ISurfaces.cs`'s `SurfacesEvent` has `Locale` and `Letters` before the
pump's `Actions`; `test_host_contract` holds both, and names the seven fields. So the first frame is drawn in the catalog's
language: nothing falls back to "en" before the first `strings` event once the class that implements `ISurfaces` reads
`SurfacesEvent.Locale`/`Letters` (step 2 below).

| C# (`[surface]`) | Python ported | Held by |
|---|---|---|
| `TrayIcon.cs` | `ui/tray/icon.py` (`Tray`: the hidden top-level window, `Shell_NotifyIconW` add/modify/version/delete, the tooltip card's rules - `_tip_shows`, the shell's silence timed by `TIMER_TIP`, the fallback to Windows' tooltip and back -, `TaskbarCreated`, `WM_WTSSESSION_CHANGE`, `WM_CLOSE`/`WM_DESTROY`), `win32.py`, `clicks.py`, `cards.py`, `animation.py` (the frame table built off the thread and its budget, `_observe`, `_frame_for`, `_sync_motion`, the day's look), the demo event | `trayicon/` (3 runs) |
| `TrayMenu.cs` | `ui/tray/menu.py` whole: `menu_items`, `menu_app_mode`, `prefer_app_mode` (uxtheme by ordinal, the build read with `RtlGetVersion`), the drawn menu first, Windows' own as the fallback, `_act`, `_power_armed`, `_theme_menu` | `trayicon/` |
| `SurfaceRenderTray.cs` | the probe's `tray_icon` case | |
| `SurfaceAccess.cs` | `ui/popup/access.py` whole: `accessible_items`, `switch_name`, `pick`, `changes`; `PopupAccessible` as a vtable built by hand (the reference's three interfaces only, never freed while its window lives, E_FAIL for an exception), `MenuAccessible`, tipcard.py's `TipAccessible`; `answer`, `disconnect`, `tell`, `announce`; `Attach(...)` fills the windows' hooks | `popupwindow/` (each step's `a11y`: the children, the child each centre picks, the events since the step before, and the object's name/value/description/default action/role/state/navigation for every child and one past them, through the vtable's own slots), exact |

**How the icon is held** (`tests/test_surface_windows.py`, 7 tests): the reference's `Tray` is driven by a script - made,
ticked, its frames built (the building thread queued and run by the script, its budget clock fixed), a frame timer, three
pointer visits with no word from the shell (the fallback to Windows' tooltip), the word (`NIN_POPUPOPEN`) and the card,
a failure unseen (red, turning), a click (the popup made, `failure_seen` posted), the popup open with its attention, the
menu drawn and a choice (`toggle`), the drawn menu refused (Windows' menu, `disarm_power`; then Open the popup), a
double click, mouse downs, a broken popup, the session locked/unlocked/away/back, High Contrast, Reduce motion, battery
saver, the overflow flyout, no icon rectangle, the demo signalled, a new language, `TaskbarCreated`, the end; a second
script under a shell that refuses version 4 (the old messages) with no icon file and a menu that cannot be made - with
every user32/shell32/wtsapi32 call recorded by a stand-in in the words `SurfaceScreen` records and not made, and the
popup, tip, drawn menu and cards stood in by recorders; the C# runs the same script over a window made and **never
shown**, no icon ever added to the notification area. After every step: version 4, unseen failure/sending, the icon's
state, motion allowed, the frame timer, the frame key, the icon shown, the tooltip held, the tip's word/visits/fallback,
the session, the menu's mode, the calls in order, what the stand-ins were asked, what was posted to the core, the log.
3 runs (two scripts), exact. Mutations (each alone, restored): `TipSilentVisits` 3, the failure seen without its
refresh (caught once the script waited 0.3 s before the click), `TaskbarCreated` without the version asked again, the
lock ignoring a disconnected session: each fails; `PopupCanOpen` ignoring a broken popup was not caught by the first
script, which then gained a right click after the popup broke. The MSAA object's answers are read in the probe through
the same slots a screen reader calls (`AccessObject.Walk`); in the reference the harness's core model takes a new
catalog at once, so its walk reads the catalog the window last drew with, as the reference's own `_rebuild` hands it.

**The host boundary, as the icon meets it** (seams for S6.1/S6.2b; not decided here, the main session's):

* What the reference asked its control layer the core answers: `TrayIcon.FailureUnseen`/`UnconfirmedUnseen` read the
  snapshot's `failure_unseen`/`unconfirmed_unseen` (`control.failure_unseen(marks) is True`, which the reference asked
  every second; the core would compute it on the tick it sends the snapshot), `PowerArmed` reads `power_armed` (the
  `armed` of `control.power_view()`). Three keys in the snapshot's value, no new field in the table.
* A failure seen posts `failure_seen`; the reference refreshed at once with a fresh answer, the host refreshes with the
  snapshot it has until the core's next one (the next snapshot after the post brings the change).
* The stored settings the icon read for itself on each opening and each motion tick (`StoredMixin`): the core's
  `settings`/`strings` events; `AdoptSettings`/`AdoptReduceMotion` do nothing on the live host.
* The demo event: `DemoName` must be the event's object name (car-platform's `watcher_names(state_dir).demo`); the
  table has no action for a signalled demo (`OnDemo` is null, so no event is made, as the reference makes none without
  `on_demo`). Either the core watches the event itself and sends `demo`, or a `demo` action is added.
* Where the reference's own loop ended (`PostQuitMessage` in `WM_DESTROY`) the icon calls `Ended`; the surfaces' class
  posts `closed` there. The cards' attach/detach are posted as `cards_attached`/`cards_detached` where the reference's
  CardStack attached to and left the inbox.

**Step 2, done.** `gui/HostSurfaces.cs` implements `ISurfaces`: `Start` builds the `TrayIcon` from the `surfaces` event (its
catalog, `Locale` and `Letters` - the first frame in that language -, the adopted look, the edition, the demo's name),
posts `tray_started` once it is up (nothing when it cannot be made, see the seams); `Snapshot` hands the icon its
snapshot and the popup its view, `Strings` the catalog with its locale and letters, `Settings` the look (the popup's
`FollowSettings`), `Notice`/`Demo` a card to the stack the icon hosts, `Close` the icon's `WM_CLOSE`; the icon's end posts
`closed`, once. The icon makes its popup, drawn menu, tip and cards as the reference makes them and fills their MSAA
hooks (`SurfaceAccess.Attach`). The probe is the host's own entry: `SurfaceRender.Probe(args)` answers
`--probe <job> [<answer>]` (null otherwise; S6.2b's `Main` asks it beside `Run()` before any DLL loads). Held by
`hostsurfaces/` in `test_surface_windows` (8 tests, exact): started in Korean, a snapshot, a tick, English, a tick, close -
the shell told the reference's `tooltip` words in each language, `cards_attached`, `tray_started`, `cards_detached`,
`closed` (mutation: a `Start` that drops the event's catalog fails it).

**Step 5, done for this head.** `make_gui.ps1` on `git archive` trees of `b1761926b` and of this head, both editions:
every `.exe` byte-identical (`ec1ae342...`, `101f257d...`, `382bbb9c...`); `gui/window.sources`, the files it lists and
`build/make_gui.ps1` have no diff from the base.

**Checks:** the GUI set (24 modules, one at a time through `gui_lock.sh`): OK, but `test_gui_v065_controls` - its GUID
rule found `SurfaceAccess.cs`' interface ids spelled as text (now built from their parts, as access.py builds them) and
its UI Automation focus test failed beside the set; alone under `quiet.sh` all 26 pass. Gates in `rust/` and
`advanced/rust/` (fmt, clippy -D warnings, test, deny), `check_groundwork.py`, `check_rebuild.sh`: all pass.

**Left, in this order (nothing of it started):** step 3's live-path proof for the menu and card windows (each window's
own paint into its buffer against the render mode's bytes, as `popupwindow/` and `tipwindow/` hold theirs); step 4 (the
render mode writes BGRA frames; retarget `build/motion_{popup,tip,card}.py` and `make_screenshots.py`'s surface functions
to it, not run); then step 5 once more at the end.

### S6.3 seventh part (seat S6.3f, 2026-11-27): the live-path proofs, the render mode's pictures, the retargets

**Step 3, done.** `menuwindow/` and `cardstack/` in `test_surface_windows` gained `["proof"]` steps: the drawn menu (and
its submenu) by its own `Render()` against a fresh renderer's `MenuLayout` + `DrawMenu` of the same entries, scale,
language, work area and item in hand; each notification card's two windows as its own `Paint(now)` draws them against a
card made offscreen (`windows=false`) from the same notice, born when it was, with its hover, press and last breath
(`NoticeCard.Breathed`), painted for the live card's frame (`NoticeCard.PaintLayers`, which `Paint` now calls - the same
calls in the same order). Both answer `[window digest, render digest, plans equal]`, against the reference's own
`menu.render()` and its card driven the same way (where each card proof must hold in the reference itself). Mutations
(each alone, restored, each fails): `DrawMenu` without the item in hand, the card's hover not carried, its last breath not
carried.

**Step 4, done (not run).** `gui/SurfaceRenderServe.cs`: a render-mode job with `"serve": true` answers one call per line
on standard input/output (the reference renderers' own calls; see its header) and writes every picture to the job's
`frames` folder as raw premultiplied BGRA with its digest. `NoticeCard.Born`/`Motion` are settable, as motion_card sets
a card's. `build/surface_render.py` runs it (a built host named by `CODEX_AR_SURFACE_EXE`, or the `[contract]`,
`[surface]` and `[generated]` files compiled once behind `SurfaceRender.Run() ?? 2`) and hands the makers stand-ins:
`Renderer` (popup and tip: `layout`, `tip_layout`, `draw`, `draw_halo`, `draw_tip`, `draw_tip_light`, `face_colours`,
`canvas.pixels()`, `card_still`, the look as attributes) and `Card` (`paint`, `body`/`shadow.pixels()`, `redraw`,
`_draw_light`, `light_band`, `edge`, `follow` for the motion, every frame checked against the reference's motion). The
retargets: `motion_popup.PopupFrames`, `motion_tip.TipFrames`, `motion_card.CardFrames` take `render=`; `make_motion.make`
hands them one session when `CODEX_AR_SURFACE_RENDER` is set; `make_screenshots.render_popup`, `popup_picture` and
`_SettledCard` draw through `surface_session()` likewise. Without the variable nothing changes. Held by
`tests/test_surface_render_retarget.py` (4 tests; mutation: `draw`'s hover dropped fails it). Found on the way:
`tests/test_surface_windows.py` spelled two known-folder ids as text, which `test_repo_hygiene`'s UUID rule refused
(S6.3c); they are built from their parts now.

**Step 5, done for this head**: `make_gui.ps1` on `git archive` trees of `b1761926b` and of this head, both editions:
every `.exe` byte-identical (`ec1ae342...`, `101f257d...`, `382bbb9c...`); `gui/window.sources`, its files and
`build/make_gui.ps1` have no diff from the base. `rediff_host_surface.py` now also watches `ui/tray/icon.py`, `menu.py`,
`animation.py`, `clicks.py`, `cards.py`, `win32.py`, `__init__.py` and `ui/popup/access.py`: exact against v0.6.26 (29
tests; only `ui/popup/model.py` differs from the tag, as before).

## P6 step 2: the host shell (seat S6.2b, branch `car-v0627-s62b`, 2026-11-27)

Cut from Integration 9 (`cfdabfe59`). P6-DESIGN 1 (exports, panics, threads, the closed tables, start/end, no console
windows, the mutex handover), 4.1 row 2 and 4.2 risk 3, under the owner's answers (Q3 one host exe, Q6 F10 kept). No
window was shown (every host run has show_tray off; the pump's window is message-only), no picture made, nothing pushed.

### What is here

| Commit | What |
|---|---|
| `e44a74af2` | The decided contract taken word for word from car-v0627-s63 (`5fc0226ab`, `874cfd91e`): abi.rs's tables (`surfaces` + `locale`, `letters`; `snapshot` + `popup`; `strings` + `locale`, `letters`), `gui/ISurfaces.cs`, test_host_contract's SurfaceTests, guiscan's `host_group` - identical hunks for Integration 10 |
| `257973aa6` | car-host's six over car-watcher's `api::Watcher`: `car_start` starts it (project root = the folder above the image's `bin`; a second start `bad_request`), `car_stop` signals its stop (0), `car_bridge` = `Watcher::bridge` on `run_deep`, `car_next_event`/`car_post_action` the watcher's (the abi queue still first, for tests). A caught export panic is also recorded as `App._record_failure` records one (`Watcher::record_failure`: `"<export> failed (panic); no submission was made"`, the detail in `errors.log`). car-watcher `surface` (new): the catalog's locale and letters (`locale_of`, `typeface.letters(l10n.catalog(locale))`), the popup's model read and drawn (`snapshot.popup = {view, menus, read, attention}`), the snapshot's `failure_unseen`, `unconfirmed_unseen`, `power_armed`; a `strings` event, a popup call and a seen failure are each followed by a snapshot at once. `post_action` answers `popup` (`ControlPopup`: car-control with actor `gui` and the popup's names), `failure_seen`/`mark_seen` (`acknowledge_failure()`). Feature `panic-test` (car-host -> car-watcher `trip`): `CAR_CORE_PANIC` trips the tick, the toasts worker or an export once |
| `793a74402` | `gui/HostMain.cs`, `gui/HostPump.cs`, `gui/HostStandIn.cs`, `gui/SurfaceJson.cs` (s63's, word for word), `gui/host.manifest`, `gui/host.sources` (`[host]`, `[contract]`, `[standin]`); make_gui.ps1 builds `CodexAutoResume.exe` in the standard run (Q3), gui_stamp kind `host`; rust_release `HOST` staged once for both editions; `tests/test_host_shell.py` |
| `858f8d875` | car-bin `main.rs` -> `main_with(&[])`; the stub is `car-core-proof.exe` (`src/bin/proof.rs`), which the installer proofs and the bootstraps' entry run use |

### Decided here, with the evidence

* **EDITION_BINARIES is not where the host goes.** EDITION_BINARIES is what each edition's workspace builds (cargo's
  `bins`, the budget test, the audit's `PER_EDITION`, whose entries may differ between archives). The host is C# and the
  same bytes in both (Q3), so it is `rust_release.HOST`, in `BINARIES` (the audit's (d) reads it) and not in
  `PER_EDITION`, so the audit's (f) holds the two archives' copies identical. Its subsystem (2) is checked at staging.
* **The real core and the proofs.** Integration 8 kept the stub as the core because the proofs ran it with the
  installer's commands, and the real `setup` writes the Run value, the AUMID and the link handler into the real HKCU
  (a scratch profile does not redirect HKCU). Now the proofs never run the real core: `rust_stage` copies
  `car-core-proof.exe` over the staged `codex-auto-resume.exe` (test_review9_install shares it), and
  `rust_legacy_bootstraps.entry_from_archive` takes the stub built beside car-legacy (`rust/target/release`), not the
  archive's core. The release's own guard is unchanged: a core with the test forward that is not the stub stops it.
* **The host's surfaces until Integration 10**: `[standin]` (`SurfaceRender.Run/Probe` -> null, `HostSurfaces` with no
  icon). Integration 10 deletes `gui/HostStandIn.cs` and the `[standin]` group and takes S6.3's `[surface]` and
  `[generated]` groups; `HostPump.Deliver` already speaks S6.3's `ISurfaces` (SnapshotEvent, StringsEvent).
* **Numbers from the window's JSON reader are doubles**: the host reads `abi` and `exit_code` as doubles (the first run
  refused "abi 1" until it did).

### Proofs

* Rust: `car-host` unit 9; `abi_exports` 3 (`the_release_dll_has_no_panic_wire` reads `CAR_CORE_DLL`); `host_watcher`
  (start, the second start refused, `surfaces` with its seven fields and `locale`/`letters`, a snapshot with `popup` and
  the three keys, the bridge, a popup `set_enabled` drawn as paused in the next snapshot, `failure_seen`, `open_chat`
  `not_ported`, stop, `close`, `ended` 0 last); `panic_feature` (feature on: the first tick's panic recorded and the next
  tick runs, `car_bridge` answers `panic`, is recorded in the log and `errors.log`, and the next call answers);
  car-watcher `toasts::a_panic_in_the_worker_costs_one_notice` (feature on) and `surface` 3.
* Python (`wait_quiet.sh`): `test_host_shell test_host_contract test_guiscan` Ran 32, OK - the DLL-load test (no DLL
  beside the host, a real `car_core.dll` in the current directory and on PATH: exit 1, the launcher's errors.log line,
  no state made; and its own DLL loaded beside a planted non-DLL), the GUI-subsystem check (subsystem 2, no `dpiAware`),
  the mutex handover 1.9 (a) host exits 3 with `runtime/loop.py:104`'s line while the v0.6.26 Python watcher runs, (b)
  the stop event ends Python 0 and the host takes the mutex, (c) the reverse, (d) each killed with a third handle open
  (a named mutex dies with its last handle, so nothing can be abandoned without one): the next watcher of the other
  language logs the abandoned-mutex line first.
* make_gui both editions into scratch folders: window `ec1ae342...`, MCP launcher `382bbb9c...`, advanced window
  `101f257d...` (unchanged), host `1c202eef...` (37,376 bytes, subsystem 2).

### Not done (and why)

* **The engine join** (`app::EngineMaker` over car-engine, discovery and the evaluator; `Given.plug` taking App's
  `Arc<Guarded>`): not started - this seat's context went to the done-check. It needs the harness's `EngineStore` moved
  into a product crate (car-watcher), a `TickEngine` for `car_engine::Engine`, the `Toasts` notifier and `EngineLog`,
  `discover_codex_exe` with car-codex's checks, the Evaluator and layout watch, `engine_moved`'s stamps; then a diff of
  the watch loop with the engine over codexsim. The watcher still logs `EngineNotJoined` and sends nothing.
* `open_dashboard`, `open_chat`, `notice_action`, `notice_complete` answer `not_ported` (the Dashboard opener, cut C6,
  and the notifier's activation are not in a product crate); the `notice` event is still car-watcher's
  `{event, detail, final}`, not S6.3's `{id, key, title, stays, view, letters}` (the notifier seam).
* car-adv-host's `export_core!(<advanced plug factory>)` (with S7.3d): the advanced `car_core.dll` still exports nothing.
* No re-diff command: the host shell has no reference file of its own beyond what car-watcher's `rediff_watcher.py`
  covers (the launcher, the loop); the mutex handover runs against this tree's Python, which is the v0.6.26 final's.

### Risk 3 measured (P6-DESIGN 4.2: the CLR in the watcher)

The host (release `car_core.dll`, the stand-in surfaces, show_tray off) beside the v0.6.26 Python watcher (this tree's
src on Python 3.13), each on its own scratch home, five runs each, medians; private commit 10 s after "watcher started":

| | start to "watcher started" | private commit | working set |
|---|---|---|---|
| host (CLR + car_core.dll) | 1.02 s | 10.8 MiB (10.7-10.9) | 20.2 MiB |
| Python watcher | 3.65 s | 27.8 MiB (27.4-28.3) | 39.7 MiB |

memguard's default limit (1024 MiB, off by default, `memguard.py:31`) fits with room; no re-check with the owner is
needed on this. The commit with S6.3's surfaces drawing (GDI+, the popup) is the 24-hour soak's (Integration 10).

### Checks (`CARGO_BUILD_JOBS=4`, `CARGO_INCREMENTAL=0`, `. tools/rustflags.sh`; rustc 1.100.0; code at `858f8d875`)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0;
                   cargo deny --locked check: advisories, bans, licenses, sources ok
## advanced/rust   fmt rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny: all four ok
cargo test -p car-host -p car-watcher --features car-host/panic-test     every result ok (panic_feature 1, toasts 8)
python -X utf8 rust/tools/check_groundwork.py        rust groundwork: OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0, every binary the same with and without advanced/;
                                                     profile-path scan none
cargo build --release -p car-host; CAR_CORE_DLL=<release car_core.dll> cargo test -p car-host --test abi_exports
                                                     3 passed: the six, and no panic wire in the release DLL
Python (wait_quiet.sh): test_host_shell test_host_contract test_guiscan  Ran 32, OK
```

### For the next seats

* **Integration 10**: drop `[standin]` and `gui/HostStandIn.cs`, take S6.3's host.sources groups; `gui/SurfaceJson.cs`
  and the contract files are identical on both branches. guiscan's `HOST` is `[host]` + `[contract]`.
* **The engine join** (above, "Not done"): `Watcher::start_with(.., maker)` is the seam; car-host's `abi::start` calls
  `Watcher::start` today and would pass the maker.
* **S8.2**: install.ps1's `Get-OwnedWatcherProcess` must learn `app\bin\CodexAutoResume.exe` (1.9); the archive now
  carries the host (`rust_release.HOST`).
* **Mutation checks: NOT run by this seat** (its context ran out after the gates). Proposed for the reviewer, each alone:
  `abi::start` without the second-start refusal (`host_watcher`); `surface::icon_answers` not called in `update_tray`
  (`host_watcher`); `locale`/`letters` dropped from `start_surfaces` (`host_watcher`); `Load` by bare name with flags 0
  (the planted-DLL test); the `tick` trip moved outside `guarded` (`panic_feature`).

### Left for the second part (main session's list of 2026-11-27; this seat stopped at a safe point, context exhausted)

Nothing of the five steps below is started; the tree is clean at this commit.
1. Engine join: move car-harness `engine.rs`'s `EngineStore` into car-watcher (a `join` module; the harness re-exports it);
   car-engine `Given.plug`/`Engine.plug` -> `Arc<Guarded>` (every `Given { plug: Guarded::null() }` in car-harness
   `proxy.rs`/`engine.rs` passes `Arc::new(..)`); `EngineMaker::engine(store, values, managed, plug: Arc<Guarded>)`;
   a `Joined` maker: `App.backend()` (car-config `discover_codex_exe` with car-codex `Backend::_compatible` checks,
   `app_engines`, the engine-word log line, `plug.codex(exe, home)`), `engine_moved` (file stamp, `_served_elsewhere`
   with ELSEWHERE waits), `engine_state`, `_compatibility_tick` (car-codex `Evaluator::tick`, `layout::Watch`), a
   `TickEngine` impl over `car_engine::Engine` (tick, watch_needed, watch, last_usage, detection_failed, handed_waits,
   apply_policy, set_retiring, latest_failures, after_sleep, activity, follow_option), `Toasts(notifier)` and `EngineLog`,
   `home_backend`/`home_engine` (NULL plug, `require_holder`); car-host `abi::start` -> `Watcher::start_with(.., maker)`.
   Prove: `run.py --build --reference v0.6.26 --reference-python bundled -k diffs_watcher` and the detection-check and
   rescan goldens through car-control `Host::checkup`/`rescan_judge`.
2. post_action `open_dashboard`/`open_chat` (ui/tray/dashboard.py, cut C6), `notice_action` (actor "toast",
   car-surface `notifier::activate`), `notice_complete` (`notifier::complete`); the `notice` event as
   `{id, key, title, stays, view, letters}` (car-surface `notice_card::view`); car-adv-host `export_core!(<advanced
   factory>)` with S7.3d, then `abi_exports` with `CAR_CORE_DLL` on the advanced release DLL.
3. `test_rust_release` and `test_rust_install` (both lanes) DETACHED via run_detached.sh + one background wait: both
   timed out at ~580 s in foreground calls here and have no result.
4. The five mutation checks listed above, and `tests/rustdiff/rediff_host.py --reference v0.6.26`.
5. Gates in both workspaces, check_groundwork, check_rebuild; update this section.

### The second part (seat S6.2b2, same branch, 2026-11-27)

**1. The engine join (`0ffdd39fb`).** car-watcher `join`: `store::EngineStore` (moved from car-harness, which
re-exports it; its second field is now a claim hook, `Option<fn(&Claim)>`, the harness's `note.claim`), `engine::Driven`
(TickEngine over `car_engine::Engine`: tick, watch_needed, watch, last_usage, detection_failed, handed_waits,
apply_policy, retiring, `source.latest_failures(since, (), True, True)`, after_sleep, activity, the follow option),
`engine::Words` (car-control's `OnceWords` as the engine's), and `maker::Joined`, the product's `EngineMaker`:
`App.backend()` (car-config `discover_codex_exe` with every candidate's `Backend::compatible` checks kept for the
registry, the app asked through `pairing::app_engines`, its log line, `named_engine`, the engine line in the registry's
word, `plug.codex(exe, home)`), `engine_moved` and `_served_elsewhere` (ELSEWHERE 60 s doubling to 15 min),
`engine_state`, `_compatibility_tick` (car-codex `Evaluator`, a failure "unknown" and recorded) and `_layout_look`
(`layout::Watch`), the engine's keywords (EngineLog in the watcher's one log - App's `Logbook` is now shared,
`SharedLog`, and opened with the engine's STATE codes - Toasts over App's notifier, one dispatch lock, connectivity,
the words for this time, `WATCHER_OPTIONS`), `home_backend`/`home_engine` (NULL plug, `require_holder`, the backend
`home_backend` made reused by the next `home_engine`, as the reference's `run.backend`) and `_recovery_facts` (the
Restart Manager through car-codex's `System::resource_users`). `App.app_runs` is `pairing::app_running_now`. Seams that
moved: car-engine `Given.plug`/`Engine.plug` are `Arc<Guarded>`; car-engine `impl Backend for Arc<T>` (App and the
engine hold one backend); `World::open_store` returns `Rc<Store>` and `World::engine`, `HomesApp::home_engine` and
`Homes::sync` take `&Rc<Store>` (the engine shares the loop's store; `store.close()` at the end closes it once the
engines are gone); `EngineMaker` gained `bind(Bound)`, `refresh_codex_exe` and the plug/values/managed arguments.
car-host's `abi::start` passes `Joined` through `Watcher::start_with`.

The notifier (`App::announce`): `notification_enabled` on the settings in force (shared with the Toasts thread),
the identity, `notifier::build`, `with_open_codex`, the plug told (P20, `told` with a store of its own), and
`notifier::deliver` with no card inbox and an empty presence answer, so the route is the toast
(`notify::show_content` through `SystemPowerShell`). The card route waits for this PC's presence probes (car-platform,
D3: not ported) and the notice event below.

Safety: the host's tests and test_host_shell set `CODEX_AUTO_RESUME_CODEX_EXE` to a file that is not there, so
discovery ends with ConfigError before any candidate is started; `host_watcher` asserts that line ("initialising Codex
adapter failed (ConfigError)") and that EngineNotJoined is gone; `panic_feature` waits for it after the panicked tick.

**2. The actions (`b29a3e138`).** car-watcher `dashboard` (ui/tray/dashboard.py, cut C6: the page and the row checked
first - `row_argument`, PAGES, ROW_DIALOGS - the window asked to come forward through car-platform `handover`, else
started with CREATE_NO_WINDOW; `open_chat` by a canonical UUID alone) and `surface::activate` (App._notice_action:
`notifier::activate` over car-control with actor "toast", the openers, `open_in_codex`, and the toast route for what a
cancel announces). `host_watcher` checks the refusals and that nothing starts where no Dashboard is installed.

**3. Proofs.** `run.py --build --reference v0.6.26 --reference-python bundled -k diffs_watcher -k diffs_bridge_acting`:
Ran 29 tests in 1104 s, OK (the six watcher diffs and the 23 acting diffs, GoldenActsDiff's detection-check and rescan
cases among them). `rediff_host.py` (`ffd55dcb0`) lists the followed files and reruns those and `diffs_engine`,
`diffs_surface_notifier` against a tag. Mutation checks, each alone, all five failed their test: the second-start
refusal removed (host_watcher:20), `icon_answers` not called in `update_tray` (host_watcher:52), `locale`/`letters`
dropped from `start_surfaces` (host_watcher:31), the host started with no maker (host_watcher:116, the join's
ConfigError line), the tick's trip moved outside `guarded` (panic_feature: the loop thread dies).

### Still left after the second part (and why)

* **The card route and the notice event** `{id, key, title, stays, view, letters}`, `notice_complete`: `deliver` needs
  this PC's presence answers (car-surface `seam::Presence`, car-platform has no probe yet: every answer is "cannot
  tell", so the route is always the toast) and a store of posted notices by id for `notice_complete`; watcher notices
  are still car-watcher's `{event, detail, final}`.
* **The detection-check and rescan goldens through the real host**: `SystemHost::checkup`/`rescan_judge` still refuse
  (car-control's defaults); a car-watcher Host wrapper with `checkup::run` (`_conversations`: `passed_over`, the
  engine's `not_taken_up`/`detection_since`) and `judge_for` (an engine with no backend per home) is the next piece.
  The acting diffs pass over the stand-ins as before.
* **car-adv-host `export_core!`** with the advanced factory (S7.3d) and `abi_exports` on the advanced release DLL.
* Small differences recorded here, not hidden: `Words::prune` keeps every entry after `keep` raised and raises after
  car-control's prune (the reference writes nothing when `keep` raises inside the change); the engine's `language` and
  the notifier's locale read the environment's language (Windows' preferred languages are not in car-platform yet, as
  for the icon's strings).
* **`test_rust_release` fails on both lanes, one test**: `EntryRunTests.test_every_bootstrap_line_reaches_the_core` -
  "does not reach the core: missing the core" (car-legacy's exit 1). It came with the first part's `858f8d875`
  (the entry run now takes `car-core-proof.exe` from rust/target/release), which never ran it (both proofs timed out
  there); this part touched neither car-legacy, car-bin nor `build/rust_legacy_bootstraps.py`, and the stub itself,
  run directly in a scratch profile as `<home>\app\bin\codex-auto-resume.exe setup`, answers 3 (NOT_PORTED). Left
  for the main session: why car-legacy's runtime python.exe does not find the stub at `app\bin` in the entry run.

### Checks of the second part (`CARGO_BUILD_JOBS=4`, `CARGO_INCREMENTAL=0`; reference v0.6.26 on the bundled 3.14.10; code at `ec4cfa3a2`)

```
Python (wait_quiet.sh): test_host_shell test_host_contract test_guiscan    Ran 32 in 168 s, OK
test_rust_release, standard and advanced lanes (detached)                   Ran 25, FAILED (failures=1, skipped=1) each:
                                                                            test_every_bootstrap_line_reaches_the_core
test_rust_install, standard and advanced lanes (detached)                   Ran 11, OK (skipped=7) each
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0;
                   cargo deny --locked check rc=0
## advanced/rust   fmt rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny rc=0 (its lock learned the
                   car-watcher -> car-scheduler edge, `507aa8366`)
python -X utf8 rust/tools/check_groundwork.py        OK (17 standard crates, 3 advanced crates) after EXPECTED learned
                                                     car-watcher -> car-scheduler (`c170c6c73`)
bash advanced/rust/tools/check_rebuild.sh            rc=0, every binary the same with and without advanced/;
                                                     profile-path scan none
run.py --build --reference v0.6.26 --reference-python bundled -k diffs_watcher -k diffs_bridge_acting
                                                     Ran 29 in 1104 s, OK
```

### The third part (seat S6.2b3, same branch, 2026-11-27)

**0. The real-engine guard (`9322fee62`, its own commit).** Twice a test reached real discovery and started this PC's
installed codex.exe. car-platform `realengine` names this PC's real Codex by the folders Windows knows
(`SHGetKnownFolderPath`: LocalAppData\OpenAI, LocalAppData\Microsoft\WindowsApps, ProgramFiles\WindowsApps, the
profile's .vscode\extensions, RoamingAppData\npm) - never the environment, which tests point at scratch folders (a
scratch folder under %TEMP% is none of them, so the diffs' planted engines still run). Where the guard is on - the
switch `CAR_NO_REAL_ENGINE`, or a crate's own `cfg!(test)` - car-config's discovery leaves those builds out (the
probes' new `Links::engine_refused`: a candidate skipped, a named one "does not exist", the app's engines not offered),
the process list (car-platform `kernel::processes_named`, car-codex `Platform`) leaves out the Codex app's rows (real
paths, OpenAI.* families), and `SystemStarter::start_guarded(spawn, cfg!(test))` refuses the engine or a `codex:` /
`shell:AppsFolder\OpenAI.*` argument before `Command::new` (error 2, as a missing program). Every car-codex, car-watcher
and car-control start passes its own `cfg!(test)`. The switch is set by car-harness's three binaries (first statement
of main), `tests/rustdiff/core.py` (every diff), `tests/sitecustomize.py` (every interpreter of the suite, so every Rust
child of a Python test), `test_host_shell` and the host's and watcher's Rust tests. `car-watcher/tests/real_engine_guard.rs`
points discovery at the real LocalAppData with the switch set: no real build checked or chosen, a named one refused, no
real row listed, a start refused before `Command::new` (`last_started_flags` unchanged). With the switch's read turned
off it FAILS, naming this PC's two real builds (the bin's and the Store app's) - the exact route of the incidents.

**1. The card route (`98f164066`, `416d867ff`).** car-platform `presence`: notice_presence.py's probes (the shell's
notification state, the two WinRT reads by the reference's IIDs and vtable slots with COM up only where this brought it
up, the screen reader, a remote session, the input desktop's name, battery saver, the dismiss time); on this PC both
sides answer the same. car-watcher `notices`: `presence()` (snapshot under the product's AUMID), `Route::deliver`
(App._deliver: the plug told, then notifier.deliver with the stack's inbox), `_show_watcher_notice` and
`_watcher_notice` (`WatcherNotices`: a final one now as the toast, the rest on their own Toasts; power notices past the
switches) - the old `{event, detail, final}` notice event is gone - and the card announce in `surface::activate` now
uses the inbox and the card setting. `Events` holds App._inbox: `cards_attached` attaches it with a wake that hands
each notice over as `notice {id, key, title, stays, view, letters}` (notice_card.view; fonts._letters of the view's
locale), `cards_detached` ends what was never taken as the toast off the calling thread, `notice_complete {id, shown}`
runs notifier.complete once per id (an id the core never gave answers ok false). Tests: car-watcher `notices` 3,
`host_watcher` (attach, an unknown id, detach).

**3. The advanced DLL (`f846f1ae7`).** car-adv-host: `export_core!(advanced_plug)`, the advanced plug as the core sees
it with no capability on (edition advanced, badge "Advanced", the trait's defaults - plug.py's AdvancedPlug answers as
NULL while nothing is on). S7.3d puts the capabilities behind the same factory. `abi_exports` with `CAR_CORE_DLL` on
the advanced release DLL: 3 passed.

**4. The entry test (`85bfd58f4`).** Cause: `EntryRunTests` still took `rust/target/release/codex-auto-resume.exe`,
which 858f8d875 made the real core, while the proof's own `entry_from_archive` was moved to the stub; the real core
answered the bootstraps' lines itself (car-legacy passes its code through; 1 reads "missing the core"). It now takes
`PROOF_CORE`: Ran 2, OK. No real value changed: this PC's Run value is still the installed Python watcher's, and
neither the AUMID key nor a link handler of ours exists.

### Still left after the third part

* **Step 2, the detection-check and rescan goldens through the real host: NOT done** (this seat's context went to the
  guard, the card route and the proofs). Needed: car-watcher `checkup::run` (settings load/read with the unread
  reason, `managed()`, `sources_for`, `_conversations` - LocalSource `written`/`cloud_tasks`/`passed_over(since,
  now-72h, every_status, newest 200, deadline 10 s)`, an `Engine(store, source, None, clock=now)` with
  `apply_policy(values, held)` for `detection_since`/`not_taken_up`/`managed.disable_auto_resume`, the records by
  thread and turn - `get_status`, `_presence` (now possible: `notices::presence` + car-surface `card_allowed`),
  `_compatibility`, `_skip_lines` over `search_logs`, `lines`), `rescan::judge_for` (an engine with no backend and no
  store per home key, HOME_UNKNOWN, one deadline), and a Host wrapper over car-control's SystemHost answering
  `checkup`/`checkup_for_bundle`/`rescan_judge`, used by `Watcher::bridge` and car-bin's bridge; then the two goldens
  (tests/golden/bridge/detection-check.json, rescan.json) compared through the real host.
* The `demo` event (`App._demo`, `show_demo` over the inbox) is not wired.

**rustflags (`3538dacf2`).** check_rebuild found the scratch checkout's path in the advanced `car_core.dll` once it
exported the six (car-host and car-policy are path dependencies outside advanced/rust). Both `tools/rustflags.sh`
(identical) now remap the repository, found by its car-host crate, to `/repo` first; the workspace's own remap still
wins for its files, so the standard binaries are unchanged.

### Checks of the third part (`CARGO_BUILD_JOBS=4`, `CARGO_INCREMENTAL=0`; reference v0.6.26 on the bundled 3.14.10)

```
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0; test --locked --no-fail-fast rc=0;
                   cargo deny --locked check rc=0
## advanced/rust   fmt rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny rc=0
python -X utf8 rust/tools/check_groundwork.py        OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0 (at 3538dacf2), every binary the same; profile-path scan none
python -X utf8 tests/rustdiff/rediff_host.py --reference v0.6.26     rc=0: diffs_watcher, diffs_bridge_acting (112 golden
                                                     cases, 270 streams), diffs_engine, diffs_surface_notifier equal
test_rust_release, standard and advanced lanes (detached)    Ran 25, OK (skipped=1) each
test_rust_install, standard and advanced lanes (detached)    Ran 11, OK (skipped=7) each
Python (wait_quiet.sh): test_host_shell test_host_contract test_guiscan    Ran 32, OK
CAR_CORE_DLL=<advanced release car_core.dll> cargo test -p car-host --test abi_exports    3 passed
Mutation: realengine::switched() answering false -> real_engine_guard FAILS (discovery checked this PC's two builds)
```

### The fourth part (seat S6.2b4, same branch, 2026-11-27)

**1. Diagnostics' check and Rescan's judge through the real host (`8d222a52f`, `767502254`).** car-watcher
`checkup::run` (with `_conversations`, `_presence`, `_skip_lines`, `sources_for`, `for_bundle`: the settings loaded and
read with the unread reason said second, `managed()`, every home's `written`/`cloud_tasks`/`passed_over(since,
now-72h, every_status, newest 200, deadline 10 s)`, an engine per home with `apply_policy(values, held)` for
`detection_since`, `managed.disable_auto_resume` and `not_taken_up`, the records by thread and turn, `get_status`, the
registry's view through car-control's now-public `bundle_compatibility`) and `rescan::judge_for` (`sources_for` by
`homes::key`, one engine per home key with no store and no backend, HOME_UNKNOWN, one deadline). car-watcher `reading`:
`NoStore`/`NoBackend` are the reference's `None` (every call `AttributeError`), `reading::engine` is `Engine(store,
source, None, clock=lambda: now, home_key=key)` with the reference's defaults, `Reading` the `RescanEngine` over
car-engine's `Engine` (its reader for `rescan_evidence` a second reader of the same home). car-watcher `checkhost::
WatcherHost` wraps any `Host` and answers `checkup`, `checkup_for_bundle` and `rescan_judge`, everything else the
wrapped host's: car-bin's `system_machine` and `Watcher::bridge` (the host's `car_bridge`) use it over `SystemHost`,
car-harness `bridge.run` over its world's host when the world says `real_checks`. car-control: a `ControlError` leaving
the host whole (`Raised::control` / `as_control`, so `checkup`'s `control._open()` refusal answers as `except
ControlError` does) and `Redactor::with_key`.
* **HistoryNotYet** (the main session's input): `checkup::history_not_yet(&Error)` reads the class `"HistoryNotYet"`;
  car-v0627-finalport's car-codex raises it, Integration 11 joins the two (or replaces the body with
  `error.is_history_not_yet()`). Until then a fresh home is `"readable": false` here and true in the tag (AUDIT line).
* **Diffs** `tests/rustdiff/diffs_host_checks.py`: GoldenChecksDiff runs car-watcher over tests/wiregolden.py's own
  installation (made in place: a copied template keeps the template's rollout paths, which is why the copy's Rescan
  answers `unreadable` on both sides) and equals tests/golden/bridge/detection-check.json and rescan.json; CheckupDiff
  (23 worlds, the bundle, an empty and a fresh home) and RescanDiff (10 worlds) equal the tag's `checkup.run` and
  `rescan.judge_for` - replies, files, state and every Host call. Only `checkup._presence` (and, for the golden, the
  aliases' key) are stood in for.

**2. The demo event (`6e105dbc2`).** car-watcher `demo`: the core makes and looks at the demo event
(`DemoEvent(str(paths.state_dir))`, once a second) while the surfaces are up, as the icon did (`ui/tray/icon.py:270-286`),
and each signal runs `App._demo` on a worker: `notifier.build_demo(time.time())`, then `show_demo`'s gates (card setting
exactly True, the host's stack attached, this PC's presence answers) and `Events::post_demo` - `demo {notice}`, the
card's view under an id `notice_complete` ends once. Never a toast. Tests: `demo` 2 (every gate; the look stops).

**3. Checks of the fourth part** (`CARGO_BUILD_JOBS=4`, `CARGO_INCREMENTAL=0`, `CAR_NO_REAL_ENGINE=1` in every run;
reference v0.6.26 on the bundled 3.14.10):

```
run.py --build --reference v0.6.26 --reference-python bundled -k diffs_host_checks   Ran 6, OK: both goldens'
                         cases through car-watcher; detection-check over 24 worlds, rescan over 10, equal to the tag
## rust            fmt --check rc=0; clippy --locked --all-targets -D warnings rc=0 (after the demo log's needless
                   borrow); test --locked --no-fail-fast rc=0; cargo deny --locked check rc=0
## advanced/rust   fmt rc=0; clippy rc=0; test --locked --no-fail-fast rc=0; cargo deny rc=0
python -X utf8 rust/tools/check_groundwork.py        OK (17 standard crates, 3 advanced crates)
bash advanced/rust/tools/check_rebuild.sh HEAD       rc=0 (at 53879617f), every binary the same; profile-path scan none
Mutations, each alone, each failed its test: `brought` with `||` for `&&` (CheckupDiff: the golden home, paused, ...);
  an unknown home key judged by the default home's engine (RescanDiff: a record of a home Settings do not know);
  `history_not_yet` true for a SourceError (CheckupDiff: the history gone, damaged); every home `current`
  (CheckupDiff: a second home - it passed until the case named a list Settings accept, `02773a39d`);
  the demo's card-setting gate dropped (car-watcher demo test).
```

### Still left after the fourth part

* Integration 11: `checkup::history_not_yet` against finalport's car-codex HistoryNotYet, and a diff world of a fresh
  home (a state database with no conversation, no history database).
* rediff: `python -X utf8 tests/rustdiff/rediff_host.py --reference v0.6.26` now includes `diffs_host_checks` and the
  check's and judge's followed files; not rerun whole here (its other four diffs were last run by the third part).
## P6 seat S6.4: the Python UI tests on the C# host (branch `car-v0627-s64`, 2026-11-27)

Writes only `tests/` and this section (Q5 (a)). Nothing in `gui/`, `src/`, `build/` or `rust/` changed; no window was shown, nothing was
captured or drawn on a screen, nothing was pushed. Base `8753199c7` (S6.3 complete).

### What is done

| What | Where | State |
|---|---|---|
| **The ledger**: the 84 test files that import the Python UI (`codex_auto_resume.ui`, `notice_window`, `tray_place`; found by AST, as P6-DESIGN 3.4 counts), one row each: kind (pure 16, drawn 28, window 29, scan 11), its classes by kind, how many of its 1,976 tests touch the UI (985; the rest are `unaffected`), status, and for a row not on the host `why` and `needs` | `tests/rustdiff/surface_ledger.json` | held by `tests/test_surface_ledger.py` (the row set equals the AST set both ways; every class, test and twin a row names is there; the pending count is held to a ceiling that only ever goes down: 66) |
| **Pure, through the shim**: `CODEX_AR_CORE=rust` puts car-surface behind the popup's words (`say`, `one_line`, `kept`, `locale_of`) and view model (`activity`, `light_for`, `icon_attention`, `watcher_known_running`, `snapshot_activity`, `urgency`, `is_waiting`, `_blocked`, `task_item`, `row_menu`, `view_model`, `busy_key`, `select_action`), car-words behind `ui/words.py` (`countdown`, `age`, `clock_time`, `window_name`, `share`, `left`, `usage_windows`, `usage_line`: the `say` it is handed is matched to the catalog it speaks) and car-surface's `snapshot_from` over the store the test hands in; the icon's words (`tooltip_parts`, `tooltip`, `tooltip_joined`, `meter_line`), its menu (`menu_items`) and its state (`icon_state`) are answered by the host's own C# (TrayWords, TrayMenu, TrayMotion) in a probe process | `tests/rustdiff/surfaceproxy.py`, `tests/rustdiff/shim.py` (the names), `tests/rustdiff/surfacehost.py` and `tests/rustdiff/HostProbe.cs` (the test-owned C# entry, compiled with `[contract]`, `[surface]`, `[generated]`; never shown, never loads the DLL) | **102 tests run on it and pass**, and pass on the Python product unchanged |
| **Window behaviour, through the host's probe**: `IconPlacement` (where Windows keeps the icon: the registry, the clock, every read counted) and `OverflowOpen` (is the flyout open) in the host's own code, each test its Python original's body | `tests/test_host_tray_place.py` (16 tests) | twins of `test_tray_icon_motion.PlacementTests` and `test_tray_overflow_open.OverflowOpenTests` |
| **Source scans, re-pointed to `gui/host.sources`**: the popup's and the tip card's shape rules (`HostListTests`, `AskWindowsNothingTests`, `OneDefinitionTests`, `TipCardTests`), the menu's fallbacks (`MenuFallbackTests`), what the surfaces may send, drive and use (`ReachTests`) | `tests/test_host_shape.py` (14 tests) | twins of `test_popup_shape`, `test_tray_tip_shape`, `test_tray_menu_fallbacks` and `test_tray_popup.SafetyTests`; `no_twin` names the tests whose subject is Python's own packaging (re-exports, import order) |
| S6.3's own comparison tests | `test_surface_parity` (21), `test_surface_windows` (8), `test_surface_render_retarget` (4) | rows with status `host`; run one at a time through `gui_lock.sh`: OK |
| The re-diff for the final | `python -X utf8 tests/rustdiff/rediff_ui_tests.py --reference v0.6.26` | lists the UI files and ledgered tests that changed, the test files that import the UI at the tag and have no row, then runs every ledger test the shim runs, and the ledger and the twins, with the tag's package first on the path |

Rows by status: **host 17** (S6.3's three, and 14 more: every UI test of the file is routed, twinned, or listed in `no_twin` with its
reason), **python-only 1** (`test_srcscan`: it tests the Python scanner, the UI's modules are its sample data), **pending 66**
(811 UI tests: drawn 447, window 271, scan 54, pure 39).

**Mutation checks** (each broken alone, the harness rebuilt, the routed tests run on the shim, restored): `words::left`'s clamp 0 to 1
(7 fail), `urgency`'s waiting flag swapped (1), `WEEK_MINUTES` named one more (25); on the host's C# (the twins): the chevron rule
returning true, the flyout counted when cloaked, `LookAgainS` ignored, `NOACTIVATE` dropped from the tip's style, `Windows.Forms` used by
a plan file, `TipGap` 8 to 9, a call the icon makes of the card added, `System.Diagnostics` used, a name `SubmitIt`, `Process.Start`, the
menu's "Show what is waiting ({n})" fallback and "Don't sleep after recoveries" worded otherwise (each fails its test). **One test set did not
fail**: `popup.one_line`'s cut (`limit - 1` to `limit`): no Python UI test asserts the cut (they call `one_line` only to flatten a name), so it is
held by `diffs_surface_popup`'s `WordsDiff` and not here. `app_server_unmatched`'s word in `tray/model.rs` (caught by the final 102, not by an earlier
list made before the icon's tests were routed), the icon state's `attention` mapped to idle (18 fail), `tray.idle`'s fallback (3), and the menu's
"Stop the watcher" fallback (caught by `test_host_shape.MenuFallbackTests`, not by the routed set).

### What is left, and how (every pending row has its `why` and `needs`)

* **Drawn** (447 tests, 25 rows): `test_tray_popup` (layout, placement, motion, elevation, fonts), `test_notice_card` (card layout, stack,
  shadow, motion), `test_tray_icon_motion` (frames, budget, glide), `test_tray_popup_v064`/`_depth`/`_designs`, `test_gui_v0623_days`,
  `test_gui_v065_taskbar`, the motion pictures' tests. The route is the plan dump: a proxy for `ui.popup.layout.layout`, `menu_layout`,
  `tip_layout`, `notice_card.layout` and the placement and motion functions that (1) runs the reference's own call once under
  `tests/test_surface_parity.py`'s `StandIn` to record every measure question and its answer (the job's `tables`), (2) asks the render
  mode for the case with those tables (`surfacehost.run`), exactly as comparison A does, and (3) hands the test the C# plan rebuilt as
  the reference's plan object (items with tuple targets, `Plan` attributes), so the test's own assertions run on the C#. What is not
  built: the dump-to-plan conversion for each surface, and `popup.motion`/`tray.motion` frames (the render mode has cases `popup_motion` and
  `icon`; each test's call shapes have to be mapped to one).
* **Window** (271 tests, 26 rows): `test_tray_menu_drawn`, `test_popup_row_menu_drawn`, `test_popup_access`, `test_tray_tipcard`,
  `test_notice_card.WindowsTests`, `test_tray_tip_messages`, `test_tray_icon_motion` timers/observe/stored. The route is a probe call per
  window class in `HostProbe.cs`, as `placement` and `overflow` are, or the scripts of `test_surface_windows` (`--probe <job>`): a
  script of the Python test's own steps over a window made and never shown, the answer the state after each step. Each Python test's
  stand-ins (a recorded user32) are the same ones `test_surface_windows` already gives the reference.
* **Scan** (54 tests, 8 rows): rules over Python sources with no C# counterpart yet (`test_screenshots` digests, `test_gui_v0623_*`
  wiring), or that move with the pictures' digest (the main session's, B and C).
* **Pure** (39 tests, 7 rows): what takes an object the test hands in - `PopupModel`, `perform`, `Tray.snapshot` callers, the
  Dashboard opener (`tray.dashboard`, car-control's) - needs the ask-back the engine proxy has (`engineproxy.py`'s pipe), which
  `surface.batch`'s scripted cases (`popup.model`, `popup.perform`) stand in for by a case file and cannot give a live object.
* The `ui.words` callables: the proxy matches a `say` to the catalog it speaks and refuses any other (`TypeError`), so a test that
  hands a hand-made `say` is not routed and says so.

### Seams and notes for the next seats

* `surfacehost.py`/`HostProbe.cs` is the one place a test asks the host's C# a question: add a `case` to `HostProbe.Answer` (internal
  members of the surfaces are reachable, it is compiled into the same assembly), a Python wrapper in `surfaceproxy.py` for the Python name
  it stands in for, the module in `shim.SURFACE`. One process serves every call of a run (`CODEX_AR_HOST_SERVE=1`); `run()` is the render mode's
  one-case job. The compiled probe is cached in `%TEMP%\car-surface-host\<digest of the sources and the driver>`.
* The shim's proxies replace names where a module loads: `from ... import view_model` copies made before that (none today) would keep
  Python's. `CAR_SURFACE_PROXY_REPORT=<file>` appends, at exit, how many calls of each op a process routed (a test is not "on the host" if
  its count is zero).
* The count of UI tests: P6-DESIGN 3.4 says 84 files and 2,018 tests; this tree has 84 files and 1,976 `def test_` in their classes (the
  three S6.3 comparison files included), of which 985 touch a UI name or read its source.
* A test file that imports the Python UI and is a host twin is named in `test_surface_ledger.HOST_SIDE`; any other new file that imports
  it needs a row.

### Checks

```
CODEX_AR_CORE=rust PYTHONPATH="src;tests" python -m unittest <the 102 ledger host_tests>     Ran 102, OK
PYTHONPATH="src;tests" python -m unittest <the same>                                              Ran 102, OK
test_surface_ledger test_host_shape test_host_tray_place                                          Ran 37, OK
test_surface_parity, test_surface_windows, test_surface_render_retarget (gui_lock.sh, one each)  OK 21 + 8 + 4
```
No Rust, advanced or `gui/` file changed, so the Rust gates (fmt, clippy, test, deny, `check_rebuild.sh`) are unchanged from S6.3's; `python -X utf8
rust/tools/check_groundwork.py`: OK. Every run set `CODEX_AUTO_RESUME_CODEX_EXE` to a path that does not exist (the main session's notice of
2026-11-27), and the proxy's harness and the host probe set it themselves, so no test of this seat can start this PC's codex.exe.

### S6.4b (continuation, 2026-11-27): the pure group's ask-back, and what is still pending

Writes only `tests/` and this section; nothing in `gui/`, `src/`, `build/` or `rust/` crates changed; no window shown, nothing captured,
nothing pushed. Every run kept `CODEX_AUTO_RESUME_CODEX_EXE` at a missing path. This worktree had no `rust/target`, so the runs used
`CODEX_AR_HARNESS_EXE` = a copy of the `car-harness.exe` built in `car-v0627-finalport` (its car-surface crate is byte-identical to this
tree's; car-words differs only in `bidi_tables.rs`, which no UI test reads).

| What | Where | State |
|---|---|---|
| **`perform` asked back**: car-surface's `popup.perform` case answers each control call by name, so the proxy runs it, makes the *first call it has not answered* on the control layer the test handed in (the reference's next call, because everything before it was answered for real), puts that answer (or the exception's class and `code`) into the spec and runs it again, until no call is new. Each control call is made once, in the reference's order and with the reference's shape (`CONTROL_SHAPES`: `postpone(.., preset=)`, `set_thread_tier(.., interruption_id=)`, `set_project_rule(.., source=)`, `list_pending(source=)` only when a source is given); the Codex `source` is an opaque object the test handed in and goes back to the control layer as that object (a token stands for it on the wire). A perform that would ask one call name twice is refused (`TypeError`), never answered by Python | `tests/rustdiff/surfaceproxy.py` `_perform` | routed |
| **`PopupModel` by replay**: every step the test took is sent again with the question as the `popup.model` script case takes them; attributes are read from the state after the last step (`drawn`/`drawn_tasks` from the last `view`); `rows` and `status` set together become one successful read, anything else assigned is refused (`TypeError`) | `_popup_model` | routed |
| Held to the reference call for call: every action x five answer sets (values, refusals with a code, other exceptions, a raising `list_pending`) x source/no source x opener (none, true, false), and every step of a model script, the wrapper's result against `__wrapped__`'s on recording objects | `tests/test_surface_askback.py` (5 tests; skipped without `CODEX_AR_CORE=rust`) | OK |
| Newly routed: `test_dont_postpone.PopupTests` (2), `test_observe_and_admission` (1), `test_postpone_and_tiers.PopupRowMenuTests` (5), `test_tray_popup` ActionTests/ActivityTests/ViewModelTests and others (the probe `car-v0627-s64-probe2.py` ran every pure class of the pending rows alone: 138 of 140 pass, 57 route at least one call) | `host_tests` of their rows | ledger |

Ledger: **host 20** (was 17: `test_dont_postpone`, `test_light_parity`, `test_observe_and_admission`), **pending 63** (ceiling 66 to 63), python-only 1.
`test_light_parity.TableTests` (4) and `test_dont_postpone.NeverToAModelTests` (1) are `no_twin` with their reasons (the table against
constants; the MCP package's tool list): they ask the UI for nothing it computes.

**Mutation checks** (proxy broken one rule at a time, `test_surface_askback` run, restored): `postpone`'s `preset` as positional, `set_thread_tier`'s
`interruption_id` as positional, `list_pending` called with a `None` source, the source token handed on instead of the object, `begin` not remembered by the
model, `busy` returned as strings, a raised control error answered as a value: **7 of 7 fail**.

### What is still pending, and why (S6.4b did not reach it)

* **Pure, 63 -> the rest**: the Dashboard opener (`ui/tray/dashboard.py`: `open_dashboard`, `open_chat`, the hand-over to an open window) has no case in
  `car-harness`; its Rust is `car-platform/src/handover.rs`. `test_notice_click_chat`, `test_tray_reuses_window`, `OpenerTests` and `test_tray_open_popup`
  need a harness case over `handover::hand_over` and the process start (a Rust change, so not this seat's), then a proxy beside `perform`'s. Their rows say so.
* **Scan**: the ledger's scan counts include tests whose subject is not the UI - found by listing each scan class's tests against the UI names in their
  bodies: `test_compat_surfaces` (McpTests, PrivacyTests: the MCP status and the registry's imports), `test_control` (the control layer's refusal codes and
  stop), `test_plug_points.MovedTests` (the store's plug calls), `test_surface_properties.JournalIsWriteOnlyTests`, most of `test_screenshots`
  (the pictures' manifest and run tool), `test_tray_shape` (the Python tray package's own file order). Those are Python-source scans of the Python product; they
  stay on it, and the rows need the per-test count re-made (the ledger's `ui_tests` is by class) before they can be `host` with `no_twin` reasons. Those that read
  `gui/*.cs` (`test_gui_v0623_*`, `test_focus_rings`, `test_tray_reuses_window.WindowSideTests`) need a twin in `tests/test_host_shape.py`'s way.
* **Window** (271) and **drawn** (447): not started. The route is unchanged from S6.4's notes (a `case` per window class in `HostProbe.cs`; the plan dump rebuilt
  as the reference's plan objects). `test_card_shadow_under_body`, for one, compares the Python card's GDI+ layers pixel by pixel: its C# twin needs
  `CardWindow`'s layers dumped by a new probe call.
* The re-diff: `python -X utf8 tests/rustdiff/rediff_ui_tests.py --reference v0.6.26` now also runs `test_surface_askback` against the tag's package.
* The proxy's `PopupModel` is built only for the test modules in `surfaceproxy.PROXIED_FOR`: Python's own popup window (`codex_auto_resume.ui.popup.window`) and the tests that hand a model to it (`test_surface_windows`, `test_tray_popup`, ...) keep
  the original model, which it sets `strings` and `wants_read` on as it runs; the window is what the C# host replaces (found by the re-diff: `test_surface_windows`
  drove the Python window with the proxy and failed on `model.strings = ...`).
* The re-diff also prints a test file the tag has and this tree lacks: `test_status_newest_usage.py` (it imports the UI at v0.6.26 and has no row; it arrives
  when this branch is rebased onto the final, and needs a row then).
* `rediff_ui_tests.py --reference v0.6.26` no longer runs `test_surface_*` under the shim: those are S6.3's comparisons of the C# host with the Python window,
  whose reference side must stay Python's (under `CODEX_AR_CORE=rust` its words are Rust's, and the run did not end in 25 minutes); `rediff_host_surface.py`
  re-runs them against the tag. Result at the end of S6.4b (through `gui_lock.sh`): 129 ledger tests + `test_surface_askback` on the shim against the tag
  pass, the ledger and the host twins pass (`test_status_newest_usage.py` listed as above).

### S6.4c (continuation, 2026-11-27): the scan group re-counted, and the first window rows on the probe

Writes only `tests/` and this section; nothing in `gui/`, `src/`, `build/` or `rust/` changed; no window shown, nothing captured, nothing
pushed. Every run kept `CODEX_AUTO_RESUME_CODEX_EXE` at a missing path and `CAR_NO_REAL_ENGINE=1`; the shim runs used
`CODEX_AR_HARNESS_EXE` = S6.4b's copy of the finalport `car-harness.exe` (this worktree has no `rust/target`).

| What | Where | State |
|---|---|---|
| **Step 1 not possible here**: `tests/test_status_newest_usage.py` is a v0.6.26 file (commits 2d0ee345e, 755b6294c on dev/main) that this base does not have: `car-v0627-rust` at 8cbcd6ac3 does not contain the v0.6.26 tag, and `domain/usage.newest` is not in `src/`. A row for a file that is not there fails `test_surface_ledger` ("a row names a file that no longer imports the UI"), so the row waits for the rebase onto the final; `rediff_ui_tests.py --reference v0.6.26` prints it as "with no row" until then. | - | left |
| **Scan, re-counted per test** (step 2): in every scan class of a pending row, a test that names no UI module and reads no UI source is `unaffected` (the Dashboard window's own C# - `test_gui_v0623_*`, `test_focus_rings`, `test_notice_stay`, `WindowSideTests`' first test -, the compat registry's closure, which reaches no UI module, the engine's and the store's sources, the demo module); a scan of the whole Python package (srcscan's `modules`, `package_asts`, `holders`, `closure`, `sites()`, every shipped `src/*`) is `no_twin` with its reason (the UI's modules are only its sample; nothing of the UI is called or computed); the Python tray package's own packaging (`test_tray_shape.ShapeTests`, five) is `no_twin`, naming the host's counterpart rule; a rule that holds a UI value or reads the Python icon's source has a twin. | `tests/rustdiff/surface_ledger.json` (applied by a scratch script; the decisions are the rows' `no_twin`/`twins`) | ledger |
| Twins read from the port's sources: `EditionTwinTests` (the panel's heading and the Dashboard's version line name no edition where the host's `TrayWords.UnnamedEdition` names none; the watcher's surfaces event carries `edition::shown(plug)`, `HostPump`/`HostSurfaces` hand it to the icon, every tooltip `TrayIcon` makes is given it), `VocabularyTwinTests` (car-surface's `STATES`, `ATTENTION_OVERLAYS` and the host's `IconStates` by test_vocabulary's own digests and vocabularies), `HandoverTwinTests` (the Dashboard's WM_COPYDATA mark and answer against car-platform's `handover.rs`) | `tests/test_host_shape.py` | 20 tests, OK |
| **Window, first rows** (step 3): `card_layers` (a NoticeCard with no window, both layers through PaintLayers at the settled frame, pixels dumped; the uncut shadow is a second card's whose image says nothing is wholly opaque, so CutUnderBody clears nothing), `icon_tick` (a TrayIcon with no window, Observe + SyncMotion under SurfaceScreen's probe record, the timers left), `icon_overflowed`, `icon_demo` (LookForDemo over a stand-in event; OpenDemo of an icon named for no demo). The probe's `Answer` is an if-chain now, no string switch (S6.3d's reproducible-build rule). | `tests/rustdiff/HostProbe.cs` | compiled by `surfacehost.py` |
| The twins over them: each subclasses the Python test class and keeps its assertions - inherited helpers, or the original bodies through `super()` - with only the hook that made the Python window (`settled`/`each_look`, `tick`) answered by the host | `tests/test_host_card_layers.py` (3), `tests/test_host_icon_tick.py` (5), `tests/test_host_icon_demo.py` (1) | OK through `gui_lock.sh`, one module at a time |
| The re-diff runs every file a row names as a twin's home | `tests/rustdiff/rediff_ui_tests.py` | see Checks |

Ledger: **host 28** (was 20: `test_control`, `test_compat_surfaces`, `test_plug_points`, `test_vocabulary`, `test_edition_label`,
`test_card_shadow_under_body`, `test_tray_overflow_open`, `test_diagnostics_tools`), **pending 55** (ceiling 63 to 55), python-only 1.

**Mutation checks** (each alone, restored with the file's own bytes): `TrayWords.UnnamedEdition` misspelt (3 fail), `IconStates` without "failed"
(2), car-surface's `codex_changed` renamed (2), `OPEN_REQUEST_TAKEN` off by one (1), one `TrayWords.Tooltip` call given `null` for the edition
(1), `HostSurfaces` dropping the edition (1); CutUnderBody's opaque test at 0xFE (6), the cut one pixel wider (2), the probe's uncut pass
cutting (2); `Overflowed` ignoring the flyout (4), asking the flyout first (1), Observe not asking `Overflowed` (1); LookForDemo acting on an
unsignalled look (1) and OpenDemo making an event with no name (1). One mutant survived and is equivalent here: SyncMotion's
KillTimer made a SetTimer - a fresh icon's `MotionMs` is already null, so neither runs (the Python test cannot see it either).

### What is left (per row, the route), for the next seat

* **Pure** (24 tests, 4 rows): `test_notice_click_chat` 2, `test_popup_row_menu_parity` 11 (OpenerTests, RemoveTests, OpensTheDashboardTests),
  `test_postpone_and_tiers` 1, `test_tray_reuses_window` 10, `test_single_rules.PageTests` 1 (and `test_tray_open_popup`'s opener tests among its
  window count): the Dashboard opener. Route unchanged (step 5): a car-harness case over car-platform's `handover.rs` and the process start
  through a scratch stand-in, then a proxy for `open_dashboard`/`open_chat` beside perform's. Not started: the seat's time went to steps 2-3.
* **Window** (248 tests, 23 rows): `test_tray_menu_drawn` 36, `test_popup_row_menu_drawn` 27, `test_tray_tipcard` 22, `test_popup_access` 21,
  `test_tray_tip_messages` 17, `test_popup_card_still` 14, `test_gui_v0623_surfaces` 12, `test_popup_card_window` 11, `test_popup_opening_motion` 11,
  `test_tray_open_popup` 11, `test_popup_motion_held` 10, `test_surface_properties.TrayMenuTests` 9, `test_failure_seen.IconTests` 6,
  `test_menu_opening_motion` 6, `test_card_focus` 5, `test_tray` 5, `test_tray_menu_no_glow` 5, `test_corners_by_design` 4, `test_tray_shape.CompositionTests` 4,
  `test_tray_tip_header_ink` 4, `test_motion_popup` 3, `test_notice_click` 3, `test_notice_stay.CardTests` 2. Route: the pattern of
  `test_host_icon_tick.py` - subclass the Python class, keep its bodies through `super()`, answer only its window-making hook with a HostProbe
  call that makes the C# window unshown under `SurfaceScreen.Probe` (which records every window call instead of making it), sets the same
  stand-ins the test patches (TrayIcon's `Ask*`, `IconRectReader`, `DemoTaken`; the menu's and popup's own seams), runs the private steps by
  reflection and reports state. `test_corners_by_design` is drawn-like (Renderer pixels of the popup, the menu and the tip): the render
  mode's `pixels` surface gives them.
* **Drawn** (424 tests, 25 rows): not started; the plan proxy of S6.4's notes (record the measures under test_surface_parity's StandIn, run
  the render mode, rebuild the reference's plan objects) is the route. The largest: `test_tray_popup` 80, `test_tray_icon_motion` 60,
  `test_notice_card` 57, `test_tray_popup_v064` 42, `test_gui_v0623_days` 31, `test_gui_v065_taskbar` 27, `test_tray_popup_depth` 22.
* **Scan** (39 tests, 3 rows): `test_screenshots` 34 (the pictures' manifest, digests and run tool: the main session's, B and C - it moves
  with the pictures), `test_motion_tray_story` 4 (the tray story's frames are drawn by the UI's motion: a drawn route, not a scan),
  `test_single_rules.PageTests` 1 (the opener, above).
* `test_status_newest_usage.py`: a row once this branch has the v0.6.26 tests (above).

### Checks

```
test_host_shape test_surface_ledger test_vocabulary test_edition_label test_tray_shape          Ran 72, OK
test_host_card_layers / test_host_icon_tick / test_host_icon_demo (gui_lock.sh, one each)      OK 3 / 5 / 1
test_surface_ledger test_tray_overflow_open test_host_tray_place test_host_card_layers          Ran 36, OK
test_card_shadow_under_body, test_diagnostics_tools (the Python originals)                     OK
CODEX_AR_CORE=rust: test_tray_tip_whole test_edition_label.TooltipTests test_app_server_surfaces.IconTests
  test_tray_menu_fallbacks (the probe's tray_words, menu_items, icon_state through the if-chain)  Ran 13, OK
python -X utf8 tests/rustdiff/rediff_ui_tests.py --reference v0.6.26 (gui_lock.sh, detached)
  129 ledger tests on the shim pass, the ledger and every twin home pass; no row: test_status_newest_usage.py   exit 0
```
No Rust, advanced or `gui/` file changed, so the Rust gates (fmt, clippy, test, deny, `check_rebuild.sh`) are S6.3's and Integration 11's;
`python -X utf8 rust/tools/check_groundwork.py`: OK.

### S6.4c, second part (the coordinator's go-on, 2026-11-27): where it stopped

The context ran low after one more row; this is where the next seat starts. `test_tray_shape` is host: `CompositionTests`' five are the Python
Tray's mixin composition (which class defines what, the MRO, the file of `class Tray`), `no_twin` with their reasons, naming test_host_shape's
OneDefinitionTests and HostListTests. `test_screenshots` stays pending with the reason "moves with the pictures (main session's pass)".
Ledger: **host 29, pending 54** (ceiling 54), python-only 1. `test_status_newest_usage.py` waits for Integration 12's merge of the final.

Left, in the coordinator's order (every count is UI tests not yet held):
1. **Window, 244 tests, 22 rows** - the `test_host_icon_tick.py` pattern. Found while reading them:
   * `test_surface_properties.TrayMenuTests` (9): the Python `_act(MENU_*)` calls the icon's callbacks; the host's `TrayMenu.Act` (private,
     gui/TrayMenu.cs) posts `HostActions.Toggle/OpenDashboard/Stop` through `IHostActions` instead. A probe `icon_act` (a TrayIcon with a
     recording IHostActions, Act by reflection) and a twin that maps each posted action to the callback the test wired (OpenDashboard page
     None = on_open, page "pending" = on_pending, Toggle(paused) = on_toggle, Stop = on_stop); `test_the_window_is_only_ever_opened_on_a_page_it_has`
     is the opener's (step 2).
   * `test_failure_seen.IconTests` (6): `test_a_failure_turns_the_icon_red_and_says_so_when_hovered` is already routed by the shim (icon_state,
     tooltip: add it to host_tests), `test_every_language_says_it` is l10n only (unaffected); the other four drive the Python icon's control
     layer, which on the port is the core's (`failure_unseen` rides the snapshot, `TrayIcon.FailureUnseen`; the seen mark is a posted action,
     gui/TrayIcon.cs near `Actions == null || !...failures`): a probe over those two and a twin per test.
   * the rest as listed in "What is left" above, largest first: `test_tray_menu_drawn` 36, `test_popup_row_menu_drawn` 27, `test_tray_tipcard` 22,
     `test_popup_access` 21, `test_tray_tip_messages` 17, `test_popup_card_still` 14, `test_gui_v0623_surfaces` 12, `test_popup_card_window` 11,
     `test_popup_opening_motion` 11, `test_tray_open_popup` 11, `test_popup_motion_held` 10, `test_menu_opening_motion` 6, `test_card_focus` 5,
     `test_tray` 5, `test_tray_menu_no_glow` 5, `test_corners_by_design` 4 (Renderer pixels: the render mode's `pixels` surface),
     `test_tray_tip_header_ink` 4, `test_motion_popup` 3, `test_notice_click` 3, `test_notice_stay` 2.
2. **Pure, 24 tests** - the Dashboard opener: a car-harness case over car-platform's `handover.rs` with a scratch stand-in for the process
   start, then its proxy beside perform's; `test_single_rules.PageTests` with it. Not started.
3. **Drawn, 424 tests** - the plan proxy; `test_motion_tray_story` (4) by the drawn route. Not started.
4. `test_screenshots` (34): pending, "moves with the pictures (main session's pass)" - done.

### S6.4f (2026-11-27/28): the drawn rows on the plan proxy

Writes only `tests/` and this section; nothing in `gui/`, `src/`, `build/`, `rust/` or HostProbe.cs/surfaceproxy.py changed; no window
shown, nothing captured, nothing pushed. Every run kept `CODEX_AUTO_RESUME_CODEX_EXE` at a missing path and `CAR_NO_REAL_ENGINE=1`; the shim
runs used `CODEX_AR_HARNESS_EXE` = S6.4b's copy of the finalport `car-harness.exe` (no `rust/target` here; the plan proxy needs none).

| What | Where | State |
|---|---|---|
| **The plan proxy**: under `CODEX_AR_CORE=rust` a test's own call (the caller's module is a `test_*` one; the product's callers keep Python's) of the icon's motion (`icon_frame`, `icon_frame_ms`, `icon_turn`, `icon_brand_state`, `icon_head_colour`, `icon_level_colour`, `icon_motion_allowed`), the popup's motion (`halo`, `animates`, `opening`, `closing`, `face_amount`, `face_length`, `mixed`, `glide_amount`, `next_glides`), placement (`place`, `taskbar_edge`, `hit_test`, `focus_order`, `next_focus`), elevation (`lift_coverage`, `well_coverage`, `shadow_step`, `recipe_shadows`, `tile_ground`), `share_columns`, `role_size`, `contrast_colour`, and the card's `entrance`, `leaving`, `rise_vector`, `hold_ms`, `stack_direction`, `stack_positions`, `float_shadows`, `shadow_at`, `depth_level`, `shadow_margin`, `premultiply` is answered by the host's own C# | `tests/rustdiff/planproxy.py`, `tests/rustdiff/PlanProbe.cs` (its own entry, compiled with `[contract]`, `[surface]`, `[generated]` into `%TEMP%\car-plan-host\<digest>`; one process per run, one JSON line a question) | routed |
| **Layouts through the render mode**: `layout.layout(vm, scale, measure)`, `Renderer.layout(vm, scale, locale)` and `notice_card.layout` run the reference once with the measure recorded (the test's `measure`, or this machine's DrawTextW through a recording `_dll`), keyed as `SurfaceText.Measure` asks (role, text or " ", width at least 1, flags); the render mode (`SurfaceRender.RunJob`, case `popup` in "en" or the locale given, case `card`) lays the case out from that table alone; the dump is rebuilt in the reference's container kinds (`shaped`: tuples and floats where the reference has them; every value, item, key and order the C#'s) | `planproxy._recorded`, `_renderer` | routed |
| **`CardMotion` by replay**: a test's `notice_card.CardMotion(...)` is the host's: every step resent as the render mode's `card_life` case, the answer and `phase`/`since`/`hold_left`/`from_alpha`/`exit_ms`/`paused`/`final`/`gone` read from the last step; anything else read or set is refused | `planproxy._HostCardMotion` | routed |
| Masks keep the C#'s sharing: a key's mask is one Python object in the module's own `_MASKS` under ("host", key), so `_MASKS.clear()` and `is` behave as the C#'s cache says | `planproxy._elevation` | routed |
| Registration: `shim.PLAN` (eight modules: `ui.tray.motion`, `ui.popup.motion/placement/elevation/layout/renderer/fonts/theme`, `notice_card`), patched before SURFACE's proxy of the same module | `tests/rustdiff/shim.py` | - |
| `CAR_PLAN_PROXY_REPORT=<file>` appends each process's routed calls per test id; `CAR_PLAN_MUTATE=<rule>` breaks one answer on purpose (drop, shift, colour, text, frame, turn, halo, place, edge, glide, mask, life, stack, shadow, entrance) | `planproxy.ask` | for the checks only |

**Rows** (a test is taken when it passed on the shim, the proxy routed at least one of its calls, it is in a UI class of its row, and its
body hands no plan to Python's own drawing - draw/pixels/card_still/_Painter/frame() - plus four read by hand and left out: two of
`test_day_frame_cost` (the Python painter's brushes), `test_tray_popup_designs.WindowGateTests`' still, `test_tray_popup_v064`'s
two-theme images). 148 tests found, 145 kept in `host_tests` (three of `test_picture_popup_face_pinned` and `test_motion_card_strip` route a call but assert Python's fonts or picture); `test_words_fit` and `test_motion_logo` are host whole; **host 31, pending 52**
(ceiling 54 left for the integration), python-only 1.

| Row | UI tests | added | on host |
|---|---|---|---|
| `test_tray_popup` | 117 | 42 | 79 |
| `test_tray_icon_motion` | 73 | 28 | 41 |
| `test_notice_card` | 63 | 27 | 33 |
| `test_tray_popup_v064` | 42 | 10 | 10 |
| `test_tray_popup_depth` | 22 | 10 | 10 |
| `test_squircle_shadows` | 13 | 8 | 8 |
| `test_gui_v065_taskbar` | 27 | 4 | 4 |
| `test_right_to_left` | 8 | 4 | 4 |
| `test_social_motion` | 4 | 3 | 3 |
| `test_words_fit` (host) | 3 | 3 | 3 |
| `test_gui_v0623_days` | 31 | 2 | 2 |
| `test_motion_card_strip` | 4 | 1 | 1 |
| `test_tray_cards`, `test_motion_tray_story`, `test_motion_logo` (host) | 15, 4, 1 | 1 each | 1 each |

**Mutation checks** (`CAR_PLAN_MUTATE`, each rule alone over the taken tests of a row; `scratchpad/s64f/mutate.sh`): 23 rule-row runs; every row the proxy routes fails at least one: `test_tray_popup` shift 26, colour 15, text 15, place 7, edge 1, halo 11, glide 3, mask 2; `test_tray_icon_motion` frame 6,920, turn 195; `test_notice_card` life 5, entrance 36, stack 8, shadow 4, drop (card layout) 990; `test_tray_popup_v064` shift 4,158, step 8; `test_squircle_shadows` mask 4; `test_gui_v065_taskbar` frame 2,241; `test_social_motion` frame_at 1, turn 2; `test_motion_logo` frame 1; `test_motion_tray_story` frame_at 1; `test_motion_card_strip` frame_at 2; `test_right_to_left` shift 156; `test_words_fit` shift 2; `test_tray_cards` life 1; `test_gui_v0623_days` scene 2; `test_tray_popup_depth` shadow 1, shift 10. Survivors, each caught by another rule of the same row: `drop` on the popup's LayoutTests (the last item is the focus ring the tests skip), `mask` on v064's dark lift (one middle byte the model's samples do not reach; `step` fails it), `frame` on the social and tray-story schedules (a level off everywhere keeps their equalities; `frame_at` fails them).

### What is left (per row, the route), for the next seat

* **Not routed, drawn** - each needs one more op in PlanProbe.cs (no gui/ change): the icon's raster frames (`build_icon_frames`,
  `IconFrames`, the frame table and budget: TrayMotion/IconMark `Samples`/`Pixel`; `test_tray_icon_motion` FrameTests/BudgetTests,
  `test_gui_v065_taskbar` 23, `test_social_motion` 1, `test_motion_card_strip`, `test_motion_tray_story` 3); the fonts (`font_faces`,
  `font_candidates`, `message_face`: a `lacks` callable asked back and Windows' own face; `test_tray_popup.FontTests`, `test_typeface`,
  `test_glyph_coverage`, `test_language_faces`, `test_picture_popup_face_pinned` 4); `notice_card.corner_coverage` (**host gap**: no C#
  counterpart found by name - `test_notice_card.ShadowTests` 2, `test_squircle_shadows.CardCutTests`); the theme readers
  (`effective_theme`, `theme_setting`, `set_reduce_motion`, `reduced_motion`: registry reads under a stand-in; `test_tray_popup_v064`
  ThemeResolutionTests, `test_settings_unreadable`, `test_tray_cards.AppWiringTests`, ReduceMotionSettingTests); `notice_presence`'s policy
  (`test_notice_card.PolicyTests`, not a drawing: its row part may be re-kinded).
* **Drawn by Python** (~60): tests that hand the host's plan to Python's `Renderer.draw`/`card_still`/`pixels` and read pixels. Route: the
  render mode's serve (gui/SurfaceRenderServe.cs `open_renderer`, `layout`, `draw`, `pixels`, `card_still`) behind a proxy of `Renderer`
  whose `draw` and `canvas.pixels()` are the host's; `test_tray_popup_depth.PixelTests`, `_designs.DesignRendererTests`, `_v064.DarkRendererTests`,
  `test_gui_v0623_days.PopupSceneTests` 12, `test_day_wide_cards`, `test_right_to_left` 4, `test_focus_rings`, `test_day_frame_cost`.
* **Window parts of drawn rows** (WindowsTests, TimerTests, NextOpenTests, ...): the probe route (S6.4d's HostProbe.cs).
* `test_screenshots` (34): the pictures' pass (main session).

### Checks

```
sweep (gui_lock.sh, one module at a time, CODEX_AR_CORE=rust, the plan proxy's report): the 26 pending drawn rows' files and
  test_gui_v0623_surfaces, test_popup_card_still, test_popup_opening_motion, test_tray, test_motion_popup, test_tray_tipcard   all rc 0
test_surface_ledger                                                                                         Ran 7, OK
rediff_ui_tests.py --reference v0.6.26 (gui_lock.sh, detached): 274 ledger tests on the shim pass (129 before), the ledger and
  every twin home pass; no row: test_status_newest_usage.py (waits for Integration 12)                      exit 0
```
No Rust, advanced or `gui/` file changed, so the Rust gates are Integration 11's; `python -X utf8 rust/tools/check_groundwork.py`: OK.
The re-diff: `python -X utf8 tests/rustdiff/rediff_ui_tests.py --reference v0.6.26` (runs every row's host_tests on the shim, the plan
proxy with them): 274 pass, exit 0.

### S6.4f2 (continuation, 2026-11-28): the host draws, and the icon's frames, the fonts and the theme's choices

Writes only `tests/` and this section; nothing in `gui/`, `src/`, `build/`, `rust/`, HostProbe.cs or surfaceproxy.py changed; no
window shown, nothing captured, nothing pushed; every run kept `CODEX_AUTO_RESUME_CODEX_EXE` at a missing path and `CAR_NO_REAL_ENGINE=1`.

**The re-diff was hollow before this seat** (S6.4e's finding): the bundled runtime never imports tests/sitecustomize.py, so
`rediff_ui_tests.py`'s "on the shim" run ran on the tag's Python. S6.4e's SHIM_UNITTEST (090b0b70b) is taken over in `0faf9fc2d`; with
the shim really loaded the 274 ledger tests of S6.4f still passed (278 ran with test_surface_askback; exit 0). The module sweeps of
S6.4f and of this seat ran on the system Python with `PYTHONPATH=src;tests`, which does import sitecustomize: they were real.

| What | Where | State |
|---|---|---|
| **A test's `popup.Renderer()` is the host's**: `Renderer.__new__` answers a test's call (not a subclass's, not the product's) with a `HostRenderer` over the C#'s `SurfaceRenderer` kept in the plan probe; its look (theme, design, contrast, lone, sweep_ms) is sent with every call; `use`, `measure`, `lines`, `fonts` (faces, key), `layout` (the C#'s own, in the reference's container kinds), `draw`, `draw_halo`, `draw_scene`, `halo_rows`, `face_colours`, `canvas.pixels()`/`width`/`height` and `layers.card_still` are the C#'s; a picture comes back as raw BGRA in the probe's folder, read by path | `planproxy.HostRenderer`, `PlanProbe.cs` `renderer_*` | routed |
| **Kept plans**: `layout.layout`, `notice_card.layout` and a Python renderer's `Renderer.layout` now ask `layout_kept` (the same `PopupLayout.Plan`/`CardPlan.Layout` the render mode's case calls, from the recorded measure table) and get a `HostPlan` (a dict, plus the probe's handle), so the host renderer draws the plan the test holds; a plan the test changed after, or a dict of its own, is refused (`handle_of`) | `planproxy._recorded`, `HostPlan` | routed |
| The face a test stands in for Windows' UI font (`fonts.windows_ui_face`, or a `message_face` it patched) is the C#'s `SurfaceFonts.Pinned`, as a render job stands one in | `HostRenderer._stand_in`, `Look` | routed |
| **The icon's raster frames**: a test's `IconFrames(...)` and `build_icon_frames(...)` are the C#'s `IconFrames` (ground, compose, `heads` and `_mark` read from its private tables by reflection, `is` held where the C# answers from its store, ArgumentException -> ValueError, KeyNotFoundException -> KeyError; the budget is `TrayMotion.BuildBudgetMs` over the test's clock, as TrayIcon checks it) | `planproxy._HostIconFrames`, `icon_frames_*` | routed |
| **The fonts**: `font_faces`, `font_candidates`, `message_face` are `SurfaceFonts.FontFaces`/`FontCandidates`/`UiFace`; a `lacks` the test hands in is **asked back** over the same pipe (`{"ask": "lacks"}` out, its answer or what it raised back; `Probe.ask(_callbacks=...)`) | `planproxy._fonts_faces`, `PlanProbe.AskBack` | routed |
| **The theme's choices**: `theme_choice`, `effective_theme`, `appearance`, `design_choice` are `SurfaceTheme`'s. The adopted settings (`set_theme`, `theme_setting`, `set_reduce_motion`, `reduced_motion`, `adopt_settings`, ...) stay Python's: the product's own callers set that one state and a test reads it (the sweep showed a second, C# state reading 'system' where the watcher had adopted 'dark'); their ops are in PlanProbe.cs for a twin | `planproxy._theme_readers` | routed (choices) |
| **`notice_card.corner_coverage` is the host's**: S6.4f's host gap was a name only - it is `CardCorner.Coverage` (gui/CardWindow.cs) | `planproxy._corners`, `corner_coverage` | routed |
| The tray story's two glide-frame tests: a **twin** on the host's `PopupMotion.GlideFrameMs` (PlanProbe `constant`); test_host_tray_story.py is in test_surface_ledger's HOST_SIDE | `tests/test_host_tray_story.py` | twins |
| Registration: `shim.PLAN` gains `ui.popup.layers` (one line) | `tests/rustdiff/shim.py` | - |

**Rows** (the take, `scratchpad/s64f/ledger2.py`: passed on the shim, routed, in a drawn class of its row, draws only on the host
renderer where it draws, touches no Python-only drawing; window-kind classes are S6.4d's and were not taken): 83 found, **52 added**
to my rows' `host_tests` plus 2 twins after the mutation checks (20 routed tests no rule failed are left out, 11 belong to window rows);
`test_focus_rings` and `test_language_faces` are host whole; **host 33, pending 50** (ceiling 54 left for the integration).
Added: test_tray_popup 9 (FontTests 8, HighContrast 1), test_gui_v0623_days 8, test_tray_icon_motion 6 (FrameTests 4, BudgetTests 2),
test_typeface 5, test_tray_popup_v064 5, test_tray_popup_depth 4, test_day_wide_cards 3, test_squircle_shadows 3 (CardCutTests),
test_tray_popup_designs 2, test_picture_popup_face_pinned 2, test_motion_tray_story 2 twins, test_focus_rings 1, test_language_faces 1,
test_notice_card 1, test_glyph_coverage 1, test_gui_v065_taskbar 1.

**For S6.4d / the integration (window rows, not written by this seat)**: drawn tests of window rows that pass on the plan proxy and
fail a mutation rule - test_popup_card_still AloneTests 3 (corners cut, premultiplied, nothing round the card), test_popup_opening_motion
ArithmeticTests 3 + FaceDrawnTests 2, test_gui_v0623_surfaces PopupSweepDrawnTests 1 + TaskbarTests 1, test_motion_popup PopupDrawnTests 1.

**Mutation checks** (`CAR_PLAN_MUTATE`, each rule alone over every newly taken test, `scratchpad/s64f/mutate2.sh` + `killed.py`;
per test, not per row): ink 11, pixels 11, face 11, theme 5, shift 4, raster 2+3, corner 2, glide 1; then over the survivors alpha 3,
turnpos 5, open 3, facefirst 5, cornerall 1, premultiply 1, size 1, contrast 1, refuse 1, budget 1, kept 1, scene_ms 1; the twins fail
`constant`. 20 survivors left out of host_tests: test_gui_v0623_days IconTests 3 + PopupSceneTests 5, test_tray_popup_designs
DesignRendererTests 3, test_popup_card_still AloneTests 2, test_gui_v0623_surfaces PopupSweepDrawnTests 2, test_day_wide_cards 1,
test_glyph_coverage 1, test_motion_card_strip 1, test_notice_card ShadowTests 1, test_typeface 1 (each needs a rule that reaches what
it holds - most compare two host pictures with each other, so a rule must break one and not the other).

### What is left (per route), for the next seat

* **Fails on the shim now, honestly** (passed before only because the test's renderer was Python's): tests that read or patch the
  Python renderer's internals - `_text` patched (test_right_to_left 4), `_images`/`_image`/`_ground_key` (test_tray_popup 1,
  test_tray_popup_designs 1, test_tray_popup_v064 2), its GDI+ object count (test_tray_popup 1), `brand.speck_frame` patched under it
  (test_day_wide_cards 1, test_day_frame_cost 1), a plan dict of its own handed to draw (test_tray_tipcard 2), the host renderer passed
  into Python's `CardLayers.shade` (test_popup_card_still ShadowLayerTests). None is in a row's host_tests. A host answer needs the
  C#'s private caches read (SurfaceRenderer `images`, `groundKey`, `Image()`, `SurfaceGdip.GdipObjects`: their keys are strings, the
  Python's tuples) or a twin; the `_text` patch needs a draw-without-words switch the C# does not have (**host gap**: SurfaceRenderer).
* **Not routed**: the icon's card renderer (`TipRenderer`: tip_layout, draw_tip, draw_tip_light - a HostTipRenderer over
  `SurfaceRenderer.TipLayout`/`DrawTip`, same pattern); `tipcard.tip_place` (TipCard.TipPlace needs the kept plan); the tray story's
  DrawnTests TIP_GAP test (needs both); `typeface.language_face`/`lacks` themselves (win/typeface.py is not a UI module);
  `notice_presence`'s policy; the window parts (S6.4d's probe).
* `test_screenshots` (34): the pictures' pass (main session).

### Checks

```
sweep 3 (gui_lock.sh, one module at a time, CODEX_AR_CORE=rust, report): the 26 drawn rows' files and the 6 others; rc 1 only where
  listed above as "fails on the shim now, honestly" (test_day_frame_cost, test_day_wide_cards, test_popup_card_still, test_right_to_left,
  test_tray_popup, test_tray_popup_designs, test_tray_popup_v064, test_tray_tipcard)
test_surface_ledger + test_host_tray_story                                        Ran 10, OK; CAR_PLAN_MUTATE=constant: the twins fail
rediff_ui_tests.py --reference v0.6.26 (shim really loaded, ids read from a file): 326 ledger tests + test_surface_askback,
  Ran 330 OK; the ledger and the host twins (test_host_tray_story among them), Ran 55 OK      exit 0
```
No Rust, advanced or `gui/` file changed, so the Rust gates are Integration 11's; `python -X utf8 rust/tools/check_groundwork.py`: OK.
The re-diff: `python -X utf8 tests/rustdiff/rediff_ui_tests.py --reference v0.6.26`. Its shim run now reads the ids from the
file `CAR_UI_REDIFF_IDS` names (`SHIM_UNITTEST_FROM_FILE`): at 326 ids one command line passed Windows' 32,767 characters
(WinError 206). A harness note: the probe has one stand-in for Windows' UI font (`SurfaceFonts.Pinned`), so a test that
patches `message_face` to answer None (Windows could not be asked) gets the C# asking Windows instead; no taken test does.

### S6.4f3 (continuation, 2026-11-28): the renderer's own state, plans of a test's own, the shadow window and the icon's card

Writes only `tests/` and this section; nothing in `gui/`, `src/`, `build/`, `rust/`, HostProbe.cs or surfaceproxy.py changed (shim.py:
the PLAN registration line only); no window shown, nothing captured, nothing pushed; every run kept `CODEX_AUTO_RESUME_CODEX_EXE` at a
missing path and `CAR_NO_REAL_ENGINE=1`. The eight tests S6.4f2 left failing on the shim (they had passed only while their renderer was
Python's) are answered by the host where the C# can be asked, and named as host gaps where it cannot:

| What | Where | State |
|---|---|---|
| **The renderer's kept state**: a host renderer's `_images` (SurfaceRenderer `images`, read by reflection; each C# string key rebuilt as the reference's tuple by parsing `KeyOf`'s form; the same C# image is the same Python object), `_ground_key` (`groundKey`, its parts string parsed again into a tuple of parts), `_image(mask, shadow)` (the private `Image` on a ShadowMask made from the mask the test holds) and an image's `_pixels`; `gdiplus_objects()` of a test's own call is the Python's count plus the probe's `SurfaceGdip.GdipObjects` | `planproxy.HostRenderer`, `_key_of`, `_HostImage`, `_gdiplus`; PlanProbe `renderer_images`, `renderer_image`, `image_pixels`, `renderer_ground_key`, `gdiplus_objects` | routed |
| **A plan of the test's own** (a dict it built, or a host plan it changed after) is drawn by the host as the C#'s SurfacePlan of the same fields (`plan_from_dict`: targets as SurfaceTarget, a whole-number rect as int[]); before, it was refused | `planproxy.plan_handle`, PlanProbe `PlanOf` | routed |
| **Drawn without its words**: a test that stands a no-op in for the renderer's `_text` gets the C#'s Draw of the plan less its text items (only the words and the card-alone seal read them; a lone renderer is refused) | `HostRenderer._text`, `_words`; PlanProbe `Wordless` | routed |
| **Stood-in specks**: `brand.speck_frame` patched to answer no speck, or every speck whatever band is asked, is drawn by the C# with SurfaceDays' own tables changed for the call (`Specks`/`Reaches` emptied, or every reach made infinite) and put back; any other stand-in is refused. The C# keeps its culling by height (out of the band, where its clip shows nothing either) | `planproxy._specks`, PlanProbe `WithSpecks` | routed |
| **The shadow window's layers**: `CardLayers.shade(renderer, plan)` with a host renderer is the C#'s `CardLayers.Shade` on a CardLayers of no window kept in the probe; the layers' `picture` (pixels, size, close), `margin`, `shadows`, `images` and `_drop_images` are then the C#'s | `planproxy._card_layers`, `_HostLayers`; PlanProbe `layers_*` | routed |
| **The icon's card**: a test's own `tipcard.draw_offscreen` and `tip_place` are the host's (`HostTipRenderer`: `TipLayout`, `DrawTip`, `DrawTipLight`, the GDI metrics and ink of `Text.Calc`; `TipCard.TipPlace`; `SurfaceRenderer.TipDay`). A `TipRenderer()` the test makes itself stays Python's (those tests patch its `_lift`/`_inner`) | `planproxy.HostTipRenderer`, `host_tip_renderer`, `host_tip_place`, `_tipcard` | routed |
| A host renderer starts from the C#'s own first look (`renderer_open` answers SurfaceRenderer's Theme, Design, Contrast, Lone, SweepMs), as the Python's starts from its own | `HostRenderer.__init__` | - |
| The tray story's hover-card placement (DrawnTests, TIP_GAP): a **twin** whose body runs with the Python's TipRenderer, tip_place and TIP_GAP standing in as the host's (HostTipRenderer, TipCard.TipPlace, PlanProbe `constant` tip_gap) | `tests/test_host_tray_story.py` DrawnOnHostTests | twin |
| Registration: `shim.PLAN` gains `ui.popup.gdiplus` and `ui.tray.tipcard` (one line) | `tests/rustdiff/shim.py` | - |

**Rows** (`scratchpad/s64f/ledger4.py` over sweep 4, then `ledger5.py` less the mutation survivors): 26 tests added to my rows'
`host_tests` and one twin; `test_typeface` and `test_motion_tray_story` are host whole; **host 35, pending 48** (ceiling 54 left for
the integration), python-only 1, on_host 457. Added: test_gui_v0623_days 7 (IconTests 2, PopupSceneTests 5), test_tray_popup_designs 4,
test_tray_popup_v064 3, test_right_to_left 3, test_tray_popup 2 (WindowsTests' two renderer-only leak tests, drawn by intent, taken at
the main session's word), test_day_wide_cards 2, test_day_frame_cost 1 (`test_the_specks_in_sight_are_all_drawn`, hollow before: the
host ignored the patched speck_frame), test_motion_card_strip 1, test_notice_card 1, test_tray_icon_motion 1, test_typeface 1, and the
tray story's third twin. `test_tray_popup_v064 test_flipping_the_theme_all_day_holds_no_more_images` was hollow before too (it counted
the Python's GDI+ objects only).

**Mutation checks** (`CAR_PLAN_MUTATE`, each rule alone over the 26, `scratchpad/s64f/mutate4.sh` + `killed4.py`; per test): every one
fails at least one rule - scenegone 8, defaultdesign 3, sceneedge 3, leak 3, pixels 3, ink 3, groundkey 2, lookbody 2, lookring 2,
sceneshown 1, hcdrop 1, imagesame 1, frozen 1, flat 1, images 1, rise 1, words 1, specks 1, symbolface 1, imagekey 1, bandtop 1, and
raster/turnpos for the icon's head test; the new twin fails `constant` and `tipplace`. The 20 survivors S6.4f2 left: 17 now fail a rule
of their own (above); the other three are not the drawing and stay off the host:
* `test_gui_v0623_days IconTests.test_an_ordinary_icon_is_the_icon_it_always_was`: both sides ask the C# the same question (`look=None`
  is the Python signature's default), so a host answer only compares with itself; its subject is the Python's default argument.
* `test_glyph_coverage GlyphCoverageTests.test_the_panel_has_a_glyph_for_every_character_in_its_type_stack`: its subject is the panel's
  CSS type stack (a browser's fallback); the one host answer it reads is Windows' UI face name.
* `test_popup_card_still AloneTests` 2 and `test_gui_v0623_surfaces PopupSweepDrawnTests` 2: window rows (S6.4d's), not written here.

**Host gaps for the C# seat (S6.3e; never edited here)**:
* gui/SurfaceRenderer.cs `DrawText`: the DrawTextW flags (DT_RIGHT, DT_RTLREADING, ...) are worked out inline and handed straight to
  P/Invoke, so nothing can read the (text, flags) a frame draws - `test_right_to_left PopupMirrorTests.test_every_line_is_aligned_right_
  and_read_right_to_left_but_a_name_in_its_own_direction` patches the Python's user32.DrawTextW. Needs e.g. an internal
  `TextFlags(PlanItem, SurfacePlan)` the loop calls, or a draw log a probe can switch on.
* gui/SurfaceRenderer.cs `Scene`/`SceneShape` and gui/SurfaceGdip.cs `SurfacePainter`: no count of the pieces a frame fills nor of the
  brushes it makes - `test_day_frame_cost PopupFrameTests.test_a_frame_fills_no_speck_out_of_sight` (patches `Renderer._scene_shape`)
  and `test_a_frame_makes_each_colour_s_brush_once` (`_Painter._brush`). Needs a piece and brush counter (or a hook) a probe can read.

**Item 4, `win/typeface.py`'s `language_face` and `lacks`**: not routed, on purpose. `test_language_faces` (host whole since S6.4f2)
holds the host's `font_faces` to `typeface.language_face` as the expectation - routing it would hold the C# to itself; `test_typeface`
hands `typeface.lacks` in as the `lacks` the C# asks back (its subject is `font_candidates`, routed). `language_face`'s C# counterpart
is the window's (gui/SoftTheme.cs), S6.4d's.

**For S6.4d / the integration (window rows, not written by this seat)**: now passing on the shim through the routes above and failing a
mutation rule - test_tray_tipcard DrawTests 3 (the meter drawn in the ground and the warning bar, plans of their own: dictplan; High Contrast: pixels, ink) and PlaceTests 2 (tipplace); test_popup_card_still ShadowLayerTests 2 (nothing of the shadow under the card: alpha; one image a shadow: layerimages, leak); test_day_wide_cards TipCardTests.test_the_card_takes_the_day_at_its_outer_side (pixels, ink; a window-kind class of a drawn row, left to the integration as S6.4f2 left window-kind classes). Routed and passing but failing no rule of scratchpad/s64f/mutatew.sh yet: test_tray_tipcard DrawTests.test_a_frame_of_the_light_redraws_only_its_band and test_plan_and_draw_take_at_most_30_ms_at_150_percent, test_day_wide_cards TipCardTests.test_none_in_high_contrast_or_classic. And `test_corners_by_design` (window row) fails on the shim since S6.4f2's host renderer: the test reads
`renderer._corner` and `renderer.canvas.smoothing`, which HostRenderer does not answer (a C# `Corner`/`Canvas.Smoothing` op would).

### What is left (per route), for the next seat

* The two host gaps above (S6.3e), then their two tests by the same plan proxy.
* `TipRenderer()` made by a test itself (test_tray_tipcard 3, test_corners_by_design): a HostTipRenderer would answer them, but they patch
  the Python renderer's `_lift`/`_inner`, which the C# has no hook for (the "no lift, no inset light" half of the card test).
* The adopted theme settings (set_theme, theme_setting, reduced_motion), kept Python's (S6.4f2's reason); `notice_presence`'s policy;
  the window parts (S6.4d's probe); `test_screenshots` (34, the pictures' pass).

### Checks

```
sweep 4 (gui_lock.sh, one module at a time, CODEX_AR_CORE=rust, report): the 26 drawn rows' files, the 6 others, test_corners_by_design,
  test_tray_tip_header_ink: rc 1 only for test_day_frame_cost and test_right_to_left (the two host gaps) and test_corners_by_design
  (window row, above)
test_surface_ledger + test_host_tray_story                                        Ran 12, OK
rediff_ui_tests.py --reference v0.6.26 (shim really loaded, ids from a file): 352 ledger tests + test_surface_askback,
  Ran 356 OK; the ledger and the host twins (DrawnOnHostTests among them), Ran 57 OK                    exit 0
```
No Rust, advanced or `gui/` file changed, so the Rust gates are Integration 11's; `python -X utf8 rust/tools/check_groundwork.py`: OK.
The re-diff: `python -X utf8 tests/rustdiff/rediff_ui_tests.py --reference v0.6.26`.

## Seat S7.4: the measurement harness, `measure.py` + `evidence.py` (branch `car-v0627-s74`, 2026-11-27)

The owner's Q2 (a): ported to car-adv and proved equal to the **v0.6.26 final** over the tests' kind of fakes only.
Nothing here was ever run for real: no codex.exe, no Codex app, no turn, no Codex home.

### Ported (module -> crate)

| Python | car-adv |
|---|---|
| `evidence.py` (whole) | `evidence` (`build`, `path_for`, `complete`, `outcome`, `write`, `CLOSED_WORDS`, the alias and the diagnostics' four expressions as `search`; records written text-mode, CRLF) |
| `measure.py` `Context`, `probe`, `run`, `complete`, `_threads_valid`, `_versions`, `_iso`, `_completed_status`, `_goal_status`, `_await_taken`, `_await_turn` | `measure` (seams: `SessionFactory`/`MeasureSession`, `World` = time/monotonic/sleep/uuid4, `Hand`s, `Cli`, `Look`, `BackendView`, `Timing` = the module constants the tests patch; `Raised` = what `probe` turns into a verdict and what leaves `run`) |
| probes M1 M2 M2b M3 M5 M6 M7 MH MA MQ MT MW | `measure` |
| MP1 MP2 MP3, MU MN MR (`_mcp_servers`, `_settings_tool`, `_read`, `_running`, `_changed`) | `measure_usage.rs` (a `#[path]` child of `measure`, so no `lib.rs` edit) |
| MIPC MAWS MCLOUD (`str.splitlines` as Python splits) | `measure_looks.rs` |
| M6B (`_word`, `_settings`, `_follow`, `_unsubscribed`, `_app_running`) | `measure_stage4.rs` |
| `runtime.py` `run_measurement`, `complete_measurement` | `runtime::measurement` (`Measuring` = the runtime's `measure_*=`/`evidence_dir=` seams, kept beside the runtime since `runtime/mod.rs` is S7.2a's; `Live` = the `measure.live_*` builders) |

**Not ported (28 probes, `Raised::Unported` from `run`), and what each waits for:** M4 (`_lock_users` over
`resource_users`, the m4_hook_note hand), ME (S7.2e1's `emptyreply.EMPTY_KINDS`), MS (S7.2e1's `subagent.kind_of`), MK,
MO (pairing's `session_kind`), MX, MXA, MF, M3B, MB, MB2 (S7.2e1's `retries`, S7.2b's `account.parse`, a scratch home),
MC1, MC2 (`_Watch`), MQO, MQP (threads), MQG, MTOK (sqlite, rollouts), MOPEN, MAL, MALR (S7.2b's `restart`), MWAKE, MHK,
M4B, MANCHOR (S7.2e2's `anchor`), MIMG (`images`), MSTEER, MSTEER2 (`ipc`), MGAVE, MPROFILE, MSWAP (S7.2b's `authfile`,
`swap`, `account`), MAUTO; and the `live_*` builders (`live_backend`, `live_session_factory`, `live_launcher`,
`live_cli`, `live_ipc`, `_ipc_look`, `live_hands`, `_profile_read`, `_account_swap`, `_wait_for_look`), which touch the
real install and are S7.3d's to wire through `runtime::measurement::Live`. The seat's time went to the harness, the
diffs and these 22 probes; the list is in `tests/rustdiff/advledger_s74.py` (`PORTED`) and `measure::ported()`.

### The seams

* `evidence::default_directory()`: the first `docs/evidence/live` above the running program (the reference's is four
  parents above its own source file, which a binary does not have and must not carry: check_rebuild); else a path that
  is not there, so `write` refuses as the reference refuses an installed copy.
* `measure::versions(backend, product_version, windows_build)`: `config.version()` and `sys.getwindowsversion()` are the
  caller's (`Live::product_version`, `Live::windows_build`; car-platform has no Windows-version reader yet).
* `BackendView::app_identity`: core's pairing look (`backend.app_identity()`), None where the backend has none.
* `MeasureSession` is implemented for adv72d's `codex::session::Session` (enter = initialise, `declined_count`).

### The proof (`tests/rustdiff/advmeasure.py`, `diffs_advmeasure.py`, example `advmeasure`)

The reference is the tag's own `measure`/`evidence` (`advref.run`, bundled 3.14.10) with `measure.time`, `measure.uuid`,
`measure.config`, `measure.sys` and the timing constants replaced; the probe drives car-adv's `measure` with the same
script. Each case compares the answer (or the class raised) and **every call the fakes saw, in order** (opens, enter,
calls with params, drains, declined counts, exit, clock readings, sleeps, ids, hands, CLI, IPC, launcher, app look),
then every evidence file left, byte for byte. `run.py --reference v0.6.26 --reference-python bundled -k
MeasureEvidenceDiff -k MeasureProbeDiff -k MeasureUsageDiff -k MeasureLookDiff`: **Ran 12, OK** (151 s), about 2,100 cases:
evidence over ~70 values/texts, 448 builds, 16 seeded files x 6 completions, 12 records; the 22 probes each through no
session, `{}`, 12 odd answers, 6 raises, failed opens and enters, a thread, versions read or unreadable, a missing
folder, a pre-1970 clock; M2b x 32 goal/queue scripts, M6 x 108, M6B x 75, MW x 23, MP1 x 145 listings, MU x 17, MN x
~130, MR x 50, MIPC/MAWS/MCLOUD x 270 helps. Each batch must be mostly answered, not refused at the door: the first
green runs were vacuous (the cases spelt `M1` where the word is `m1`, so both sides raised ValueError) and the
mutation checks said so; with the words right the diffs found four port bugs, all fixed: `_iso` refused times before
1970 (the reference's gmtime takes down to -43200), `complete` read the record with serde (now car-machine's
`compat::loads`, which takes NaN, the infinities and a lone surrogate as `json.loads` does), a lone surrogate failed
before the file was opened (now after, the file emptied), and MR refused a reading with no windows (`full` reads
`windows or ()`).

Safety (the main session's notice of 2026-11-27): the reference refuses `inuse.backend`, `pairing.processes_named`,
`resource_users`, `process_identity`, `win.inventory.resource_users` and every `measure.live_*`, and both sides run
with `CODEX_AUTO_RESUME_CODEX_EXE` naming a file that is not there. car-adv's `measure` has no discovery of its own:
it reaches an engine only through a `SessionFactory`/`Live` its caller hands in, and the harness hands only fakes.

Mutation checks (scratchpad `car-v0627-s74-mutate.py`, each alone, `advmeasure` rebuilt, its diff class run, the file restored): an alias with a final newline refused, records written with LF, a refusal by Codex recorded as blocked, M6 never interrupting its turn, MU reading twice, MR counting down by two, MCLOUD ignoring `unknown`: **7 of 7 caught** (on the second run; the first, on the vacuous cases, caught 1 of 7 and so exposed them).

The re-diff for the final: `python -X utf8 tests/rustdiff/rediff_s74.py --reference v0.6.26`.

### For later seats

* The proxy seat (S7.2a3): the 21 files of `advledger_s74.py`; every one waits for the proxy, most also for probes above.
* S7.3a: the Dashboard's `measure` / `measure-verdict` call `Runtime::run_measurement` / `complete_measurement` with a
  `Measuring`; a `Raised`'s `class()` is the reference's exception class.
* S7.3d: implement `runtime::measurement::Live` (the real session over car-codex's backend, MW's WMI chain, the hands).
* The next S7.4 seat: port the probes above in that order, each a case family in `diffs_advmeasure.py`, and move it
  into `measure::ported()` and `advledger_s74.PORTED`.

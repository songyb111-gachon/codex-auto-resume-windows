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
bash advanced/rust/tools/check_rebuild.sh HEAD       NOT RUN: the disk (838 GB) had 0.2-4.6 GB free during this seat and the
                                                     check builds three release trees; its scan is proved by --self-test and
                                                     the planted binaries above
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

The full runs, the frozen modules and the guards run detached after this commit (scratchpad `long.sh`); their result is
the seat's report's, and the next integration's to record if this section does not.

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

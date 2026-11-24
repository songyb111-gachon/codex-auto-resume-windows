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

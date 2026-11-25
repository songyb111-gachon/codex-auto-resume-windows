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
running / 1 stopped / else unknown; `downgrade-state` exactly one line `downgrade: converted a b c d e` or `downgrade: nothing`
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
  only, by `edition_audit.one_word`'s rule for (c); every other literal and every name is still looked for.
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

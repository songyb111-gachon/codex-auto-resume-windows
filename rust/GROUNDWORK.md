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

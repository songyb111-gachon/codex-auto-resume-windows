# tests/rustdiff: the differential harness

The Rust core port (v0.6.27, `PLAN.md` section 4) proves each piece it ports by running the same input through
the reference and through Rust and comparing the outputs byte for byte (D12). The reference is a tag's own
Python (D17: the v0.6.26 tag; until it exists, `v0.6.26-beta.2` stands in, `reference.STAND_IN`), taken out
of git by `tests/released.py` and run in a process of its own on scratch homes.

| Piece | Where | What it does |
|---|---|---|
| reference | `reference.py` | the tag's tree (`released.package`), run with every home in a scratch folder, PYTHONPATH the tag's `src` alone, no console window; answers are kept as bytes |
| Rust | `rust/crates/car-harness` (PLAN 1.2 row 17, `publish = false`) | `car-harness serve`: JSON-lines calls, the framing `controlcli serve` uses; `car-core-stub`: the stand-in for `codex-auto-resume.exe` (`bridge`/`mcp`/`cli` + the Python entry point's argv) |
| Rust, from Python | `core.py` | where the binaries are (`CODEX_AR_CORE_EXE`, `CODEX_AR_HARNESS_EXE`, `CARGO_TARGET_DIR`, else the crate's release build), `build()`, `stub()`, `Harness` |
| shim | `shim.py` | `CODEX_AR_CORE=rust`: the entry points' `main` runs the Rust binary (below) |
| diffs | `diffs.py`, `diffs_*.py` (each seat's own: `diffs_store.py`, S1.2) | the comparisons, as unittest cases; run.py loads `diffs.py` and then every `diffs_*.py` in name order. The folder has no `__init__.py` (a namespace package) and no `test*.py`, so the lanes' discovery never enters it: it imports nothing of it and runs none of it |
| ledger | `LEDGER` | tests that fail on Rust only for reading a Python internal, each with its reason; only shrinks; empty |
| entry point | `run.py` | the one command CI and a person run |

## The entry point

```
python -X utf8 tests/rustdiff/run.py --build
```

From the repository root, on any PYTHONPATH. `--build` runs `cargo build --release --locked --manifest-path
rust/crates/car-harness/Cargo.toml` (CARGO_BUILD_JOBS 4 unless set), then every diff. Exit 0 identical, 1 a
difference or a failure, 2 binaries missing. `--reference TAG` names another reference; the tag must be in the
checkout (CI fetches the tags; a missing one fails there, as in `tests/released.py`). The crate is a member of
the `rust/` workspace: its build goes to `rust/target` and its lock is `rust/Cargo.lock`.

## The shim's seam

`tests/sitecustomize.py`, the existing seam: Python loads it in every interpreter with `tests/` on its path,
so it is in place before any test imports the product, and in the child Pythons a test starts with the same
path. Under `CODEX_AR_CORE=rust` it loads `shim.py` by path and `install()` puts one finder first on
`sys.meta_path`: `codex_auto_resume.controlcli`, `.mcpserver`, `.mcp.server` and `.cli` load as always and
then their `main` is replaced by one that runs `car-core-stub <entry> <argv>`, hands it the test's stdin when
the command reads it (`serve`, an argument `-`, the MCP server), writes its bytes to the test's stdout and
stderr, and returns its exit code. The tests call `controlcli.main([...])` (or import `main`), so replacing
the attribute after the module runs reaches every one of them, and nothing else of the module changes.

`scripts/test_parts.py`'s lanes run with `PYTHONPATH=src`, where sitecustomize is not loaded (the guards have
the same gap, which `no_real_toast()` closes), so `work()` calls `rust_core()`, which does the same under the
same variable. Without the variable sitecustomize looks at `os.environ` once (already imported by `site`)
and `rust_core()` returns False: no module loaded, nothing patched.

Not here yet: the `Engine`, `Store` and `LocalSource` proxies over car-harness (S4.2); a `serve` that streams
a live pipe (the shim reads the whole input first, as a test's StringIO allows); `python -m
codex_auto_resume.<entry>`, which runs as `__main__` and never passes the finder (no test does that today);
the child Pythons of a test_parts lane, which start with `PYTHONPATH=src` and so run Python.

## The runs (2026-11-24, reference v0.6.26-beta.2, rustc 1.100.0, SQLite 3.54.1 bundled)

The whole harness (the build cached; from clean it took 1 min 46 s):

```
$ CARGO_BUILD_JOBS=4 python -X utf8 tests/rustdiff/run.py --build -v
reference v0.6.26-beta.2; rust rust/target/release
test_defaults (rustdiff.diffs.DefaultsDiff.test_defaults) ... ok
test_both_seams_reach_rust (rustdiff.diffs.ShimRoutes.test_both_seams_reach_rust) ... ok
test_no_variable_no_shim (rustdiff.diffs.ShimRoutes.test_no_variable_no_shim) ... ok
test_record_states (rustdiff.diffs.StateFixtureDiff.test_record_states) ... ok

Ran 4 tests in 11.340s

OK
defaults: reply 2098 bytes, settings.json 2244 bytes, identical to v0.6.26-beta.2 and to the golden
shim: controlcli.main ran car-core-stub through tests/sitecustomize.py and test_parts' lane
shim: without CODEX_AR_CORE, controlcli.main is Python's and the shim is not loaded
state fixture: 27 records (schema 5) written and opened by v0.6.26-beta.2's store, the same 29 values read by car-harness (SQLite 3.54.1)
```

### 1. The bridge's `defaults`

Reference: the tag's `controlcli.main(["--home", H, "defaults"])` in its own Python. Rust:
`car-core-stub bridge --home H defaults`. Each on a fresh scratch home and profile. The reply lines are
compared with each other and with `tests/golden/bridge/defaults.json`'s reply written as the wire writes it
(`json.dumps(reply, ensure_ascii=False)` and `\n`); the `settings.json` each wrote are compared too.

```
reference exit 0 reply 2098 32194a494c6ded06 settings.json 2244 260c66058bf5c876
rust      exit 0 reply 2098 32194a494c6ded06 settings.json 2244 260c66058bf5c876
golden           reply 2098 32194a494c6ded06
```

(sha256, first 16 hex digits.) The diff catches a difference: with `--reference v0.6.10`, whose defaults
have fewer settings, `test_defaults` fails "the reply line differs from the tag's" and run.py exits 1.

### 2. One state fixture

The tag's own store writes a `state.sqlite` with one record in each state it knows and a conversation switched
off (`released._WRITE_STATE`, as the released-tree tests write v0.6.10's), then opens it and answers each
record's state and the schema version. `car-harness serve` opens the same file with car-store (S1.2; until then
a read-only rusqlite stand-in, `state.rs`, now gone) and answers `store.record_state` for every key (and one key in no record: `null`) and `store.schema_version`.
Each reply line equals `json.dumps({"id": n, "reply": {"ok": true, "value": <the reference's value>}})`:
27 records, schema 5, 29 values, identical.

### car-brand (`diffs_leaves_brand.py`, S1.1)

`python -X utf8 tests/rustdiff/run.py -k Brand -k CssDiff -k PaletteDiff -k LightDiff -k MarkDiff -k ShapeDiff -k DaysDiff
-k TrayDiff` (8 tests, about 20 s). gui/Brand.cs from car-brand's `make_brand::render()` is the committed file (`git show
HEAD:gui/Brand.cs`, LF) and the tag's own `build/make_brand.py` `render()`, byte for byte (149,471 bytes); every function
of brand/css.py, and the brand functions the panel, the popup and the window read, over about 88,000 generated cases,
floats by their JSON text. The tables are the tag's, written by `gen_brand.py --write` (`--check` says whether
`car-brand/src/tables_gen.rs` is stale). Two of Python's `math` functions are not Rust's: `math.hypot` is CPython's own
(the C runtime's `_hypot` differs from it in the last bit for about one pair in six), so car-brand carries CPython's
algorithm (`pyfmt::hypot`); `math.erfc` is the C runtime's in both, called through one `extern "C"` declaration.

### 3. The state store (S1.2, `diffs_store.py`, car-store)

`car-harness serve` answers `store.script` (open a `Store` with `migrate`, `check` and a pinned `clock`, then a list
of `{"method", "args", "kwargs"}` named as the Python's methods), `store.legacy`, `store.downgrade` and
`store.open_state` (a Windows stand-in for the install lock and the watcher's mutex). The reference runs the same
request through the tag's store (`_RUNNER`). Each answer line must equal the reference's value written as the wire
writes it, and every state file is compared by a dump in a stable order: user_version, application_id, journal mode,
page size, every sqlite_master object, every table's rows by rowid with each value's type, integrity, and the
forensic copies with their time taken out of the name.

Run 2026-11-25 (`run.py --build -v`, 17 tests, 219 s, all OK):

```
fresh state: created and marked by car-store, the same file as v0.6.26-beta.2's (schema 5, mark 0x43410505)
migrations: v0.3.2 (schema 1, 16 records), v0.5.6 (schema 2, 21), v0.5.7 (schema 2, 21), v0.6.10 (schema 3, 27),
  v0.6.13 (schema 4, 27) each upgraded to the same schema-5 file, the same forensic copy and the same 14 reads;
  the same UpgradePending without migrate
readable-from: a schema 6 marked readable from 5 opened and written alike; unmarked, marked from 6 or with schema 5's
  mark, StateFromNewerVersion alike
refusals: 8 broken states refused with the same class and sentence, check on and off
script: 140 store calls (18 refused alike) gave equal answers and the same file; v0.6.26-beta.2's store read
  car-store's file and car-store the reference's, 14 reads equal
journal: 5,500 entries pruned by age and by count to the same 5123
downgrade: a rich schema-5 state to 4, 3 and 2 gave the same report and file; refusals alike
legacy store: v0.5.7, v0.6.10 and v0.6.13 states as LegacyStore, 18 calls each equal, the same file
open_state: 43 policy and Windows combinations over a v0.6.10 state opened the same store, the same file
connection: foreign_keys=1, synchronous=2, trusted_schema=0, journal_mode=delete, busy_timeout=10000, ...
claim race: 6 rounds of each pairing (python+python, rust+rust, python+rust, rust+python): one claim every round,
  the other refused submission_safe/possibly_sent
busy: a read under another's write lock did not wait; a claim waited for a 2 s lock and got it; behind a 13 s lock
  both gave up after the 10 s timeout with StoreError 'State transaction failed'
store seam: the policy's 11 closed lists equal to v0.6.26-beta.2's; 23 lists are car-machine's
```

The diff catches a difference: `max(0, ...)` turned to `max(1, ...)` in car-store's claim refund made ScriptDiff fail
at the first record read after a release ("op 45 (get) differs").

## Dependencies (crates.io only)

`rusqlite` 0.43 with `bundled` (D4; libsqlite3-sys 0.40, SQLite 3.54.1, above the bundled Python's 3.50.4), now a
dependency of car-store, which the harness reaches it through; and `serde_json` 1 to read requests (D5), which brings
`serde`. The JSON writer is car-machine's (S0.2).

## Platform diffs (S3.1, car-platform)

Three modules named `*_diffs`, which `run.py` loads beside `diffs.py` (a seat adds its own; nothing of another seat's
is edited). They do not use `car-harness`: car-platform has its own probe, `rust/crates/car-platform/examples/probe.rs`
(an example, never shipped; built on demand with `cargo build -p car-platform --example probe`, two jobs, or named by
`CODEX_AR_PLATFORM_PROBE`). Alone: `python -X utf8 tests/rustdiff/platform_diffs.py` (or `-m unittest
rustdiff.platform_live_diffs`, `rustdiff.platform_registry_diffs`).

| Module | Proves |
|---|---|
| `platform_diffs.py` | the mutex, stop, wake and demo names, the install lock and the home lock's files for 50 homes (Unicode, case, 8.3 names, a junction, `..`, homes that do not exist) x 3 state names; `subprocess.list2cmdline`, `startup.quote_argument` and `parse_command` over 4,000 generated argument lists; the child sees the arguments it was given |
| `platform_registry_diffs.py` | every registry writer and reader behind a stand-in in both implementations (the calls recorded, in order, the results, the store left), and the shortcut writers behind a recording starter (command line, the values' environment variables, flags, timeout, refusals) |
| `platform_live_diffs.py` | CREATE_NO_WINDOW on every process started (flags read back; no other `Command::new`); the pure rules (host walk, owner trust, access-list verdicts, SDDL descriptors, signature reasons, typeface); the read-only live questions put to both at once; a mutex, the three events and the home lock made by one implementation and met by the other |

The registry is never the machine's: the reference runs with `winreg` replaced by a recorder, the probe on an in-memory
`FakeRegistry`; the real Win32 writer is held to that stand-in on a private hive of a scratch file
(`cargo test -p car-platform --test registry_hive`, `RegLoadAppKey`). Named objects are made under a scratch
USERPROFILE, so their names are not the real watcher's. Power is never acted on (`act` refuses).

Platform seat dependencies: `windows` 0.62 (and its `windows-*` support crates), `serde_json` for the manifest's display
name. No other crate; SHA-256 is Windows' own (`BCryptHash`).

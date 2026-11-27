# tests/rustdiff: the differential harness

The Rust core port (v0.6.27, `PLAN.md` section 4) proves each piece it ports by running the same input through
the reference and through Rust and comparing the outputs byte for byte (D12). The reference is a tag's own
Python (D17: the v0.6.26 tag; until it exists, `v0.6.26-beta.2` stands in, `reference.STAND_IN`; `--reference` names the
tag a run uses), taken out of git by `tests/released.py` and run in a process of its own on scratch homes, on the bundled
Python 3.14.10 (`refpython.py`, below).

| Piece | Where | What it does |
|---|---|---|
| reference | `reference.py` | the tag's tree (`released.package`), run with every home in a scratch folder, PYTHONPATH the tag's `src` alone, no console window; answers are kept as bytes |
| Rust | `rust/crates/car-harness` (PLAN 1.2 row 17, `publish = false`) | `car-harness serve`: JSON-lines calls, the framing `controlcli serve` uses; `car-core-stub`: the stand-in for `codex-auto-resume.exe` (`bridge`/`mcp`/`cli` + the Python entry point's argv) |
| Rust, from Python | `core.py` | where the binaries are (`CODEX_AR_CORE_EXE`, `CODEX_AR_HARNESS_EXE`, `CARGO_TARGET_DIR`, else the crate's release build), `build()`, `stub()`, `Harness` |
| shim | `shim.py` | `CODEX_AR_CORE=rust`: the entry points' `main` runs the Rust binary (below) |
| diffs | `diffs.py`, `diffs_*.py` (each seat's own: `diffs_store.py`, S1.2) | the comparisons, as unittest cases; run.py loads `diffs.py` and then every `diffs_*.py` in name order. The folder has no `__init__.py` (a namespace package) and no `test*.py`, so the lanes' discovery never enters it: it imports nothing of it and runs none of it |
| ledger | `LEDGER` | tests that fail on Rust only for reading a Python internal, each with its reason; only shrinks; empty (S4.2: the 15 frozen modules need no entry) |
| scenario proxy | `engineproxy.py` | `CODEX_AR_CORE=rust`: the `Engine` the frozen modules build, as car-engine (S4.2) |
| entry point | `run.py` | the one command CI and a person run |

## The entry point

```
python -X utf8 tests/rustdiff/run.py --build
```

From the repository root, on any PYTHONPATH. `--build` runs `cargo build --release --locked --manifest-path
rust/crates/car-harness/Cargo.toml` (CARGO_BUILD_JOBS 4 unless set) and then (Integration 6, `core.build_rest`) the
standard workspace's release binaries and car-adv's `advprobe` and `advstore` examples, so no diff runs a stale binary; then
every diff. Exit 0 identical, 1 a
difference or a failure, 2 binaries missing. `--reference TAG` names another reference; the tag must be in the
checkout (CI fetches the tags; a missing one fails there, as in `tests/released.py`). The crate is a member of
the `rust/` workspace: its build goes to `rust/target` and its lock is `rust/Cargo.lock`.

## The reference's Python (`refpython.py`)

The reference runs on the runtime the product ships, not on whatever `sys.executable` is. v0.6.26 bundles the
embeddable CPython **3.14.10** (`build/make_release.py` `PYTHON_VERSION`, pinned by `PYTHON_SHA256` and
`build/runtime_keep.json`); a person may choose python.org's newer one. Python's behaviour moves between versions (json's
nesting depth, `ntpath.realpath` and a junction, Unicode tables, SQLite), and a reference on another Python hides every
such place.

```
python -X utf8 tests/rustdiff/run.py --reference-python bundled   # the default
python -X utf8 tests/rustdiff/run.py --reference-python system    # this interpreter (sys.executable), as before
python -X utf8 tests/rustdiff/run.py --reference-python D:\py\python-3.15.2-embed-amd64.zip   # a python.exe, a folder, or an embeddable zip
CODEX_AR_REFERENCE_PYTHON=system python -X utf8 tests/rustdiff/rediff_codex.py --reference v0.6.26
```

`run.py` prints which one it used: `reference v0.6.26-beta.2 on python 3.14.10 (bundled: embeddable); rust ...`. The
variable is what `rediff_*.py` hand on to the `run.py` they start, and a child finds the already unpacked runtime
(`CODEX_AR_REFERENCE_PYTHON_EXE`), so one run unpacks it once.

How it runs: the zip is unpacked into a scratch folder of the run (removed when it ends; nothing goes into the
repository), and `reference.run` starts its `python.exe` with `-X utf8 -c`. An embeddable runtime ignores PYTHONPATH and the
working folder (its `python314._pth` makes it isolated), so the tag's `src` reaches it through `sys.path`, set by a
three-line boot in front of the script (`refpython.boot`; the script runs in `__main__` as `-c` would, `sys.argv` the same);
nothing of the person's environment is used. The runtime is stdlib only; `refpython.check` imports what the tag's code
imports and names a module the runtime lacks. `reference.command(script, *arguments, paths=[...])` is the argv for a caller
that starts the reference itself.

Where the zip comes from (never a fetch of this harness's own): `CODEX_AR_RUNTIME_ZIP`, else this checkout's `build/cache/`,
else the `build/cache/` of another worktree of the repository (the cache is not tracked); its sha256 is checked against
`make_release.PYTHON_SHA256` every time. **On CI** a zip found nowhere is fetched by `make_release.fetch_runtime()` itself
(`python build/make_release.py` downloads and checks it into `build/cache/` the same way; an `actions/cache` step on
`build/cache` could keep it between runs); off CI a missing zip is an error that says where it looked, and `run.py` exits 2.

The twin check (`reftwin.py`): a diff stops at its first mismatch, and a mismatch between Rust and one Python says
nothing of the other. With `CODEX_AR_REFERENCE_TWIN=system` (or a path) and `CODEX_AR_REFERENCE_TWIN_LOG=<folder>`, every
`reference.run` also runs its script on the twin Python, with the profile folder put back as it was, and compares exit code,
stdout, stderr and the profile's files; each call that differs is appended to `<folder>/calls.jsonl` with both answers as
files. The run's own verdict is the chosen Python's alone. For readers only (a store that writes where it reads sees the first
run's files outside the profile).

Routed (follow 3.14, D): every start of the reference's Python goes through `reference.command(script, ...)` or
`reference.script_command(path, ...)` (a script file: the generators, a script too long for a command line), so
`--reference-python` reaches it: the advanced reference (`advref.run` / `popen`, hence the advanced diffs and `advstore.py`'s
claim race), `diffs_store.reference_process`, the engine's and the command line's reference (`diffs_engine`, `cliworld`), and
`gen_cli.py`, `gen_vocab.py`, `gen_logbook.py`. The Unicode generators (`gen_tables`, `gen_codex`, `gen_policy`,
`gen_advcodex`) run themselves under the bundled runtime through `productpy.py` - which now unpacks nothing of its own, it asks
`refpython` for `bundled` - whatever `--reference-python` says: a table of Python's Unicode is the product's Python's, not the
reference's choice. What differs between 3.13 and 3.14: `outputs/plans/v0627-rust/REFERENCE-314.md`; the nesting limits are
`diffs_nesting_314.py`'s, the drive-like realpath tail `diffs_paths_314.py`'s (both differ BY DESIGN under `system`, and
`rediff_follow314.py --reference v0.6.26` reruns them with the generators' `--check`).

Integration 10 routed the P7 seats' families the same way (`advaccount`, `advusage`, `advturns`, `advtime`, `advcourier`,
`advplug`, `advreport`, `advhook`, `advcodex`, all through `advref.run` / `refpython.command`) and the advanced proxy's two
lanes (`advproxy/ledger.py --run`: scripts/test_parts.py's worker through `refpython.script_command`); `run.py --build` now
builds `advserve`, `advcourier`, `advaccount`, `advusage`, `advturns` and `advtime` with the other examples.

**No reference run reaches this PC's Codex** (`refguard.py`, Integration 10, after two seats' reference runs started the
installed codex.exe on 2026-11-27). Every process `refpython.command` / `script_command` starts - on any runtime, so
`reference.run`, `advref.run` and `popen` too - and tests/released.py's `run` runs refguard's program before the script:
core's process lookups (`win.kernel.processes_named`, `process_identity`, `win.inventory.resource_users`, and every module's
own binding of them, pairing's engine lookups among them) and the advanced `codex.inuse.backend` refuse with the tag's
`AdapterError`, and `CODEX_AUTO_RESUME_CODEX_EXE` points where no codex.exe is (`reference.scratch_environment` sets it over
whatever the runner inherited, for both sides of a diff; a test hands its own path, or `None` for discovery on its scratch
homes). A stand-in a script sets still wins. The one file whose subject is this PC's live process table
(`platform_live_diffs.py`) lifts the lookups by name (`CODEX_AR_REFGUARD=live-processes`); the advanced proxy's lanes are
test lanes with tests/no_real_codex.py, not references (`guard=False`). `tests/test_rustdiff_refguard.py` holds all of it.

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

S4.2: `codex_auto_resume.engine`'s `Engine` becomes `engineproxy.py`'s - car-engine in a session of one `car-harness
serve` per test process, its store, source and backend the test's own objects asked back over the pipe
(rust/GROUNDWORK.md, "The scenario proxy"). The `Store` and `LocalSource` stay Python's: their proxies are not needed,
because what the frozen modules hold is what the engine decides. Not here yet: a `serve` that streams
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

## The classifier and its policy (S2.1, car-policy `src/classify/`)

Four modules, `diffs_classify_*.py`, loaded by `run.py` with the rest (alone: `run.py --build -k diffs_classify`). They go
through `car-harness serve`'s `leaves.batch` (the harness's `src/classify.rs` answers every `failures.*`, `reasons.*`,
`gates.*`, `guards.*`, `ladder.*`, `quiet.*`, `projects.*`, `needsyou.*`, `power.*`, `permits.*`, `continuation.*`,
`public.self_check` and `own.*` case with car-policy's own function) and each family script runs in the reference tag.

| Module | Proves |
|---|---|
| `diffs_classify_failures.py` | **the done-check**: every structured error the tag's own tests, codexsim and fixtures carry (read out of `git show TAG:tests/...`: every `error_json` row, every `codexErrorInfo`/`error` object, every literal handed to `classify`/`shape`/`transient_error`, every `code=`), read as `codex/values.normalize` reads a turn row, gets the same category, the same reason (`reasons.get`) and the same public code (`shape`, `unknown_code`, `takes`/`admits`/`readmits`); then generated errors in every form Codex writes one, and `self_check` |
| `diffs_classify_policy.py` | the gates (moved from car-store's seam), guards, ladder, needs-you, power, projects, permits, quiet hours on six test zones (`ZONE`: an offset and summer time; car-harness's `Zone` is the same rules), and `ownvalues` (S2.2's, which the classifier reads: `own.*`) |
| `diffs_classify_continuation.py` | **the done-check**: `build()` in every one of the 22 languages for every category, style, Custom choice and metadata; the same text through `for_settings`/`source_for`/`with_once_words`; the checks of a person's words |
| `diffs_classify_vocab.py` | the eleven modules' words equal to the tag's `vocab.json`; `str.lower()`, `str.casefold()` and `\w` of every code point equal to the reference interpreter's; the generated files current |

Run 2026-11-25 (`run.py --build -v -k diffs_classify -k SeamVocabularyDiff`, reference v0.6.26-beta.2), all OK:

```
classify corpus: 106 errors from v0.6.26-beta.2's tests (586 files) and fixtures (86 files) - 14 error_json rows, 92 structured
  infos - 2968 cases equal; categories {network_transient 2, rate_limit_transient 1, server_5xx 6, stream_interrupted 2,
  terminal_auth 6, terminal_invalid 7, unknown 80, usage_limit 2}
classify generated: 694880 cases equal          self_check: 1029 cases equal
gates: 41367 cases equal                         policy: 59817 cases equal        quiet: 24243 cases equal
continuation text: 103503 builds equal - 23 languages (22 and one it lacks) x 15 categories x 6 styles x 10 Custom x 5 metadata
continuation settings: 40084 cases equal         continuation checks: 1630 cases (286 product texts) equal
classify vocab: 11 modules, 72 constants          text tables: \w of 1,112,064 code points, 1433 lower(), 1530 casefold()
store seam: gone but python.rs; the policy's closed lists car-policy's, equal to the tag's
```

**Re-diff at the final.** S2.1 was ported from v0.6.26-beta.2 while `failures.py` and others still moved on dev (PLAN 5.1).
One command checks the port against a tag: `python -X utf8 tests/rustdiff/rediff_classify.py --reference v0.6.26`. It prints
which ported Python files changed since beta.2, runs `gen_policy.py --check --ref TAG` (the generated vocabulary and tables) and
`run.py --build --reference TAG -k diffs_classify -k SeamVocabularyDiff`, and exits 0 only when all are clean.

The gates take a stored record and the clock as the store has them (numbers, words, `None`; `now` an f64), the types the
store validates on every write; the other modules take any value, as the Python does, and answer its exception's class.

## Settings and the plug (S2.2, car-policy `settings/` and `plug/`)

Six modules named `diffs_settings_*.py`, over one helper, `settingsdiff.py` (a family of cases made in the tag and
answered by both, like `leaves.py`; not loaded by `run.py` on its own). They go to `car-harness serve` as `policy.batch`
calls (`car-harness/src/policy.rs`), which read the request line as Python's `json.loads` reads it - a NaN, an int of any
size and half of a surrogate pair reach the settings exactly as in Python, because settings files hold all three - and a
reply holding half a pair is written with its escape.

| Module | Holds equal to the tag |
|---|---|
| `diffs_settings_values.py` | `coerce`, `validate_update` (accept, refuse, the sentence), `_migrate` over every field's choices, own spellings, bounds and wrong types, and random mixtures with unknown and reserved keys; `defaults()`, `describe()`, `RANGES`, `field_type`, the readers of a settings dict and the bytes `save` writes; ownvalues; the homes' checks; the kinds of notice, registrations included; the memory guard |
| `diffs_settings_files.py` | `read`/`load`/`save`/`update` and config.py's three settings functions on files: what 14 tags wrote, BOM, UTF-16, Latin-1, no JSON, 4 MiB and one byte more, nested past the reader, a folder in the file's place, a file held with no sharing, a read-only file - the answer, the bytes left and every other name in the folder; the status file's writer and remover; `homes.problem`/`strict` and the edition's look over a tree with a junction |
| `diffs_settings_policy.py` | the policy keys: `managed.parse`/`clamp`/`admit`/`quiet_sources` over generated places, and end to end through a registry stand-in (the reference's `policykeys.read()` on `platform_registry_diffs.FAKE`, Rust's `read_policies` on `FakeRegistry`; HKCU is never opened); the power action's rules; the status file's content; the demo; `public.self_check` |
| `diffs_settings_plug.py` | PLUG_API and every table of `domain/plug.py`; what NULL answers at all 21 hooks and what `Guarded(NULL)` gives core; `consult`'s closed set at each decision point for every word and for a hook that raises; `records_of`, `workers`, `fields`, `kinds_of`, `widening_of`, `Guarded.power`; the vocabularies of the 12 modules; car-policy's generated files |

Alone: `python -X utf8 tests/rustdiff/run.py --build -k Settings -k OwnValues -k HomesKinds -k StatusTree -k Managed -k PowerStatus -k Plug`.

**The final re-diff, one command:** when v0.6.26 is tagged, `python -X utf8 tests/rustdiff/gen_policy.py --check --ref v0.6.26 && python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 -k Settings -k OwnValues -k HomesKinds -k StatusTree -k Managed -k PowerStatus -k Plug`
(`gen_policy.py` regenerates the vocabularies and Python's casefold and isalnum tables and says which file is stale; the
diffs then say which answer moved). dev changed none of the seat's modules after v0.6.26-beta.2 when it was ported.

The run of 2026-11-25 (all diffs, `run.py --build`, rc=0): 48,130 coerce/validate/migrate cases (26,012 accepted, 22,118
refused alike), 1,186 schema and reader cases, 4,102 own-value cases, 923 homes/kinds/memory cases, 367 file cases (28
files from 14 tags; 94 answered by an exception with the same class, sentence and reason), 94 status/homes/edition
cases on disk, 8,439 policy-key cases and 10 registry scenarios, 5,457 power-action, 621 status-content, 14 demo and 92
self-check cases, and the plug's tables, NULL, 133 consult, 1,505 records_of and 65 other checks.

The diffs catch a broken rule (each broken alone, rebuilt, its diff run, restored; every one failed, and all passed again
after): `max_recovery_attempts` up to 21 (coerce, case 574); a REG_QWORD switch ignored (managed, case 15); NULL wanting
every point (plug, case 1); the status file with LF line ends (tree, case 0); `handed_over_too` met with no recovery
(power, case 4...); a settings file of exactly 4 MiB refused as too large (files, case 312).

## S2.1 and S2.2 together (car-policy, Integration 3)

The two seats met in `car-policy`: `classify/` (S2.1) and `settings/` and `plug/` (S2.2). Each had kept a copy of what the
other owns, and both are gone: S2.1's `classify/seam.rs` (`ownvalues`'s `Own`, `amount`, `canonical`, `coerce`, `spell`, and the
plug's `TAKE_UP`, `PACED_AS`, `Alternative`, `FailureForm`) and S2.2's `settings/seam.rs` (`continuation`, `ladder`, `quiet`,
`guards`, `power`, `needsyou`, `projects`, `failures`, `reasons`: the choice lists, the defaults, the coercers). Each module now
reads the other seat's own. Nothing in a diff was edited: `own.*` and `SeamParity` hold S2.2's `ownvalues` and plug words, and the
settings diffs hold the classifier's lists and coercers through `settings.coerce`, `describe()` and the validators.

`homefind.coerce_dismissed`, which neither seat's list named, is ported as the reference has it (`settings/homefind.rs`, with
`SWITCH`, `DISMISSED` and `DISMISSED_MAX`) and has a diff of its own: `diffs_settings_homefind.py` (1,596 cases: 0 to 18
folders, a relative path, a share, a lone surrogate, two spellings of one folder, non-text entries). The rest of `homefind.py`
(looking for homes, `dismissed_with`) is the watcher's.

`gen_policy.py` is one script for both seats (the first two of its five files are S2.1's, the last three S2.2's): `--check`
says whether any of the five differs from what the tag gives. The two re-diffs at the v0.6.26 final:

```
python -X utf8 tests/rustdiff/rediff_classify.py --reference v0.6.26
python -X utf8 tests/rustdiff/gen_policy.py --check --ref v0.6.26 && python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 -k Settings -k OwnValues -k HomesKinds -k StatusTree -k Managed -k PowerStatus -k Plug -k Homefind
```

The whole harness: 97 diffs (harness 4, S1.1 27, S1.2 15, S2.1 13 + the store's seam check, S2.2 11, S3.1 27).

## Codex's readers (S3.2, car-codex)

Four modules, `diffs_codex_*.py` (and `codexdiff.py`, `codexbattery.py`: what they share, not loaded by `run.py` on their
own), alone: `python -X utf8 tests/rustdiff/run.py --build -k diffs_codex`. car-codex's readers never write, so one Codex
home on disk is read by both implementations, where it is - the same path for both - and no path needs to be made
canonical. A case is a home and a list of calls named as the reference's `LocalSource` methods; the reference runs them in a
process of its own (`codexdiff.SCRIPT`, the tag's own package) and `car-harness serve` answers the same list as one
`codex.script` call (`car-harness/src/codex.rs`). The module state of the reference (the split listing, the first lines,
the triggers) is cleared before each case, as a fresh process starts; a case with a chain-memory file is run on the file
for the reference and on a copy for Rust, and the two files are then the same bytes.

| Module | Proves |
|---|---|
| `diffs_codex_homes.py` | **the done-check**: every codexsim home (`tests/codexsim.py`'s `CodexHome` in every shape its builders make: usage limits with and without a reset, transient failures of every code, in-progress and interrupted turns, queues with our marker, a foreign item, an edited item, a client id, dispatches with a steer, a first user item unset, stale and missing projections), the odd ones the audits hold (splits: one, two, one with the first file gone and a chain memory, one with a remembered chain, every guard failing, in subfolders, the same name twice; every kind of conversation: 490 combinations of a row's source, thread_source and the first line's originator; rollout files of 41 first-line kinds plus the size boundaries - BOM, no newline, CRLF, empty, Latin-1, not UTF-8, truncated, one byte over and under the 256 KiB limit, 400 KB, 3,000 and 20,000 brackets deep, a NaN, a repeated key, a lone surrogate; 19 forms of `rollout_path`, a BLOB where text belongs; 45 rollout bodies for the reset hint, Rescan's evidence and `turn_trigger`; the databases' files and generations, the schema with each required column gone, extra columns, the column types the guards read, the labels' columns; 240 random rows of the wrong type; the cloud-task file in 24 forms; git HEADs in 27 forms; the chain memory's file in 30 forms) asked every question the product asks of Codex (`codexbattery.battery`) |
| `diffs_codex_pure.py` | each reader function over its own inputs, through `leaves.batch`: turn rows (`detect`, `normalize`, `judge`, `admissible`, `error_shape`: the usage-limit fixture and 6,000 generated rows), rate-limit snapshots (`_choose_reset`, `parse_usage`: 4,000 each), the words (`_label` with the `isprintable` of every one of the 1,114,112 code points, `taken_thread_source`, `_turn_status`, `epoch`, `_json`), `eligibility.*`, `_item_is_ours`, `_queue_has_marker`, `marker_row`, `later_turn`, `placed`, `taken`, `continued_id`, and the file readers on 44 files and folders |

`gen_codex.py` makes `printable_gen.rs` (the code points `str.isprintable()` is true of, from the Python the product ships:
3.14.10, Unicode 16.0.0, `productpy.py`); `--check` says whether it is stale or made by another Python. Every Unicode table
(`gen_tables.py`, `gen_codex.py`, `gen_policy.py`) is made and checked that way, and `diffs_unicode16.py` holds all of them to
that interpreter code point by code point, whichever Python runs the reference.

**The final re-diff, one command:** `python -X utf8 tests/rustdiff/rediff_codex.py --reference v0.6.26`. dev changed none of
the ported modules after v0.6.26-beta.2 when S3.2 was ported (`git log v0.6.26-beta.2..origin/dev -- <file>` was empty for each of
`codex/{__init__,errors,paths,schema,history,values,labels,payload,rollout,chains,eligibility,workspace,usage}.py`); the command
prints which of them (and of the domain, guards, projects, homes and failures modules they read) changed to the tag, checks
the generated table, and runs every `diffs_codex_*` diff with the tag as the reference.

What stays out of S3.2 (S3.3's, from the final tag): `codex/{appserver,transport,pairing,layout}.py`, `compat/*`, `compatio.py`.
`windows.py` is a re-export front and has no Rust module. A BLOB (`bytes`) in a Codex column is carried as an empty list:
the diffs write the reference's `bytes` as `[]`, and the one place where a list and `bytes` differ (`skips.kind` of a source) is
read from the cell itself (`sql::Cell::kind`).

Run 2026-11-25 (`rediff_codex.py`, the release build, reference v0.6.26-beta.2, rustc 1.100.0, SQLite 3.54.1 bundled; 28 tests, 1,040 s, all OK):

```
homes: 268 homes and chain-memory files, 101,440 calls equal - codexsim basic 1, codexsim queue/dispatch 6, projection 5,
  splits 12, eligibility matrix 1 (490 conversations) and first lines 1 (25 kinds), rollout first lines 1 (41 variants and the 256 KiB boundary),
  rollout paths 1 (19 forms and the BLOBs), reset hints 42, superseded and trigger 31 (+ 6 widened), schemas 62, database
  files 32, odd rows 6 (+ 1 asked everything), items and markers 1, stalled and activity 1, cloud tasks 24, sessions
  folder 3, workspace 1 (+ 196 facts), chain memory 30 files
pure: 76,766 cases equal - turn rows 42,022 (+ the usage-limit fixture's detect, normalize and reset hint), reset and usage
  8,000, eligibility functions 9,455, our messages 9,414, labels and words 3,497 (isprintable of all 1,114,112 code points),
  file readers 3,095 (44 files and folders, every end offset, limit and turn), placed/taken/continued 1,231,
  workspace digests 49
every answer by an exception has the same class (an OSError of any kind is OSError; a SourceError has the same sentence)
```

The diffs catch a broken rule (each broken alone, the harness rebuilt, its diff run, the rule restored; every one failed):
`agentMessage` gone from the progress kinds (codexsim queue: `turn_progress`), a label cut at 71 (labels), `SPAN` 2^41 (splits),
a window exhausted past 100 instead of at 100 (usage), a first line allowed one byte more (rollout first lines: the line of
`256 KiB + 1` bytes), `codex_work_desktop` no desktop originator (eligibility matrix), a rollback after the anchor no doubt
(superseded and trigger).

## The app server's half and the registry (S3.3, car-codex)

Six modules, `diffs_codex_appserver_{pairing,lines,transport}.py` and `diffs_codex_compat_{registry,io}.py` (with
`appserverdiff.py` and `compatdata.py`, what they share, not loaded on their own), alone:
`python -X utf8 tests/rustdiff/run.py --build -k diffs_codex_appserver -k diffs_codex_compat`. A case is a stand-in
world - the process list, who holds which file, live processes' identities, files' signers, LOCALAPPDATA /
ProgramW6432 / ProgramFiles / USERPROFILE, this process's pid, the clock, the Restart Manager - and a list of operations
named as the reference script names them; car-harness answers them as one `codexapp.script` call (`src/appserver.rs`,
`src/registry.rs`). The reference has `processes_named`, `resource_users`, `process_identity`, `authenticode.signer`,
`os.getpid`, `windows.restart_manager_available` and the pairing's clock replaced by the same world, so neither side
reads this machine's processes, holders or signatures. Files are real, in the scratch folder; a file an operation
writes is put back before the Rust side runs, and both must leave the same bytes.

Processes are started only by the transport, the helper and discovery, and only `car-fake-codex` (a bin of
car-harness, never shipped) copied into a case's scratch `OpenAI\Codex\bin\<hex>\`, always with no window. It answers
from `fake.json` beside it and keeps what it was asked: every argument list, its working folder, `CODEX_HOME`,
`OTEL_SDK_DISABLED`, and every byte written to the helper (`stdin.bin`), which must be equal for both sides - the
JSON-RPC requests byte for byte, CRLF included. A child started with no working folder inherits its parent's, which
differs by side; that one folder is named the same for both.

**The final re-diff, one command:** `python -X utf8 tests/rustdiff/rediff_appserver.py --reference v0.6.26`. It lists
which of the ported files and the modules they read changed between v0.6.26-beta.2 and the tag, then runs these six
modules with the tag as the reference. `rediff_codex.py` (S3.2) runs them too (`-k diffs_codex`).

## The advanced edition (S7.1a, S7.1b, Integration 5; car-adv)

Two seats' diffs, run through one reference. `advref.py` takes a tag's core **and** advanced trees out of git once (`package`,
`trees`, `locales`), runs a script under them with every home in a scratch folder (`run`, `popen`), and builds and asks car-adv's
`advprobe` example (`ask`); `diffs_advstore.py` (S7.1a, the store: its own `advstore` example) and `diffs_advpolicy_*.py`
(S7.1b: vocabulary, standards, measured, policy, registry, statement and `Arming`, through `advprobe`) both use it
(`advreference.py` was S7.1a's copy of the same). `gen_advstore.py --check` holds `state/schema_gen.rs` to the tag and
`gen_advpolicy.py --check` the vocabulary and registry tables the store now reads (`GeneratedDiff` runs both).

`ArmingScenarioDiff.test_over_the_real_state` is the diff that holds `Arming` to the tag over the **real** state: the scenarios
of the stand-in diff, run by the tag's `Arming` over the tag's `AdvancedState` and by car-adv's `Arming` over car-adv's, each on a
home of its own (`<home>/py`, `<home>/rs`, begun empty), every step's answer, the edges' calls and the state left - as the
state's own readers say it - equal (`CODEX_AR_ARMING_REAL` sets how many scenarios; 240 by default).

## The second review's fixes (seat fix5, REVIEW-int5)

**Floats the channel cannot carry.** A NaN or an infinity crosses as `{"$float": "nan" | "inf" | "-inf"}`, both ways:
`diffs.TAGGING` (`tagged`) is in `leaves.PRELUDE`'s `finish`, `codexdiff.SCRIPT`'s answers, `diffs.encode` and the store
diffs' requests; car-harness untags a `leaves.batch` or `codex.script` request and the store calls' line before anything
runs and tags the leaves and codex answers. Every finite value is written as before. `policy.batch` (settingsdiff.py) keeps
its own loose reading of NaN. A dict whose only key is `$float` is the tag's. A BLOB in a store answer is written as
car-store carries it, `{"\u0000bytes": hex}`.

| Module | Proves |
|---|---|
| `diffs_leaves_floats.py` | the float's text, character for character: car-machine's JSON writer, `pytext::float_repr` and car-brand's `pyfmt::repr` against `json.dumps` and `repr` over 258,728 floats sent as their bits (every power of two and its neighbours, the subnormals, every decimal exponent's boundary, the non-finite, random) |
| `diffs_store_values.py` | car-store on values no store writes: BLOB columns read by `watcher_status` and a legacy store (`bool(bytes)`, written back as a BLOB), sign-ins with a newline, no settings row, claims with non-finite caps |
| `diffs_classify_clock.py` | the product's clock (car-platform `localclock::Crt`, the zone `"local"`) against the interpreter's own `time` under six `TZ` zones with summer time, half hours and UTC (161,874 cases); `diffs_classify_policy.py` holds it in this PC's zone at every edge |

The re-enabled cases (`diffs_classify_policy.py`'s four `if False`), and NaN and the infinities added to the words, domain
and brand families, are equal to v0.6.26-beta.2. The re-diff at the final: `python -X utf8 tests/rustdiff/rediff_review5.py
--reference v0.6.26`.

## The engine (S4.1, car-engine and car-scheduler)

`diffs_engine.py` (alone: `python -X utf8 tests/rustdiff/run.py --build -k EngineTraceDiff`), over `enginerun.py`, which is
run in two interpreters and so imports nothing of the product or of this checkout's tests. A scenario is a list of steps -
the clock, codexsim's own calls on the Codex home (`home`), test_engine's helpers (`helper`: fail_turn, dispatch_and_fail,
archive, raw_turn, edit_head, duplicate_head, ...), the stand-in backend's moods (`backend`), a person's store calls
(`store`, `{"$key": thread}` naming that conversation's newest record), `policy`, `tick`, `watch`, `after_sleep`, `facts`.
It runs once in the reference tag's Python (its Engine, Store and LocalSource; `SCRIPT`, TZ=UTC0) and once through
`car-harness serve`'s engine session (`engine.open` / `engine.step` / `engine.close`, `car-harness/src/engine.rs`), whose
backend calls and jitter's draw come back as `{"ask": name, "args": [...]}` lines answered by this side's
`codexsim.SimBackend` and a `random.Random` of the same seed. The launch guard of a send is entered on each side's own store
before its stand-in is told. Both worlds are built by the tag's own `tests/codexsim.py`, with `new_id` a counter, so every
id is the same; a continuation's language is named (`CODEX_AUTO_RESUME_LANG`, `en` unless a scenario says), so neither
side reads this PC's Windows languages.

After every step the two traces must be equal: the step's answer (or the class it raised), the engine's log lines and
notifications, every backend call with its arguments (the words sent among them), and the whole `state.sqlite` - every
table, every row in rowid order, each value with its type, floats by `repr` - and the other files the store keeps.

The corpus is the frozen scenario modules' flows (test_engine 01-18, the crash and uncertainty tests, T01-T47,
test_outcomes, test_pause_unknown, test_ladder_and_guards, test_skip_reasons, ...) written as step lists, never the modules
themselves; then `generated(seed)`'s random walks (CODEX_AR_ENGINE_WALKS, 60 by default, 60 steps each, one to three
conversations). The final's re-diff: `python -X utf8 tests/rustdiff/rediff_engine.py --reference v0.6.26`.

Run 2026-11-25 (`run.py --build --reference v0.6.26-beta.2 -k EngineTraceDiff -v`, 926 s, OK): corpus 81 scenarios, 1,023
steps equal (63 sends); random walks 60 scenarios, 5,153 steps equal (122 sends). Eight broken rules each failed a trace
(rust/GROUNDWORK.md, "The engine").

### 4. car-control's quiet bridge (S5.1a, `diffs_bridge.py`, `diffs_bridge_commands.py`, `bridgeworld.py`)

`car-harness serve` answers `bridge.run` {home, world, mode, input (hex), argv}: car-control's `serve` over request lines, or its
one-shot form, on a scratch home, for a **world** - the answers of the machine the commands ask for (the clock, the
watcher's mutex, the Run value, an administrator's keys, the install lock, the Codex home, the languages, who may open the state
folder, where the watcher runs, the compatibility view, the Codex homes of an installed copy). `bridgeworld.SCRIPT` patches the
same world into the tag's own modules and runs its `controlcli.serve` (or `main`); each side runs on a fresh copy of one template
at **one and the same path** (a home's key is a hash of its path), and the reply bytes, the exit code and every small file the
commands wrote (settings.json, failure-seen.json, once-words.json, a set-aside copy) must be equal. The harness is started with
the reference's scratch environment (every home variable in a scratch profile), as the reference is: the real mutex is named
from the user's home folder.

The installation is the wire goldens' own (`make_screenshots.pinned_installation`), an empty home, or none at all; the damaged
and the huge ones are made from it (`tune`).

| Diff | What |
|---|---|
| `FramingDiff` | the goldens' framing cases; 60 request streams: no final newline, two requests in one write, CRLF, a lone CR, padding by spaces / no-break space / `\x1c`-`\x1f`, a byte order mark (start, twice, mid-stream), ids of 30 and 5,000 digits, NaN, Infinity, `1e999`, an object, a lone and a paired surrogate, commands that are not text, arguments of every wrong type, JSON text with NaN and surrogates, duplicate and trailing-comma keys, nesting of 1,000 and 100,000, lines of exactly and one past 1 MiB (padded too), invalid UTF-8 first / after a good line / cut at the end / past an 8 KiB chunk, 400 requests |
| `GoldenCasesDiff` | all 122 cases `wiregolden.BRIDGE_CASES` asks of the 23 quiet commands, in order, the watcher running and not |
| `WorldDiff` | the watcher (3 states x 3 Run values; 4 Run values that belong to the home), 7 sets of the administrator's keys over status/settings/describe/update/defaults, the install lock (3) x superseded (2), 11 language and environment worlds, host-app and access (36), the compatibility view over configured Codex homes (6), the installed copy's home suggestion with the registry and the Codex app's list |
| `DamagedDiff` | no home / no state (6), a state that is garbage, empty, a header only, schemas 0, 4, 6 and 99, v0.6.10 and v0.6.13 states under and without the install lock, 17 settings files (garbage, empty, a list, a folder, nested, 5 MB, NaN, a lone surrogate, wrong types, older/newer `config_version`, not UTF-8, a BOM), 14 failure-seen files, 9 logs x 17 queries (Unicode digits, casefold, 2 MB, rotated copies, not UTF-8), 20 once-words files, a state of 1,500 records |
| `WriterDiff` | `update` in 33 shapes, `check-setting` (20), `conversation-message` (66, past the 50 limit), `preview-continuation` in every kind of change in 8 languages |
| `EdgesDiff` | `statistics` days (20), `timeline` ids (24), the lists with the watcher in each state, the one-shot form (24 argument and stdin shapes) |

`python -X utf8 tests/rustdiff/rediff_control.py --reference v0.6.26` lists any ported file that changed after v0.6.26-beta.2 and
reruns every `diffs_bridge*` diff against the tag.

## The plug's answer paths (review 6, S3: `diffs_engine_plug.py`)

`python -X utf8 tests/rustdiff/run.py --build -k EnginePlugDiff` (alone). A scenario with a `plug` key - a script, `enginerun.Script`:
the points the plug wants and, per hook, rules (`when` facts of the record, `answer`, `skip`, `times`) - runs on both sides with
the same script. The reference's Engine is handed a `domain.plug.Plug` whose hooks ask the script; car-engine's plug is
car-harness's `plugscript.rs`, a test double of car-policy's `Plug` trait that asks the very same Python object back over the pipe
(`plug.<hook>`), so both engines get the same answer to the same question. Every question the engine puts to the plug (the hook,
what it was handed, the answer), every claim's `carried`/`relaxed`/`resend`/`forced`/`caps` (what P11's ledger would pay for) and
how many hooks failed (`facts`' `plug_failures`) are part of the trace, in order, with the log, the notifications, the backend's
calls and the state. A `plug` step changes the script mid-scenario. An answer is a word, a text, a list, `null` (DEFER), `raise` or
`panic`. Three tests: `scripted_paths` (hand-written scenarios for P3 holds at every gate, P4, P5/P15 asked, P6, P7's EARLY, SEND_NOW
and RESEND, P14, P16's QUEUE_FOR_OPEN and TO_SESSION, P17's ADMIT, CAPACITY and AS_* with P3's known_failure, P18 and P19, a hook that
raises or panics); `corpus_with_a_deferring_plug` (the 81 corpus scenarios again, each with a plug that wants every point and
defers: the engine's questions at every call site, compared as asked); `random_walks_with_a_plug` (the engine walks with a script
drawn from the seed, CODEX_AR_PLUG_WALKS). `CODEX_AR_PLUG_ONLY=name,name` runs the scenarios whose name starts with one. Not
held here, because they need the advanced plug (S7.2): P2's records, P5's channel, P8's and P22's errands, P11's ledger itself (a
hold or a failure at the claim), P12's pool, P16's route, P9, P13, P20 and P21 (runtime's, not the engine's).

## The scenario proxy (S4.2)

```
python scripts/test_parts.py --worker tests --report py.json <the 15 modules of tests/neutral.py MODULES>
CODEX_AR_CORE=rust python scripts/test_parts.py --worker tests --report rs.json <the same>
python scripts/test_parts.py --compare py.json rs.json
```

(`PYTHONPATH="src;tests"`, the harness built first.) Run 2026-11-25: 456 test ids, all pass on both, 0 differ. Three
broken engine rules (the day's cap, the settle, the queue launch retries) each turned two frozen tests red on the Rust
lane (rust/GROUNDWORK.md, "The scenario proxy").

## car-surface (seat S6.0)

`surface.py` is the family base (`Surface.family`, the call `surface.batch`) and `SURFACE` the stand-ins both sides use:
PowerShell and explorer.exe recorders (nothing started), the presence answers and the card host's wakes from the case,
Windows' languages `["en-US"]`, this PC's clock (`Crt`), and the renderer's `measure`. The answers are compared as the
JSON each side wrote (both already carry the float tag). S6.0 was ported from the v0.6.26 final, so where `reference.TAG`
is the beta.2 stand-in these diffs read v0.6.26 (`surface_tag`); `CAR_SURFACE_DUMP=<file>` writes a differing case whole.

| Module | Proves |
|---|---|
| `diffs_surface_uris.py` | `urlsplit`/`parse_qs` as the readers use them, `notice_uris`' readers and writers, the Codex and chat links and `open_in_codex`, `card_allowed`, `Inbox` |
| `diffs_surface_notify.py` | every toast's content and sentence in 22 languages, `_toast_xml`, and what `show` hands PowerShell (`-Command`, the variables, the flags) |
| `diffs_surface_notifier.py` | `build` for every notice kind, the demo, Open Codex, clicks, `deliver`, `complete`, `show_demo`, `told`, `activate` |
| `diffs_surface_card.py` | `view`, `layout` (scales, right to left, special days), `CardMotion`, the stack, the floating shadow, the corner, `premultiply` |
| `diffs_surface_popup.py` | ui/popup/model.py (the final's) and its words, `PopupModel`, `perform`, ui/tray/model.py and stored.py |

The re-diff: `python -X utf8 tests/rustdiff/rediff_surface.py --reference v0.6.26`.

## car-watcher (seat S6.1)

`car-harness serve` answers three calls of `rust/crates/car-harness/src/watcher.rs` (and its `watcher/` modules): `watcher.loop`
{home, script} (the watch loop over a scripted world), `watcher.launcher` {here, argv, env, script} (the launcher's logic over a
scripted world, the plug's answers checked by car-policy's own `Guarded`) and `watcher.batch` {cases} (the smaller pieces, case by
case). Every world answers from the case: no named object of the product's, no timer, no window, no Codex, no process started; the
store, the status file, the self-check file, launcher.log and errors.log are the real writers' files in the case's scratch folders.
The reference is the v0.6.26 final (`--reference v0.6.26`).

| Module | Proves |
|---|---|
| `diffs_watcher_loop.py` | the watch loop (runtime/loop.py) of the tag's own `App` and car-watcher's `watchloop::run` over 30 scenarios: each exit code (0 stop and once, 1 a refused mutex, a refused stop event and once with no engine, 3 the double look and a busy Codex home, 4 a newer state at the open and mid-tick, 5 the memory guard), a status probe lost to once, an abandoned mutex, no wake event, the open's backoff and a stop during it, failing ticks and builds (Unreadable, OSError, StoreError), Retry now's wake and its coalescing, the one-second watch, the memory guard's warning, the status file, the usage reading kept once, the self-check's detection rules, an unknown error code, the recovery facts' look, the poll interval. Equal: the exit code, every log line, every call of the world with its arguments, and the heartbeat row, status.json and selfcheck.json byte for byte |
| `diffs_watcher_launcher.py` | the tag's `scripts/watcher_launcher.py` (`git show`) and car-watcher's `launcher` over 31 scenarios: the plugin root's three-way order, runtime.json missing or damaged, the relaunch mark, AFTER_STOP (let go, still running, not known, no probe), P13's SUPERVISE and RESTART (ended, restarted, the newer state's 4, no program, a child that cannot start), a supervisor held and taken up after, answers that are not the point's, the relaunch once, the memory guard's 5, a long launcher.log. Equal: the code, every question to the plug with its facts, every child, relaunch, sleep and watcher run, and launcher.log, both errors.log and unsupervised.txt (time stamps aside) |
| `diffs_watcher_pieces.py` | `setaside.sweep` over 13 fixture homes made twice (names, `.sweep` twins, the journal, an installation running or not known, a home not ours, a running program, no program list, a read-only file, a junction) with what is left afterwards; the plug's notices over four sequences (DEFER, the meter, the update check, the account and the switch, a key seen again, past 64); the power action's looks over 13 step sequences (the file missing, invalid, unreadable, a countdown to the end, refused, input, a gap, presence, Codex busy, not available, the tasks, an administrator's key, a pause, a stop mid-countdown) |
| `diffs_watcher_check.py` | the Diagnostics check's `lines` in all 22 languages over generated results, `_summary`, `_usage`, `_ago`, `_within`, `_reason`; Rescan's `proofs` and `judge` over a scripted engine (retired, rechecked, every unresolved reason, a call that raises at each step, out of time) |

The re-diff: `python -X utf8 tests/rustdiff/rediff_watcher.py --reference v0.6.26`.

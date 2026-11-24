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
| diffs | `diffs.py` | the comparisons, as unittest cases. The folder has no `__init__.py` (a namespace package) and no `test*.py`, so the lanes' discovery never enters it: it imports nothing of it and runs none of it |
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
record's state and the schema version. `car-harness serve` opens the same file read only with rusqlite and
answers `store.record_state` for every key (and one key in no record: `null`) and `store.schema_version`.
Each reply line equals `json.dumps({"id": n, "reply": {"ok": true, "value": <the reference's value>}})`:
27 records, schema 5, 29 values, identical.

## Dependencies (crates.io only)

`rusqlite` 0.43 with `bundled` (D4; libsqlite3-sys 0.40, SQLite 3.54.1, above the bundled Python's), and
`serde_json` 1 to read requests (D5), which brings `serde`. The JSON writer is our own, inline in
`src/pyjson.rs` and marked to be replaced by S0.2's in car-machine.

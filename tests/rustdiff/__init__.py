"""The differential harness (v0.6.27 Rust core port, PLAN.md section 4): the same inputs through the reference -
a tagged release's Python, run as tests/released.py runs released trees - and through the Rust core, the
outputs compared byte for byte (D12).

* `reference` - the reference tag (D17: the v0.6.26 tag; a stand-in until it exists) and how its code runs.
* `core` - the Rust binaries of rust/crates/car-harness: where they are, how they are built and started.
* `shim` - CODEX_AR_CORE=rust: the product's entry points started as the Rust binary (tests/sitecustomize.py
  and scripts/test_parts.py install it; without the variable nothing here is imported).
* `diffs` - the diffs themselves, as unittest cases. No file here is named test*.py, so the standard and
  advanced lanes' discovery never collects them: they run through `run.py`, the one entry point CI calls.

Not a test package of the suite (see above); README.md beside this file records the runs.
"""

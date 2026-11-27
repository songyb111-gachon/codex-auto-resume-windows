"""Loaded by Python itself in every interpreter that has tests/ on its path (PYTHONPATH="src;tests", as
every local run of the suite is started): the guard that fails a test which reaches the real Windows toast
(tests/no_real_toast.py), and the one that keeps this PC's Codex processes out of every test
(tests/no_real_codex.py). It never raises: an interpreter must start whatever happens here.

v0.6.27 (the Rust core port): with CODEX_AR_CORE=rust, also the shim that starts the product's entry points as
the Rust binary (tests/rustdiff/shim.py). Without that variable the only things this adds are one look at
os.environ, which `site` has imported already, and CAR_NO_POWER_ACTION set in it for every child (the Rust core's
power-action guard): no module is loaded and nothing is patched.

Not a test module (no `test_` prefix), so discovery does not collect it."""
import os as _os
import sys as _sys

# The Rust core's power-action guard (car-platform powerdown): the reference refuses a power action whenever
# "unittest" is in sys.modules, and a Rust child of a test has no sys.modules, so every interpreter of the suite says
# it in the one way the Rust side reads, before anything can start a child. No test can sleep or shut this PC down.
_os.environ.setdefault("CAR_NO_POWER_ACTION", "1")
# The Rust core's real-engine guard (car-platform realengine), the same way: no Rust child of a test finds, lists or
# starts this PC's installed Codex engine or the Codex app.
_os.environ.setdefault("CAR_NO_REAL_ENGINE", "1")

if _os.environ.get("CODEX_AR_CORE") == "rust":
    try:
        import importlib.util as _util

        _spec = _util.spec_from_file_location(
            "rustdiff_shim", _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "rustdiff", "shim.py"))
        _shim = _util.module_from_spec(_spec)
        _sys.modules["rustdiff_shim"] = _shim
        _spec.loader.exec_module(_shim)
        _shim.install()
    except Exception as _exc:   # pragma: no cover - said, never in the way of the interpreter
        _sys.stderr.write("CODEX_AR_CORE=rust, but the shim did not install (%r): the Python core runs\n" % (_exc,))
try:
    import no_real_toast as _no_real_toast

    _no_real_toast.install()
except Exception:   # pragma: no cover - a guard that cannot load must not stop the interpreter
    pass
try:
    import no_real_codex as _no_real_codex

    _no_real_codex.install()
except Exception:   # pragma: no cover - the same: never in the way of the interpreter
    pass

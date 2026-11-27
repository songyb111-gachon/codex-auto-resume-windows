"""The Rust side: rust/crates/car-harness's two binaries, built and started.

* `car-core-stub` stands in for codex-auto-resume.exe: `bridge|mcp|cli` and then the Python entry point's
  own argv. The shim (shim.py) starts it; so does a diff that runs one command.
* `car-harness serve` answers JSON-lines calls (`Harness`), the framing `controlcli serve` uses.

CODEX_AR_CORE_EXE and CODEX_AR_HARNESS_EXE name other builds (a CI artifact, say); otherwise the release
build beside the crate is used. Every process gets no console window and scratch homes (reference.py).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
# Every Rust process a diff starts (the harness, the stub core, a probe) inherits the core's power-action guard, as
# tests/sitecustomize.py gives every interpreter of the suite: the reference refuses under unittest, Rust by this.
POWER_GUARD = "CAR_NO_POWER_ACTION"
os.environ.setdefault(POWER_GUARD, "1")
# And the real-engine guard (car-platform realengine): no Rust process of a diff finds, lists or starts this PC's
# installed Codex engine or app (twice on 2026-11-27 a test reached the owner's codex.exe).
REAL_ENGINE_GUARD = "CAR_NO_REAL_ENGINE"
os.environ.setdefault(REAL_ENGINE_GUARD, "1")
CRATE = ROOT / "rust" / "crates" / "car-harness"
MANIFEST = CRATE / "Cargo.toml"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def target_dir() -> Path:
    """Where cargo puts the build: CARGO_TARGET_DIR when set, else the standard workspace's rust/target (the
    crate is one of its members, with its one Cargo.lock)."""
    named = os.environ.get("CARGO_TARGET_DIR")
    return Path(named) if named else ROOT / "rust" / "target"


def binary(name: str) -> Path:
    variable = {"car-core-stub": "CODEX_AR_CORE_EXE", "car-harness": "CODEX_AR_HARNESS_EXE"}[name]
    named = os.environ.get(variable)
    return Path(named) if named else target_dir() / "release" / (name + ".exe")


def build() -> None:
    """`cargo build --release --locked` of the harness crate alone, four jobs unless CARGO_BUILD_JOBS says
    otherwise. Raises CalledProcessError with cargo's own output on a failed build."""
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    subprocess.run(["cargo", "build", "--release", "--locked", "--manifest-path", str(MANIFEST)],
                   env=environment, check=True, creationflags=NO_WINDOW, timeout=1800)


def build_rest() -> None:
    """The other binaries a diff runs, so that `run.py --build` never leaves one of them stale (Integration 6: the
    advanced examples were built only when missing, and an advstore.exe from before a merge differed): the standard
    workspace's release binaries (car-legacy's python.exe, car-bin's codex-auto-resume.exe, which diffs_review4 runs),
    and, where advanced/ is in the checkout, car-adv's `advprobe`, `advstore`, `advcodex`, `advfake`, `advreport` and
    `advhook` examples, S7.2a's `advtrace`, and the P7 seats' (Integration 10): S7.2a3's `advserve` (the advanced proxy),
    S7.3b's `advcourier`, S7.2b's `advaccount`, S7.2d's `advusage`, S7.2e1's `advturns` and S7.2e2's `advtime`, and
    S7.4's `advmeasure` (Integration 11)."""
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    subprocess.run(["cargo", "build", "--release", "--locked", "--manifest-path", str(CRATE.parents[1] / "Cargo.toml")],
                   env=environment, check=True, creationflags=NO_WINDOW, timeout=3600)
    advanced = CRATE.parents[2] / "advanced" / "rust" / "Cargo.toml"
    if advanced.is_file():
        subprocess.run(["cargo", "build", "--release", "--locked", "-p", "car-adv", "--example", "advprobe",
                        "--example", "advstore", "--example", "advcodex", "--example", "advfake", "--example", "advreport",
                        "--example", "advhook", "--example", "advtrace", "--example", "advserve", "--example", "advcourier",
                        "--example", "advaccount", "--example", "advusage", "--example", "advturns", "--example", "advtime",
                        "--example", "advmeasure",
                        "--manifest-path", str(advanced)],
                       env=environment, check=True, creationflags=NO_WINDOW, timeout=3600)


def missing() -> list[str]:
    """The binaries not built yet."""
    return [name for name in ("car-core-stub", "car-harness") if not binary(name).is_file()]


def stub(*argv, environment: dict, stdin: bytes | None = None, cwd=None) -> subprocess.CompletedProcess:
    """One run of car-core-stub with `argv` (its entry point first: "bridge", "mcp" or "cli")."""
    return subprocess.run([str(binary("car-core-stub")), *map(str, argv)], input=stdin, capture_output=True,
                          env=environment, cwd=cwd, creationflags=NO_WINDOW, timeout=300)


class Harness:
    """`car-harness serve` for the length of a `with`: `call(name, **fields)` returns the reply line's bytes."""

    def __init__(self, environment: dict):
        self.environment, self.process, self.next_id = environment, None, 0

    def __enter__(self):
        self.process = subprocess.Popen([str(binary("car-harness")), "serve"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.environment,
                                        creationflags=NO_WINDOW)
        return self

    def call(self, call: str, **fields) -> tuple[int, bytes]:
        """Send one request; answer (its id, the reply line as written, newline included)."""
        self.next_id += 1
        request = dict(fields, id=self.next_id, call=call)
        self.process.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        self.process.stdin.flush()
        return self.next_id, self.process.stdout.readline()

    def __exit__(self, *_exc):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=30)
        finally:
            if self.process.poll() is None:
                self.process.kill()
            self.process.stdout.close()
            self.process.stderr.close()

"""The reference: a tag's own Python, in a process of its own, on scratch homes only.

D17 makes the v0.6.26 tag the reference. It is not tagged yet, so `TAG` is v0.6.26-beta.2 until it is, and
CODEX_AR_REFERENCE names another tag for one run. The tag's tree is taken out of git by tests/released.py
(`released.package`), exactly as the released-tree tests take theirs; what differs from `released.run` is
that the answer is kept as the bytes the process wrote, not parsed, because the diff is byte for byte.

Every home a release could look for points into a scratch folder, the process gets no console window, and
neither the shim's variable nor this checkout's tests/ reach it: PYTHONPATH is the tag's src alone.

The Python it runs on is the one the product ships, the bundled embeddable 3.14.10, not whatever `sys.executable` is
(refpython.py: `bundled` by default, `system` or a path by CODEX_AR_REFERENCE_PYTHON / run.py --reference-python).
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

import released
from rustdiff import refguard, refpython, reftwin

# D17's tag. Until v0.6.26 is tagged, its last pre-release stands in (change this line, not the callers). The tag
# that `run.py --reference` (CODEX_AR_REFERENCE) names is the one every run uses; this is only what no one named.
STAND_IN = "v0.6.26-beta.2"
TAG = os.environ.get("CODEX_AR_REFERENCE") or STAND_IN
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOME_VARIABLES = ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "CODEX_HOME", "CODEX_AUTO_RESUME_HOME")
# What never reaches the reference: the shim's switch, and the edition the lane under it runs.
DROPPED = ("CODEX_AR_CORE", "CODEX_AR_CORE_EXE", "CODEX_AR_HARNESS_EXE", "CODEX_AR_EDITION")


def scratch_environment(profile: Path, **extra) -> dict:
    """os.environ with every home pointed at `profile`, the shim's variables gone, and the engine's path pointing where no
    codex.exe is (refguard.py) unless `extra` hands one (a path); leaving it unset is a discovery run's alone
    (refguard.discovery_environment, DISCOVERY_SUBJECTS).
    Both sides of a diff build their environment here, so both see the same engine path."""
    environment = {name: value for name, value in os.environ.items() if name not in DROPPED}
    environment.update({name: str(profile) for name in HOME_VARIABLES})
    return refguard.environment(environment, **extra)


def command(script: str, *arguments, paths, which=None) -> list:
    """The argv of the reference's process: `script` as sys.argv[1:] has it, `paths` first on its sys.path, on the Python
    refpython.py chose. Other callers that start the reference themselves (advref, the claim race) use this."""
    return refpython.command(script, *arguments, paths=paths, which=which)


def script_command(path, *arguments, paths, which=None) -> list:
    """The same for a script FILE (a generator, a script too long for a command line)."""
    return refpython.script_command(path, *arguments, paths=paths, which=which)


def run(script: str, *arguments, profile: Path | None = None, tag: str | None = None,
        stdin: bytes | None = None) -> subprocess.CompletedProcess:
    """Run `script` under the reference tag's package with `arguments` as sys.argv[1:]. Returns the finished
    process with stdout and stderr as bytes; a non-zero exit is the caller's to judge (a refusal exits 1)."""
    source = released.package(tag or TAG)
    with tempfile.TemporaryDirectory(prefix="rustdiff-reference-") as own:
        home = Path(profile) if profile is not None else Path(own)
        environment = scratch_environment(home, PYTHONPATH=str(source))

        def start(which):
            return subprocess.run(command(script, *arguments, paths=[source], which=which), input=stdin,
                                  capture_output=True, env=environment, cwd=str(home), creationflags=NO_WINDOW,
                                  timeout=300)

        if reftwin.twin():  # the same script on a second Python too (reftwin.py); the answer is the chosen one's
            return reftwin.twinned(start, home, script, arguments)
        return start(None)


# The bridge as the tag's own entry point runs it - controlcli.main with the argv given - on a source tree,
# which no administrator's policy reaches (control/policy.managed_policy: config.installed_home() is None).
BRIDGE = r'''
import sys
from codex_auto_resume import config
if config.installed_home() is not None:
    raise SystemExit("the reference must run from a source tree, never an installed one")
from codex_auto_resume.controlcli import main
sys.exit(main(sys.argv[1:]))
'''


def bridge(*argv, profile: Path, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    """The tag's bridge (`controlcli.main(argv)`) in its own process."""
    return run(BRIDGE, *argv, profile=profile, stdin=stdin)

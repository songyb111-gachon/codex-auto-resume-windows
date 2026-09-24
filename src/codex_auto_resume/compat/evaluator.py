"""The watcher's side: recompute when something changed, write the report, answer the
gate's one word; and the refresh a person asks for.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

from .. import config
from .. import compat
from .. import codex as codex_source
from . import files, probes
from .files import (REFRESH_EXIT, REFRESH_TIMEOUT_SECONDS, _stamp, product_version,
                    write_json_atomic)
from .cache import (_cache_empty, _coerce, _sources_of, judge_cache, read_cache)
from .probes import (_candidate_paths, engine_from_backend, engine_from_discovery)
from .views import (assemble)

# ------------------------------------------------------------------------------ the watcher
class Evaluator:
    """The watcher's side: recompute when something changed, write the report, and answer
    the one word the engine's gate reads.

    The word the gate reads - `acting` - is evaluated for the backend the watcher is driving,
    from the checks that backend passed when it was accepted, plus the registry data in
    force. That is deliberate. The engine has always decided on the verdict it started
    with, and a gate that changed its answer under a running engine (a binary that vanished
    mid-update, say) would move decisions - supersessions and budget stops - that happen
    after it. So the gate's answer moves only with the registry data a person imported,
    while the report says what is true now, and says so when the two differ.
    """

    def __init__(self, paths, codex_home, *, product=None, log=None, clock=time.time,
                 recompute=compat.RECOMPUTE_SECONDS, source=None, explicit=None):
        self.paths = paths
        self.explicit = explicit
        self.codex_home = Path(codex_home)
        self.product = product or product_version()
        self.log = log or (lambda *args: None)
        self.clock = clock
        self.recompute = recompute
        self.source = source
        self.bundled, self.bundled_state = files.load_bundled(product=self.product, now=clock())
        self.cache = _cache_empty()
        self._cache_stamp = ("never",)
        self._engine_key = None
        self._backend_seen = None
        self._last_at = None
        self.report = None
        self.acting = None
        self._said = None
        self._write_failed = False

    def _sources(self):
        return _sources_of(self.bundled, self.cache)

    def acting_for(self, backend) -> str:
        """The gate's word for a backend that exists: its accepted checks all passed."""
        return compat.accepted_word(getattr(backend, "engine_version", None), self._sources())

    def _engine_key_of(self, backend, discovery):
        if backend is not None:
            try:
                return ("backend", id(backend), _stamp(backend.codex_exe))
            except Exception:
                return ("backend", id(backend), None)
        items = []
        for path, result in sorted((discovery or {}).items()):
            result = result if isinstance(result, dict) else {}
            items.append((path, repr(result.get("signature")),
                          tuple(_coerce(result.get(name)) for name in
                                ("official_location", "version_runs", "queue_flags"))))
        return ("discovery", tuple(items))

    def tick(self, backend, discovery=None) -> str:
        """Called once per watcher tick, before the engine ticks. Returns the gate's word."""
        now = self.clock()
        stamp = _stamp(self.paths.compat_cache_file)
        cache_changed = stamp != self._cache_stamp
        if cache_changed:
            self.cache = read_cache(self.paths.compat_cache_file, bundled=self.bundled,
                                    product=self.product, now=now)
            self._cache_stamp = stamp
        else:
            # The file did not change, but time did: the cache may have expired, or a clock
            # that was behind may have caught up with it. Judged in memory, every tick, so
            # the gate never keeps trusting data past its expiry.
            judged = judge_cache(self.cache, bundled=self.bundled, product=self.product, now=now)
            if judged.get("state") != self.cache.get("state"):
                self.cache = judged
                cache_changed = True
        engine_key = self._engine_key_of(backend, discovery)
        due = (self.report is None or cache_changed or engine_key != self._engine_key
               or self._last_at is None or now - self._last_at >= self.recompute)
        if due:
            if backend is not None:
                engine_checks, engine = engine_from_backend(backend)
            else:
                engine_checks, engine = engine_from_discovery(
                    discovery, candidates=len(_candidate_paths(self.explicit)))
            source = self.source or codex_source.LocalSource(self.codex_home)
            report = assemble(engine_checks=engine_checks, engine=engine,
                              other_checks={**probes.source_checks(source), **probes.api_checks()},
                              bundled=self.bundled, bundled_state=self.bundled_state,
                              cache=self.cache, product=self.product, now=now)
            acting = self.acting_for(backend) if backend is not None else report["overall"]
            self.report = dict(report, acting=acting)
            self._engine_key, self._last_at = engine_key, now
            self._write()
        else:
            acting = self.acting_for(backend) if backend is not None else self.report["overall"]
            if acting != self.report.get("acting"):
                self.report = dict(self.report, acting=acting)
                self._write()
        self.acting = acting
        self._say()
        return acting

    def _write(self):
        try:
            write_json_atomic(self.paths.compat_report_file, self.report, "compatibility.")
            self._write_failed = False
        except OSError:
            if not self._write_failed:
                self.log("compatibility report could not be written; readers will show unknown")
            self._write_failed = True

    def _say(self):
        """One log line whenever what is known changes: codes and the version string only."""
        report = self.report
        failing = sorted("%s=%s/%s" % (name, entry["state"], entry["reason"])
                         for name, entry in report["capabilities"].items()
                         if entry["state"] in (compat.INCOMPATIBLE, compat.UNKNOWN)
                         and entry["reason"] != "not_implemented")
        said = (report.get("acting"), report["overall"], report["engine"]["version"],
                report["data"]["cache"], tuple(failing))
        if said == self._said:
            return
        self._said = said
        self.log("compatibility: acting %s, found %s (engine %s; data %s, cache %s)%s" % (
            report.get("acting"), report["overall"], report["engine"]["version"] or "not found",
            report["data"]["source"], report["data"]["cache"],
            "; not established: " + ", ".join(failing) if failing else ""))


# ------------------------------------------------------------------------------ the refresh
def run_refresh(home, *, script=None, timeout=REFRESH_TIMEOUT_SECONDS, runner=None) -> dict:
    """Start the one fetch there is: `scripts/bootstrap.ps1 -Compatibility`, for the
    Diagnostics button. The script downloads from its one constant URL to a temporary file
    and hands it to `import_document` through the bridge; this reads back its one line.

    The line and the exit code have to agree, as the update check's do; a disagreement is
    `failed`, never guessed into an answer.
    """
    runner = runner or subprocess.run
    script = Path(script) if script else config.PROJECT_ROOT / "scripts" / "bootstrap.ps1"
    powershell = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
                  / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    answer = {"answer": "failed", "sequence": None, "reason": None}
    if not script.is_file() or not powershell.is_file():
        return dict(answer, answer="incomplete")
    environment = dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=str(Path(home)))
    try:
        done = runner([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                       "Bypass", "-File", str(script), "-Compatibility"],
                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                      text=True, encoding="utf-8", errors="replace", timeout=timeout,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False,
                      env=environment)
    except subprocess.TimeoutExpired:
        return dict(answer, answer="unavailable")
    except (OSError, ValueError, subprocess.SubprocessError):
        return answer
    line = None
    for raw in (done.stdout or "").splitlines():
        if raw.strip().startswith("compatibility: "):
            line = raw.strip()[len("compatibility: "):].split()
    if not line:
        return answer
    said = line[0]
    if said not in REFRESH_EXIT or REFRESH_EXIT[said] != done.returncode:
        return answer
    result = dict(answer, answer=said)
    if said == "refreshed" and len(line) > 1 and line[1].isdigit():
        result["sequence"] = int(line[1])
    if said == "refused" and len(line) > 1 and line[1] in compat.IMPORT_REASONS:
        result["reason"] = line[1]
    return result

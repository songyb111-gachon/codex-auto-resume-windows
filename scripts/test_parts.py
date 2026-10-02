"""Run the test suite in parts - one part, or every part at once - with the result one whole run gives.

The suite took 78 to 103 minutes a lane on GitHub's runners in September 2026, and the ko sync's four
round-robin parts took 9, 18, 18 and 32 minutes of it. This deals the test files into N parts, balanced
by how long each file took when it was last measured, and runs them. It is the only place the split is
written: CI's lanes (.github/workflows/test.yml), the release's suite (release.yml) and the ko sync
(sync-ko.yml) all run it, and nothing else decides which file goes where.

    python scripts/test_parts.py                          # the whole suite: unittest discover itself
    python scripts/test_parts.py --parallel 8             # the same suite in 8 parts at once
    python scripts/test_parts.py --part 2/8               # only the second of 8 parts
    python scripts/test_parts.py --lane advanced ...      # the advanced edition's lane
    python scripts/test_parts.py --outcomes FILE ...      # every test id's outcome, as JSON
    python scripts/test_parts.py --compare A.json B.json  # two outcome files, test by test
    python scripts/test_parts.py --record-durations ...   # write this run's per-file times
    python scripts/test_parts.py --list --parts 8         # show how 8 parts are dealt
    python scripts/test_parts.py --check                  # prove the parts are the discovered suite

With neither --part nor --parallel it runs the whole suite as CI always ran it: `python -m unittest
discover -s <suite>` itself (unittest.main, as `-m unittest` calls it), one fresh interpreter for each suite,
recording each test id's outcome as it goes. That is the run the parts are compared with (--compare).

What a part runs is that, restricted to its files: the same file rule (discover's pattern `test*.py` and
its module-name rule), the same loading call - discover itself, once per file - in the same order, the same
runner settings (the warnings filter, verbosity), the same `sys.path[0]` and `sys.argv`, one fresh
interpreter for each suite. `--check` proves the first half: for every suite, the files loaded one by one
are exactly the tests discover finds, in its order, and for every N the parts together are each of them
exactly once. Whether each test's outcome is the same is the tests' own business - a file that leans on
another having run first, or on a name no other process may use - and `--compare` answers it. Parts run at
once on one machine also contend for it - one desktop for the window tests, one processor for the probes'
timeouts and the timing checks - which a runner of its own never does; so `--compare` names the part a
differing test ran in, and holds that part run alone (`--part K/N`) to the whole run on the part's files.

A lane is the suites one CI job runs and how each is run (LANES):

* standard - tests/, with src on the path: the standard edition.
* advanced - tests/ and then advanced/tests/, with src and advanced/src on the path: core with an
  advanced checkout beside it, which must change nothing, and the package's own tests.
* release - tests/ as the standard edition and advanced/tests/ as the advanced one: the two suites the
  release workflow runs before it builds each edition's archive.

Every suite of a part runs, and the part fails after the last if any failed. `--parallel N` starts all N
parts as child processes, each with a temporary directory of its own (TEMP and TMP), and prints one merged
summary with one exit code. Every child gets CREATE_NO_WINDOW and is python.exe, never pythonw.exe: a
console program started by a process with no console opens a window (tests/test_no_console_windows.py).

The durations are tests/data/durations.json, seconds per file - its tests and their class and module
fixtures, from the end of one test to the end of the next - measured on a whole run; a file with no
measurement yet is dealt round-robin after the measured ones. `--record-durations` rewrites the file from
the run it ends, keeping entries for files the run did not include and dropping files that are gone.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import locale
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
DURATIONS = ROOT / "tests" / "data" / "durations.json"
# `unittest discover`'s own defaults: the pattern it matches file names against, and the rule a file
# name must pass to be a module it imports (unittest.loader.VALID_MODULE_NAME).
PATTERN = "test*.py"
VALID_MODULE_NAME = re.compile(r"[_a-z]\w*\.py$", re.IGNORECASE)
# A developer tool, but it ships in scripts/ with the product, and every console program anything the
# product ships starts gets a hidden console of its own.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STANDARD = {"PYTHONPATH": "src", "CODEX_AR_EDITION": "standard"}
ADVANCED = {"PYTHONPATH": os.pathsep.join(("src", "advanced/src")), "CODEX_AR_EDITION": "advanced"}
# Each lane: its suites in the order they run, and what each is run with.
LANES = {
    "standard": (("tests", STANDARD),),
    "advanced": (("tests", ADVANCED), ("advanced/tests", ADVANCED)),
    "release": (("tests", STANDARD), ("advanced/tests", ADVANCED)),
}
# What a test id can come out as. A test with a failing subtest is a failure, and the worse word wins
# when one id is reported twice (a subtest, then its test).
OUTCOMES = ("pass", "skip", "expected-failure", "unexpected-success", "fail", "error")
RANK = {word: rank for rank, word in enumerate(OUTCOMES)}
SEPARATOR = "=" * 70


class Refused(SystemExit):
    pass


# --- which files, and which part each is in ---------------------------------------------------------

def suite_files(suite: str) -> list[str]:
    """The file names `unittest discover -s <suite>` imports, in the order it runs them."""
    folder = ROOT / suite
    names = []
    for name in sorted(os.listdir(folder)):
        path = folder / name
        if path.is_dir():
            if (path / "__init__.py").is_file():
                # discover would go into it; this deals files, so it would not.
                raise Refused("%s/%s is a package; the split deals the files of one folder" % (suite, name))
            continue
        if VALID_MODULE_NAME.match(name) and fnmatch.fnmatch(name, PATTERN):
            names.append(name)
    return names


def lane_files(lane: str) -> list[str]:
    """Every file a lane runs, as `<suite>/<name>`, suites in the lane's order."""
    return ["%s/%s" % (suite, name) for suite, _ in LANES[lane] for name in suite_files(suite)]


def load_durations(path: Path = DURATIONS) -> dict:
    try:
        seconds = json.loads(path.read_text(encoding="utf-8"))["seconds"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {key: float(value) for key, value in seconds.items()
            if isinstance(value, (int, float)) and value >= 0}


def deal(files: list[str], count: int, seconds: dict) -> list[list[str]]:
    """`files` in `count` parts: the measured ones longest first, each to the part with the least so far
    (the lowest-numbered on a tie), then the unmeasured ones round-robin in name order. Deterministic: the
    same files, count and durations always give the same parts. Each part keeps the lane's order."""
    if count < 1:
        raise Refused("a suite in %d parts is no suite" % count)
    if count > len(files):
        raise Refused("%d parts of %d files would leave a part with nothing to run" % (count, len(files)))
    parts = [[] for _ in range(count)]
    load = [0.0] * count
    for name in sorted((f for f in files if f in seconds), key=lambda f: (-seconds[f], f)):
        smallest = min(range(count), key=lambda index: (load[index], index))
        parts[smallest].append(name)
        load[smallest] += seconds[name]
    for index, name in enumerate(sorted(f for f in files if f not in seconds)):
        parts[index % count].append(name)
    order = {name: index for index, name in enumerate(files)}
    return [sorted(part, key=order.__getitem__) for part in parts]


def parse_part(text: str) -> tuple[int, int]:
    found = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", text or "")
    if not found or not 1 <= int(found.group(1)) <= int(found.group(2)):
        raise argparse.ArgumentTypeError("a part is K/N with 1 <= K <= N, such as 2/8")
    return int(found.group(1)), int(found.group(2))


# --- the worker: one suite, some of its files, in a fresh interpreter ------------------------------

class Recorder(unittest.TextTestResult):
    """The text result `unittest` prints, which also keeps each test id's outcome, and the seconds from the
    end of one test to the end of the next under the next one's module: its test, and the class and module
    fixtures set up before it. Nothing about the run changes; the result only listens."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes, self.modules = {}, {}
        self.clock = time.perf_counter()

    def startTestRun(self):
        super().startTestRun()
        self.clock = time.perf_counter()

    def stopTest(self, test):
        super().stopTest(test)
        now, module = time.perf_counter(), type(test).__module__
        self.modules[module] = self.modules.get(module, 0.0) + now - self.clock
        self.clock = now

    def _put(self, test, word):
        key = test.id()
        if key not in self.outcomes or RANK[word] > RANK[self.outcomes[key]]:
            self.outcomes[key] = word

    def addSuccess(self, test):
        super().addSuccess(test)
        self._put(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._put(test, "fail")

    def addError(self, test, err):
        super().addError(test, err)
        self._put(test, "error")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._put(test, "skip")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._put(test, "expected-failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._put(test, "unexpected-success")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            word = "fail" if issubclass(err[0], test.failureException) else "error"
            self._put(subtest, word)
            self._put(test, word)


class Runner(unittest.TextTestRunner):
    resultclass = Recorder


def work(suite: str, names: list[str], report: str, verbose: bool) -> int:
    """What `python -m unittest discover -s <suite>` does - all of it when `names` is empty, else for
    `names` only - and the record of it."""
    # `python -m` puts the working directory first on the path, where running this file put scripts/.
    sys.path[0] = os.getcwd()
    sys.argv = ["python -m unittest", "discover", "-s", suite] + (["-v"] if verbose else [])
    if not names:
        # The whole suite: what `python -m unittest` runs - unittest.main(module=None) - with a result
        # that only listens.
        result = unittest.main(module=None, argv=list(sys.argv), testRunner=Runner, exit=False).result
    else:
        loader = unittest.TestLoader()
        # discover itself, with each file's own name as the pattern: the same import, the same handling
        # of a file that cannot be imported, the same tests in the same order as a whole discover.
        files = [loader.discover(suite, pattern=name) for name in names]
        runner = Runner(verbosity=2 if verbose else 1, warnings=None if sys.warnoptions else "default")
        result = runner.run(unittest.TestSuite(files))
    mine = set(suite_files(suite))
    record = {
        "outcomes": result.outcomes,
        "seconds": {"%s/%s.py" % (suite, module): round(value, 3) for module, value in result.modules.items()
                    if module + ".py" in mine},
        "counts": counts_of(result),
        "ok": result.wasSuccessful(),
    }
    Path(report).write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


def counts_of(result) -> dict:
    return {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
            "skipped": len(result.skipped), "expected failures": len(result.expectedFailures),
            "unexpected successes": len(result.unexpectedSuccesses)}


# --- a part: each suite of the lane in its own worker, one after the other -------------------------

def interpreter() -> str:
    """python.exe: pythonw.exe has no console to hand down, so everything the tests start would open one."""
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe" and executable.with_name("python.exe").is_file():
        return str(executable.with_name("python.exe"))
    return str(executable)


def write_out(data: bytes) -> None:
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(data.decode(locale.getpreferredencoding(False), "replace"))
    else:
        stream.write(data)
    sys.stdout.flush()


def say(text: str) -> None:
    write_out((text + "\n").encode(getattr(sys.stdout, "encoding", None) or "utf-8", "replace"))


def run_worker(suite: str, names: list[str], env: dict, verbose: bool) -> tuple[int, bytes, dict]:
    """One suite's files - all of it, as discover runs it, when `names` is empty - in a fresh interpreter,
    its output passed through as it comes."""
    handle, report = tempfile.mkstemp(prefix="test-parts-", suffix=".json")
    os.close(handle)
    try:
        environment = dict(os.environ)
        environment.update(env)
        argv = [interpreter(), str(Path(__file__).resolve()), "--worker", suite, "--report", report]
        argv += (["-v"] if verbose else []) + list(names)
        child = subprocess.Popen(argv, cwd=str(ROOT), env=environment, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        captured = bytearray()
        with child.stdout:
            for chunk in iter(lambda: child.stdout.read1(65536), b""):
                write_out(chunk)
                captured += chunk
        code = child.wait()
        try:
            record = json.loads(Path(report).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}                     # it died before writing one: the exit code says so
        return code, bytes(captured), record
    finally:
        try:
            os.remove(report)
        except OSError:
            pass


def annotation(suite: str, where: str, output: bytes) -> str:
    """A GitHub error annotation for a failed suite: the failures, not the roll-call of passing tests.

    An annotation is capped at 4096 characters, and a verbose run fills that with "ok" lines long before
    the part that says what went wrong; an annotation is also part of a run's public status, where its
    log is not."""
    lines = output.decode(locale.getpreferredencoding(False), "replace").splitlines()
    first = next((index for index, line in enumerate(lines) if re.match(r"(FAIL|ERROR):", line)), None)
    # No failure header at all means the process died rather than failed a test; the tail is then the
    # only evidence there is.
    detail = [line for line in lines[first:] if line.strip()] if first is not None else \
        [line for line in lines if line.strip()][-25:]
    text = "\n".join(detail).replace("::", ":")[:3800]
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return "::error title=test suite failed (%s, %s)::%s" % (suite, where, text)


def run_part(lane: str, part: int | None, count: int, *, verbose: bool = False, annotate: bool = False,
             worker=run_worker) -> dict:
    """Part `part` of `count` of a lane - the whole lane, each suite as discover runs it, when `part` is
    None: every suite with files in the part, each in its own worker. Every suite runs, and the part has
    failed if any of them did."""
    mine = set(lane_files(lane) if part is None else deal(lane_files(lane), count, load_durations())[part - 1])
    where = "the whole suite" if part is None else "part %d of %d" % (part, count)
    merged = {"outcomes": {}, "seconds": {}, "counts": {}, "ok": True, "suites": [],
              "files": [name for name in lane_files(lane) if name in mine]}
    if part is not None:
        merged["part"] = "%d/%d" % (part, count)
    for suite, env in LANES[lane]:
        names = [name for name in suite_files(suite) if "%s/%s" % (suite, name) in mine]
        if not names:
            continue
        say("%s, lane %s: %s, %d of its files" % (where, lane, suite, len(names)))
        # The whole suite is discover's to find; a part names its files.
        code, output, record = worker(suite, [] if part is None else names, env, verbose)
        passed = code == 0 and record.get("ok") is True
        if not record:
            say("%s: the interpreter running %s ended with exit code %d before it reported: it died, "
                "which no test's result explains" % (where, suite, code))
        merged["suites"].append({"suite": suite, "files": len(names), "ok": passed})
        merged["ok"] = merged["ok"] and passed
        for key, word in record.get("outcomes", {}).items():
            if key in merged["outcomes"]:
                raise Refused("%s ran in two suites of one part" % key)
            merged["outcomes"][key] = word
        merged["seconds"].update(record.get("seconds", {}))
        for name, value in record.get("counts", {}).items():
            merged["counts"][name] = merged["counts"].get(name, 0) + value
        if not passed and annotate:
            say(annotation(suite, where, output))
    return merged


# --- every part at once ----------------------------------------------------------------------------

def failure_text(log: bytes) -> str:
    """The failure blocks of a part's output: from each worker's first separator to its `Ran` line."""
    lines = log.decode(locale.getpreferredencoding(False), "replace").splitlines()
    shown, inside = [], False
    for line in lines:
        if line == SEPARATOR:
            inside = True
        if inside:
            shown.append(line)
        if inside and re.match(r"Ran \d+ tests? in ", line):
            inside = False
    return "\n".join(shown) if shown else "\n".join(lines[-25:])


def run_parallel(lane: str, count: int, *, verbose: bool = False) -> tuple[dict, list]:
    """All `count` parts at once, as child processes with a temporary directory each."""
    dealt = deal(lane_files(lane), count, load_durations())   # a count that cannot be dealt is refused here
    base = Path(tempfile.mkdtemp(prefix="tp"))
    children = []
    try:
        for part in range(1, count + 1):
            folder = base / str(part)
            folder.mkdir()
            env = dict(os.environ, TEMP=str(folder), TMP=str(folder))
            log = open(base / ("part-%d.log" % part), "wb")
            argv = [interpreter(), str(Path(__file__).resolve()), "--lane", lane, "--part",
                    "%d/%d" % (part, count), "--report", str(base / ("part-%d.json" % part))]
            argv += ["-v"] if verbose else []
            child = subprocess.Popen(argv, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            children.append({"part": part, "child": child, "log": log, "started": time.perf_counter()})
        waiting = list(children)
        while waiting:
            for entry in list(waiting):
                if entry["child"].poll() is None:
                    continue
                entry["seconds"] = time.perf_counter() - entry["started"]
                entry["log"].close()
                waiting.remove(entry)
                report = base / ("part-%d.json" % entry["part"])
                try:
                    entry["record"] = json.loads(report.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    entry["record"] = {"ok": False, "outcomes": {}, "seconds": {}, "counts": {}}
                entry["ok"] = entry["child"].returncode == 0 and entry["record"].get("ok") is True
                say("part %d of %d: %s, %d tests, %.0f s" % (
                    entry["part"], count, "OK" if entry["ok"] else "FAILED",
                    entry["record"].get("counts", {}).get("run", 0), entry["seconds"]))
            if waiting:
                time.sleep(0.25)
    except BaseException:
        for entry in children:
            if entry["child"].poll() is None:
                entry["child"].kill()
        raise
    merged = {"outcomes": {}, "seconds": {}, "counts": {}, "ok": True, "files": lane_files(lane), "deal": dealt}
    for entry in children:
        record = entry["record"]
        merged["ok"] = merged["ok"] and entry["ok"]
        for key, word in record.get("outcomes", {}).items():
            if key in merged["outcomes"]:
                raise Refused("%s ran in two parts" % key)
            merged["outcomes"][key] = word
        merged["seconds"].update(record.get("seconds", {}))
        for name, value in record.get("counts", {}).items():
            merged["counts"][name] = merged["counts"].get(name, 0) + value
        if not entry["ok"]:
            say("\n--- part %d of %d failed; its log: %s" % (entry["part"], count, base / ("part-%d.log" % entry["part"])))
            say(failure_text((base / ("part-%d.log" % entry["part"])).read_bytes()))
    if merged["ok"]:
        shutil.rmtree(base, ignore_errors=True)
    return merged, [(entry["part"], entry["seconds"]) for entry in children]


# --- the proof that the parts are the discovered suite ---------------------------------------------

def test_ids(suite) -> list[str]:
    found = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            found.extend(test_ids(item))
        else:
            found.append(item.id())
    return found


def check_suite(suite: str, counts: list[int]) -> dict:
    """In a fresh interpreter: discover's whole suite, the same files loaded one by one as a part loads
    them, and every lane's parts for every count, compared test id by test id."""
    sys.path[0] = os.getcwd()
    whole = test_ids(unittest.TestLoader().discover(suite, pattern=PATTERN))
    loader = unittest.TestLoader()
    by_file = {name: test_ids(loader.discover(suite, pattern=name)) for name in suite_files(suite)}
    joined = [key for name in suite_files(suite) for key in by_file[name]]
    wrong = []
    seconds = load_durations()
    for lane, suites in sorted(LANES.items()):
        if suite not in dict(suites):
            continue
        for count in counts:
            parts = deal(lane_files(lane), count, seconds)
            ids = [[key for name in part if name.rsplit("/", 1)[0] == suite
                    for key in by_file[name.rsplit("/", 1)[1]]] for part in parts]
            together = [key for part in ids for key in part]
            if sorted(together) != sorted(whole) or len(set(together)) != len(together):
                wrong.append("%s in %d parts" % (lane, count))
    return {"suite": suite, "tests": len(whole), "files": len(by_file), "same_order": joined == whole,
            "unique": len(set(whole)) == len(whole), "wrong": wrong}


def check(counts: list[int]) -> tuple[bool, list]:
    """Each suite checked in its own interpreter, with what the advanced lane runs it with: the lane that
    runs every suite there is, so no suite is loaded without what its imports need."""
    answers = []
    for suite, env in LANES["advanced"]:
        environment = dict(os.environ)
        environment.update(env)
        done = subprocess.run([interpreter(), str(Path(__file__).resolve()), "--check-suite", suite,
                               "--counts", ",".join(map(str, counts))],
                              cwd=str(ROOT), env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                              creationflags=NO_WINDOW)
        try:
            answers.append(json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1]))
        except (ValueError, IndexError):
            answers.append({"suite": suite, "error": done.stderr.decode("utf-8", "replace")[-2000:]})
    ok = all(answer.get("same_order") and answer.get("unique") and not answer.get("wrong")
             and answer.get("tests", 0) > 0 for answer in answers)
    return ok, answers


# --- outcomes, durations and the command line ------------------------------------------------------

def write_outcomes(path: str, lane: str, parts, merged: dict) -> None:
    """Every test id's outcome, and the files the run ran: the lane's, or one part's (`part`, `files`); a run
    of parts at once also keeps which part ran which file (`deal`)."""
    document = {"lane": lane, "parts": parts, "python": sys.version.split()[0]}
    document.update({key: merged[key] for key in ("part", "files", "deal") if key in merged})
    document.update({"counts": merged["counts"], "outcomes": dict(sorted(merged["outcomes"].items())),
                     "seconds": dict(sorted(merged["seconds"].items()))})
    Path(path).write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")


# A class or module fixture's id, as unittest reports one that failed: `setUpClass (module.Class)`.
FIXTURE = re.compile(r"(?:setUpClass|tearDownClass|setUpModule|tearDownModule) \((.+)\)")


def module_of(test_id: str) -> str:
    """The module a test id came from: `module.Class.test`, a subtest's `module.Class.test (x=1)`, a failed
    fixture's `setUpClass (module.Class)`, or the loader's stand-in for a file it could not import,
    `unittest.loader._FailedTest.module`."""
    found = FIXTURE.fullmatch(test_id)
    name = found.group(1) if found else test_id.split(" ", 1)[0]
    if name.startswith("unittest.loader._FailedTest."):
        return name.rsplit(".", 1)[1]
    return name.split(".", 1)[0]


def compare(first: str, second: str) -> int:
    """Two --outcomes files, test id by test id. When they ran different files - a part alone against the
    whole run - only the ids of the files both ran are held to each other. A difference in a run of parts at
    once names its part and the run that checks that part without the others."""
    documents = [json.loads(Path(name).read_text(encoding="utf-8")) for name in (first, second)]
    a, b = (document["outcomes"] for document in documents)
    keys = set(a) | set(b)
    ran = [{Path(name).stem for name in document["files"]} if document.get("files") else None
           for document in documents]
    if None not in ran and ran[0] != ran[1]:
        both, either = ran[0] & ran[1], ran[0] | ran[1]
        # An id whose module is no file either run names is held only where both runs have it.
        kept = {key for key in keys
                if (module_of(key) in both if module_of(key) in either else key in a and key in b)}
        say("the two runs ran different files: the %d both ran are held to each other; %d test ids of "
            "files only one ran are left out" % (len(both), len(keys - kept)))
        keys = kept
    holders = {}
    for document in documents:
        dealt = document.get("deal") or []
        for index, files in enumerate(dealt, 1):
            for name in files:
                holders.setdefault(Path(name).stem, (index, len(dealt), document.get("lane")))
    differ = sorted(key for key in keys if a.get(key) != b.get(key))
    checks = []
    for key in differ:
        holder = holders.get(module_of(key))
        say("%s: %s / %s%s" % (key, a.get(key, "absent"), b.get(key, "absent"),
                               " (part %d of %d)" % holder[:2] if holder else ""))
        if holder and holder not in checks:
            checks.append(holder)
    tally = {}
    for key in keys & set(a):
        tally[a[key]] = tally.get(a[key], 0) + 1
    say("%d test ids in %s, %d in %s; %d differ; %s" % (
        len(keys & set(a)), first, len(keys & set(b)), second, len(differ),
        ", ".join("%s %d" % (word, tally[word]) for word in OUTCOMES if word in tally)))
    if checks:
        say("Parts run at once contend for this machine, which a runner of its own does not. Run each part "
            "with a difference alone and compare it with the whole run: what still differs, two test files "
            "share; what agrees came from the parts running together (docs/CONTRIBUTING.md).")
        for part, count, lane in sorted(checks, key=lambda holder: holder[:2]):
            say("  python scripts/test_parts.py --lane %s --part %d/%d --outcomes part-%d.json"
                % (lane or default_lane(), part, count, part))
    return 1 if differ else 0


def record_durations(seconds: dict, path: Path = DURATIONS) -> None:
    kept = load_durations(path)
    kept.update({key: round(value, 1) for key, value in seconds.items()})
    present = {key for lane in LANES for key in lane_files(lane)}
    document = {
        "about": "Seconds each test file took (its tests and their fixtures) on the last run that recorded them, "
                 "for scripts/test_parts.py to balance its parts by. Refresh with --record-durations.",
        "seconds": {key: kept[key] for key in sorted(kept) if key in present},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")


def summary(merged: dict, seconds: float, parts=None) -> str:
    counts = merged["counts"]
    extra = ", ".join("%s=%d" % (name, counts[name]) for name in
                      ("failures", "errors", "skipped", "expected failures", "unexpected successes")
                      if counts.get(name))
    where = "" if not parts else " in %d parts (%s)" % (
        len(parts), ", ".join("%.0f s" % value for _, value in sorted(parts)))
    return "Ran %d tests%s in %.0f s: %s%s" % (counts.get("run", 0), where, seconds,
                                              "OK" if merged["ok"] else "FAILED", " (%s)" % extra if extra else "")


def default_lane() -> str:
    named = os.environ.get("CODEX_AR_EDITION", "")
    return named if named in LANES else "standard"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--lane", choices=sorted(LANES), default=None,
                        help="which suites, run how (default: CODEX_AR_EDITION, else standard)")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--part", type=parse_part, metavar="K/N", help="run part K of N")
    which.add_argument("--parallel", type=int, metavar="N", help="run all N parts at once")
    which.add_argument("--list", action="store_true", help="show how --parts N deals the files")
    which.add_argument("--check", action="store_true", help="prove the parts are the discovered suite")
    which.add_argument("--compare", nargs=2, metavar="FILE", help="compare two --outcomes files: a whole run, parts at once, or one part alone")
    which.add_argument("--worker", metavar="SUITE", help=argparse.SUPPRESS)
    which.add_argument("--check-suite", metavar="SUITE", help=argparse.SUPPRESS)
    parser.add_argument("--parts", type=int, default=4, help="with --list: how many parts")
    parser.add_argument("--counts", default="1,2,3,4,5,6,7,8",
                        help="with --check: the part counts to prove, comma separated")
    parser.add_argument("--outcomes", metavar="FILE", help="write every test id's outcome as JSON")
    parser.add_argument("--record-durations", action="store_true",
                        help="write this run's per-file seconds to tests/data/durations.json")
    parser.add_argument("--annotate", action="store_true", help="a GitHub error annotation per failed suite")
    parser.add_argument("--report", help=argparse.SUPPRESS)
    parser.add_argument("-v", "--verbose", action="store_true", help="name every test as it runs")
    parser.add_argument("names", nargs="*", help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    lane = options.lane or default_lane()

    if options.worker:
        return work(options.worker, options.names, options.report, options.verbose)
    if options.check_suite:
        counts = [int(value) for value in options.counts.split(",") if value.strip()]
        print(json.dumps(check_suite(options.check_suite, counts)))
        return 0
    if options.compare:
        return compare(*options.compare)
    if options.check:
        ok, answers = check([int(value) for value in options.counts.split(",") if value.strip()])
        print(json.dumps({"ok": ok, "suites": answers}))
        return 0 if ok else 1
    if options.list:
        seconds = load_durations()
        for index, part in enumerate(deal(lane_files(lane), options.parts, seconds), 1):
            known = sum(seconds.get(name, 0.0) for name in part)
            say("part %d of %d: %d files, %.0f s measured, %d not measured" % (
                index, options.parts, len(part), known, sum(name not in seconds for name in part)))
            for name in part:
                say("  %s%s" % (name, "  %.1f s" % seconds[name] if name in seconds else ""))
        return 0

    started = time.perf_counter()
    if options.parallel:
        merged, parts = run_parallel(lane, options.parallel, verbose=options.verbose)
        count = options.parallel
    else:
        part, count = options.part or (None, 1)
        merged = run_part(lane, part, count, verbose=options.verbose, annotate=options.annotate)
        parts = None
    elapsed = time.perf_counter() - started
    if options.report:
        Path(options.report).write_text(json.dumps(merged), encoding="utf-8")
    if options.outcomes:
        write_outcomes(options.outcomes, lane, count, merged)
    if options.record_durations:
        record_durations(merged["seconds"])
    if not merged["counts"].get("run"):
        merged["ok"] = False
    say(summary(merged, elapsed, parts))
    return 0 if merged["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Run the test suite in parts - one part, or every part at once - with the result one whole run gives.

The suite took 78 to 103 minutes a lane on GitHub's runners in September 2026, and the ko sync's four
round-robin parts took 9, 18, 18 and 32 minutes of it. This deals the test files into N parts, balanced
by how long each file took when it was last measured, and runs them. It is the only place the split is
written: CI's lanes (.github/workflows/test.yml), the release's suite (release.yml) and the ko sync
(sync-ko.yml) all run it, and nothing else decides which file goes where.

    python scripts/test_parts.py                          # the whole suite, as one run
    python scripts/test_parts.py --parallel 8             # the same suite in 8 parts at once
    python scripts/test_parts.py --part 2/8               # only the second of 8 parts
    python scripts/test_parts.py --lane advanced ...      # the advanced edition's lane
    python scripts/test_parts.py --outcomes FILE ...      # every test id's outcome, as JSON
    python scripts/test_parts.py --compare A.json B.json  # two outcome files, test by test
    python scripts/test_parts.py --record-durations ...   # write this run's per-file times
    python scripts/test_parts.py --list --parts 8         # show how 8 parts are dealt
    python scripts/test_parts.py --check                  # prove the parts are the discovered suite

What a part runs is what `python -m unittest discover -s <suite>` runs, restricted to its files: the same
file rule (discover's pattern `test*.py` and its module-name rule), the same loading call - discover
itself, once per file - in the same order, the same runner settings (the warnings filter, verbosity), the
same `sys.path[0]` and `sys.argv`, one fresh interpreter for each suite, as CI has always run them.
`--check` proves the first half: for every suite, the files loaded one by one are exactly the tests
discover finds, in its order, and for every N the parts together are each of them exactly once.

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

The durations are tests/data/durations.json, seconds per file, measured on a whole run; a file with no
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

class Timed(unittest.TestSuite):
    """One file's tests, adding the time they take to run to `clock[name]`."""

    def __init__(self, tests, name, clock):
        super().__init__(tests)
        self.name, self.clock = name, clock

    def run(self, result, debug=False):
        started = time.perf_counter()
        try:
            return super().run(result, debug)
        finally:
            self.clock[self.name] = self.clock.get(self.name, 0.0) + time.perf_counter() - started


class Recorder(unittest.TextTestResult):
    """The text result `unittest` prints, which also keeps each test id's outcome."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

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


def work(suite: str, names: list[str], report: str, verbose: bool) -> int:
    """What `python -m unittest discover -s <suite>` does, for `names` only, and the record of it."""
    # `python -m` puts the working directory first on the path, where running this file put scripts/.
    sys.path[0] = os.getcwd()
    sys.argv = ["python -m unittest", "discover", "-s", suite] + (["-v"] if verbose else [])
    loader = unittest.TestLoader()
    seconds, files = {}, []
    for name in names:
        started = time.perf_counter()
        # discover itself, with the file's own name as the pattern: the same import, the same handling
        # of a file that cannot be imported, the same tests in the same order as a whole discover.
        found = loader.discover(suite, pattern=name)
        seconds[name] = time.perf_counter() - started
        files.append(Timed(found, name, seconds))
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1, resultclass=Recorder,
                                     warnings=None if sys.warnoptions else "default")
    result = runner.run(unittest.TestSuite(files))
    record = {
        "outcomes": result.outcomes,
        "seconds": {"%s/%s" % (suite, name): round(value, 3) for name, value in seconds.items()},
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
    """One suite's files in a fresh interpreter, its output passed through as it comes."""
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


def run_part(lane: str, part: int, count: int, *, verbose: bool = False, annotate: bool = False,
             worker=run_worker) -> dict:
    """Part `part` of `count` of a lane: every suite with files in the part, each in its own worker. Every
    suite runs, and the part has failed if any of them did."""
    mine = set(deal(lane_files(lane), count, load_durations())[part - 1])
    where = "part %d of %d" % (part, count)
    merged = {"outcomes": {}, "seconds": {}, "counts": {}, "ok": True, "suites": []}
    for suite, env in LANES[lane]:
        names = [name for name in suite_files(suite) if "%s/%s" % (suite, name) in mine]
        if not names:
            continue
        say("%s, lane %s: %s, %d of its files" % (where, lane, suite, len(names)))
        code, output, record = worker(suite, names, env, verbose)
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
    deal(lane_files(lane), count, load_durations())      # a count that cannot be dealt is refused here
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
    merged = {"outcomes": {}, "seconds": {}, "counts": {}, "ok": True}
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
    document = {"lane": lane, "parts": parts, "python": sys.version.split()[0],
                "counts": merged["counts"], "outcomes": dict(sorted(merged["outcomes"].items()))}
    Path(path).write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")


def compare(first: str, second: str) -> int:
    a = json.loads(Path(first).read_text(encoding="utf-8"))["outcomes"]
    b = json.loads(Path(second).read_text(encoding="utf-8"))["outcomes"]
    differ = sorted(key for key in set(a) | set(b) if a.get(key) != b.get(key))
    for key in differ:
        say("%s: %s / %s" % (key, a.get(key, "absent"), b.get(key, "absent")))
    tally = {}
    for word in a.values():
        tally[word] = tally.get(word, 0) + 1
    say("%d test ids in %s, %d in %s; %d differ; %s" % (
        len(a), first, len(b), second, len(differ),
        ", ".join("%s %d" % (word, tally[word]) for word in OUTCOMES if word in tally)))
    return 1 if differ else 0


def record_durations(seconds: dict, path: Path = DURATIONS) -> None:
    kept = load_durations(path)
    kept.update({key: round(value, 1) for key, value in seconds.items()})
    present = {key for lane in LANES for key in lane_files(lane)}
    document = {
        "about": "Seconds each test file took (import and run) on the last whole run that recorded them, "
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
    which.add_argument("--compare", nargs=2, metavar="FILE", help="compare two --outcomes files")
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
        part, count = options.part or (1, 1)
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

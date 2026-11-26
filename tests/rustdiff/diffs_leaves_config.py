"""S1.1, car-config: `Paths`, the project root and version, Codex discovery and the log, held to the reference tag.

* PathsDiff - `Paths` for 24 homes (spaces, non-ASCII, a path past 260 characters, UNC-like and verbatim forms, forward
  slashes, dot segments, another letter case, 8.3 names, `~`, relative, from the environment, from the project root), each
  as a home that exists and one that does not: every name `Paths` makes, as `Path(root).expanduser().resolve()` makes it.
* OwnedDiff - what `Paths` owns and what an uninstall may take, over a scratch tree with markers, decoys, rotated logs,
  accounts, a junction, `runtime.json` of each kind; `ensure()` and `claim_home()` on both.
* ConfigDiff - `_project_root`, `read_version`, `version()` (told once), `codex_home`, the candidate engines and
  `discover_codex_exe` over scratch trees.
* LogbookDiff - `render` for every pair the log has words for, `skipped`, `format_local`, `tail`, and the log file itself
  (lines, `\\r\\n`, rotation at a million bytes, the skip lines a watcher before this one wrote).

Scratch homes only: every tree is made under the diff's own temporary folder, one for the reference and one for Rust, the
two named `@` in the answers, and the reference's environment, working folder and project root are set per case.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from rustdiff import core, diffs, reference
from rustdiff.leaves import Leaves, PRELUDE

RECORD: list[str] = []
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Runs under the reference: the cases arrive as JSON on stdin, each with the scratch root already in place.
SETUP = r'''
import logging, os, sys
from pathlib import Path
from codex_auto_resume import config, logbook
SAVED = dict(os.environ)

def scene(env, cwd, call):
    os.environ.clear()
    os.environ.update(env)
    here = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        return call()
    finally:
        os.chdir(here)
        os.environ.clear()
        os.environ.update(SAVED)

def fields(paths):
    names = ["home", "state_dir", "logs_dir", "settings_file", "compat_report_file", "compat_cache_file", "failure_seen_file",
             "status_file", "self_check_file", "split_chains_file", "codex_layout_file", "power_action_file", "once_words_file",
             "edition_left_file", "advanced_dir", "accounts_dir", "log_file", "error_log", "codex_start_log", "entry_script", "icon_file"]
    return {name: str(getattr(paths, name)) for name in names}

def report(paths, extra):
    folders = {}
    for folder in paths.owned_account_dirs():
        folders.setdefault(len(folder.parts), []).append(str(folder))
    return {"fields": fields(paths), "owns_state": paths.owns(paths.state_dir), "owns_logs": paths.owns(paths.logs_dir),
            "owns_home": paths.owns_home(), "state_files": [str(each) for each in paths.owned_state_files()],
            "advanced_files": [str(each) for each in paths.owned_advanced_files()],
            "account_files": [str(each) for each in paths.owned_account_files()],
            "account_dirs": [[depth, sorted(members, key=str.lower)] for depth, members in sorted(folders.items(), reverse=True)],
            "log_files": [str(each) for each in paths.owned_log_files()],
            "confined": [paths.confined(Path(each)) for each in extra]}

def made(home, root, env, cwd):
    def call():
        config.PROJECT_ROOT = Path(root)
        return config.Paths(home)
    return scene(env, cwd, call)

def refused(error):
    return {"config_error": str(error)}

def build(home, root, env, cwd, long):
    return fields(made(home, root, env, cwd))

def paths_report(home, root, env, cwd, long, extra):
    paths = made(home, root, env, cwd)
    return scene(env, cwd, lambda: report(paths, extra))

def mutate(home, root, env, cwd, long, extra):
    paths = made(home, root, env, cwd)
    def call():
        try:
            paths.ensure()
            ensured = None
        except config.ConfigError as error:
            ensured = refused(error)
        claimed = paths.claim_home()
        return {"ensure": ensured, "claim_home": claimed, "after": report(paths, extra)}
    return scene(env, cwd, call)

def read_version(manifest):
    try:
        return config.read_version(Path(manifest))
    except config.ConfigError as error:
        return refused(error)

def version(root):
    config._reported.clear()
    seen = []
    class Catch(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())
    logger = logging.getLogger("codex_auto_resume.config")
    handler = Catch()
    logger.addHandler(handler)
    old = (logger.propagate, logger.level)
    logger.propagate, logger.level = False, logging.DEBUG
    config.PROJECT_ROOT = Path(root)
    try:
        return {"version": config.version(), "warned": seen}
    finally:
        logger.removeHandler(handler)
        logger.propagate, logger.level = old

def project_root(module, levels, package):
    return str(config._project_root(Path(module), levels, package))

def codex_home(env, cwd, long):
    return str(scene(env, cwd, lambda: config.codex_home()))

def bin_dir(env):
    try:
        return str(scene(env, None, lambda: config.codex_bin_dir()))
    except config.ConfigError as error:
        return refused(error)

def candidates(env, cwd, long):
    try:
        return [str(each) for each in scene(env, cwd, lambda: config.candidate_codex_exes())]
    except config.ConfigError as error:
        return refused(error)

def tail(path, count):
    return logbook.tail(Path(path), count)

def log_digest(file):
    import hashlib
    out = {}
    for each in sorted(Path(file).parent.iterdir()):
        data = each.read_bytes()
        out[each.name] = [len(data), hashlib.sha256(data).hexdigest()]
    return out

def log_write(file, mark, codes, events, now0, offset, step):
    import time
    clock = [float(now0)]
    real = time.time_ns
    time.time_ns = lambda: int(clock[0] * 1e9)
    try:
        logger = logbook.setup_logging(Path(file), mark=mark)
        log = logbook.EngineLog(logger)
        for event in events:
            if event[0] == "info":
                logger.info(event[1])
            else:
                log(event[0], event[1], tuple(event[2]) if event[1] == logbook.SKIPPED else event[2])
            clock[0] += step
        for handler in list(logger.handlers):
            handler.close()
    finally:
        time.time_ns = real
    return log_digest(file)

def discover(explicit, env, cwd, rules, running, ask, ask_none, long):
    def compatible(path):
        reason = rules.get(Path(path).parent.name)
        if reason is not None:
            raise RuntimeError(reason)
    def asked():
        if isinstance(running, str):
            raise OSError("no")
        return [Path(each) for each in running]
    try:
        return str(scene(env, cwd, lambda: config.discover_codex_exe(explicit, compatible, None if running is None else asked, ask, ask_none)))
    except config.ConfigError as error:
        return refused(error)
'''

OPS = r'''
ops = {"paths.build": build, "paths.report": paths_report, "paths.mutate": mutate, "config.read_version": read_version,
       "config.version": version, "config.project_root": project_root, "config.codex_home": codex_home,
       "config.codex_bin_dir": bin_dir, "config.candidates": candidates, "config.discover": discover,
       "logbook.tail": tail, "logbook.write": log_write}
cases = json.load(sys.stdin)
finish(cases, ops)
'''


def where(a, b, path="") -> str:
    """The first place two answers differ, as a path into them."""
    if type(a) is not type(b):
        return "%s: %r != %r" % (path or "/", a, b)
    if isinstance(a, dict):
        for key in a:
            if key not in b:
                return "%s/%s only in the reference" % (path, key)
            found = where(a[key], b[key], "%s/%s" % (path, key))
            if found:
                return found
        return "%s: keys only in Rust %s" % (path, [key for key in b if key not in a]) if set(b) - set(a) else ""
    if isinstance(a, list):
        for index, (one, other) in enumerate(zip(a, b)):
            found = where(one, other, "%s[%d]" % (path, index))
            if found:
                return found
        return "%s: %d items against %d (%r / %r)" % (path, len(a), len(b), a[len(b):][:3], b[len(a):][:3]) if len(a) != len(b) else ""
    return "" if a == b else "%s: %r != %r" % (path or "/", a, b)


def replaced(value, old: str, new: str):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [replaced(each, old, new) for each in value]
    if isinstance(value, dict):
        return {replaced(key, old, new): replaced(each, old, new) for key, each in value.items()}
    return value


class ConfigBase(Leaves):
    def roots(self, name: str) -> tuple[Path, Path]:
        """Two folders alike in name length, one for each side, and each side's ENV for the cases."""
        ours, theirs = self.profile("ref-" + name), self.profile("rust-" + name)
        return ours, theirs

    def pair(self, label: str, template: list, build=None, tree=None, ref_script_extra: str = "") -> list:
        """Run `template` (a list of cases whose strings carry `@` for the scratch root) through both sides; each side's
        root is made by `tree(root)` first. Returns (cases, expected) once the answers are equal with the root as `@`."""
        ours, theirs = self.roots(label)
        for root in (ours, theirs):
            (root / "tree").mkdir()
            if tree is not None:
                tree(root / "tree")
        real = {root: Path(os.path.realpath(root)) for root in (ours, theirs)}
        reference_cases = replaced(template, "@", str(ours / "tree"))
        rust_cases = replaced(template, "@", str(theirs / "tree"))
        made = reference.run(PRELUDE + SETUP + ref_script_extra + OPS, profile=ours,
                             stdin=json.dumps(reference_cases, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(made.returncode, 0, made.stderr[-3000:].decode("utf-8", "replace"))
        expected = json.loads(made.stdout.decode("utf-8"))["results"]
        with core.Harness(reference.scratch_environment(theirs)) as harness:
            _number, line = harness.call("leaves.batch", cases=rust_cases)
        actual = json.loads(line.decode("utf-8"))["reply"]["value"]
        self.assertEqual(len(actual), len(expected))
        for index, (want, got) in enumerate(zip(expected, actual)):
            want = replaced(want, str(real[ours] / "tree"), "@")
            want = replaced(want, str(ours / "tree"), "@")
            got = replaced(got, str(real[theirs] / "tree"), "@")
            got = replaced(got, str(theirs / "tree"), "@")
            # a path that climbs above the tree names the side's own folder: one name for both
            want, got = replaced(want, str(real[ours]), "@@"), replaced(got, str(real[theirs]), "@@")
            if json.dumps(want, ensure_ascii=False, sort_keys=False) != json.dumps(got, ensure_ascii=False, sort_keys=False):
                self.fail("%s: case %d differs at %s - case %s" % (
                    label, index, where(want, got), json.dumps(template[index], ensure_ascii=False)[:500]))
        return expected


ENV = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"), "USERPROFILE": "@\\profile", "USERNAME": "ExampleUser",
       "LOCALAPPDATA": "@\\local"}


class PathsDiff(ConfigBase):
    def long_paths(self) -> bool:
        """Whether this system takes a path past 260 characters as it is: what the reference's realpath says of one."""
        probe = self.profile("probe")
        deep = probe
        for index in range(6):
            deep = deep / ("long-folder-name-%02d-" % index + "x" * 45)
        os.makedirs("\\\\?\\" + str(deep))
        script = ("import os, sys, json\nsys.stdout.write(json.dumps(os.path.realpath(sys.argv[1]).startswith(chr(92) * 2 + '?' + chr(92))))")
        done = reference.run(script, str(deep), profile=probe)
        self.assertEqual(done.returncode, 0, done.stderr[-1000:])
        return not json.loads(done.stdout)

    def test_twenty_four_homes(self):
        long_paths = self.long_paths()
        far = "@/" + "/".join("long-folder-name-%02d-" % index + "y" * 45 for index in range(6))
        homes = [
            "@/home", "@/my home/dir with spaces", "@/\ud64f/\uac00\ub098\ub2e4 \u00e9\u4e2d", "@/a/./b/../c", "@//double//slash/", "@/HOME",
            "@/home/", "@\\back\\slash", "@/mixed\\slashes/x", "\\\\?\\@\\verbatim", "\\\\127.0.0.1\\nosuchshare\\home",
            "\\\\?\\UNC\\127.0.0.1\\nosuchshare\\home", "//127.0.0.1/nosuchshare/home", far, "rel\\dir", "..\\up", ".", "~\\under profile", "~",
            "C:\\PROGRA~1\\x", "C:\\Windows\\..\\Windows\\System32", "C:\\", "@/trailing dot./x", "@/nul", "d:relative", "\\rooted",
        ]
        template = []
        for home in homes:
            template.append(["paths.build", home, "@/root", ENV, "@/cwd", long_paths])
        for home in ["@/exists/home", "@/exists/my home", "@/exists/\uac00\ub098\ub2e4", "@/exists/LONGCASE", "@/exists/./x/../y"]:
            template.append(["paths.build", home, "@/root", ENV, "@/cwd", long_paths])
        template += [["paths.build", None, "@/root", ENV, "@/cwd", long_paths], ["paths.build", "", "@/root", ENV, "@/cwd", long_paths],
                     ["paths.build", None, "@/root", dict(ENV, CODEX_AUTO_RESUME_HOME="@/from env"), "@/cwd", long_paths],
                     ["paths.build", "@/given", "@/root", dict(ENV, CODEX_AUTO_RESUME_HOME="@/from env"), "@/cwd", long_paths],
                     ["paths.build", "", "@/root", dict(ENV, CODEX_AUTO_RESUME_HOME="~\\envhome"), "@/cwd", long_paths],
                     ["paths.build", None, "@/inst/app", ENV, "@/cwd", long_paths], ["paths.build", "~other", "@/root", ENV, "@/cwd", long_paths],
                     ["paths.build", "~ExampleUser\\x", "@/root", ENV, "@/cwd", long_paths],
                     ["paths.build", "~", "@/root", {"SYSTEMROOT": ENV["SYSTEMROOT"]}, "@/cwd", long_paths],
                     ["paths.build", "~", "@/root", {"SYSTEMROOT": ENV["SYSTEMROOT"], "HOMEDRIVE": "C:", "HOMEPATH": "\\Users\\h"}, "@/cwd", long_paths],
                     ["paths.installed_home_like", "@/inst/app"]]
        template = [case for case in template if case[0] != "paths.installed_home_like"]

        def tree(root: Path):
            for folder in ("exists/home", "exists/my home", "exists/\uac00\ub098\ub2e4", "exists/LONGCASE", "exists/y", "cwd/rel/dir", "home",
                           "my home/dir with spaces", "a/c", "double/slash", "profile", "local", "inst/app", "root", "from env", "given", "back/slash",
                           "mixed/slashes/x", "verbatim", "\ud64f/\uac00\ub098\ub2e4 \u00e9\u4e2d", "profile/under profile", "profile/envhome"):
                (root / folder).mkdir(parents=True, exist_ok=True)
            os.makedirs("\\\\?\\" + str(root / "/".join("long-folder-name-%02d-" % index + "y" * 45 for index in range(6))), exist_ok=True)
        expected = self.pair("homes", template, tree=tree)
        shown = [result["ok"]["home"] for result in expected if "ok" in result]
        self.assertGreaterEqual(len(shown), 20)
        RECORD.append("Paths: %d homes (%d resolved, %d refused alike; spaces, non-ASCII, %d-character, UNC-like, verbatim, dot "
                      "segments, letter case, 8.3, ~, relative, from the environment) give every name equal to the tag's; long paths %s"
                      % (len(template), len(shown), len(expected) - len(shown), len(far), "stripped" if long_paths else "keep their prefix"))


class OwnedDiff(ConfigBase):
    def test_what_is_owned(self):
        def tree(root: Path):
            marker = ".owned-by-codex-auto-resume"
            text = "Created by codex-auto-resume. Deleting this file makes `uninstall` skip this directory.\n"
            for home, parts in {
                "empty": {}, "marked": {marker: text, "config/" + marker: text, "logs/" + marker: text},
                "only config": {"config/" + marker: text}, "unmarked": {"config/settings.json": "{}", "logs/auto-resume.log": "x"},
                # config/ a file: ensure()'s mkdir raises FileExistsError and logs/ is never made (Integration 8)
                "config a file": {"config": "x"},
            }.items():
                (root / home).mkdir(parents=True)
                for name, body in parts.items():
                    target = root / home / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(body, encoding="utf-8")
            full = root / "full"
            for name in ("state.sqlite", "state.sqlite-wal", "settings.json", "SETTINGS.tmp", "Settings.1.TMP", "settings.unreadable-3.json", "settings.unreadable-.JSON",
                         "status.9.tmp", "status.tmp", "stray.txt", "compat-cache.json", "selfcheck.json", "selfcheck.a.tmp", "edition-left.x.tmp"):
                (full / "config").mkdir(parents=True, exist_ok=True)
                (full / "config" / name).write_text("x", encoding="utf-8")
            for place in ("config", "logs", "config/advanced", "accounts", "accounts/a", "accounts/a/b", "accounts/c"):
                (full / place).mkdir(parents=True, exist_ok=True)
                (full / place / marker).write_text(text, encoding="utf-8")
            (full / marker).write_text(text, encoding="utf-8")
            for name in ("adv1.json", "ADV2.db", "sub"):
                (full / "config/advanced" / name).parent.mkdir(exist_ok=True)
            (full / "config/advanced/adv1.json").write_text("1", encoding="utf-8")
            (full / "config/advanced/ADV2.db").write_text("2", encoding="utf-8")
            (full / "config/advanced/sub").mkdir(exist_ok=True)
            (full / "config/advanced/sub/deep.txt").write_text("3", encoding="utf-8")
            for name in ("auto-resume.log", "auto-resume.log.1", "auto-resume.log.12", "errors.log", "errors.log.3", "errors.log.x", "errors.log.",
                         "Auto-Resume.log", "other.log", "auto-resume.log.\u0663", "codex-start.log", "auto-resume.log.1.1"):
                (full / "logs" / name).write_text("x", encoding="utf-8")
            for name in ("accounts/one.json", "accounts/a/two.json", "accounts/a/b/three.json", "accounts/c/four.json", "accounts/a/b/Five.json"):
                (full / name).write_text("x", encoding="utf-8")
            # a junction out of the home, and one that stays inside it
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("keep", encoding="utf-8")
            (outside / marker).write_text(text, encoding="utf-8")
            for home in ("junction", "junction in"):
                (root / home).mkdir()
            (root / "junction" / "marker-holder").mkdir()
            (root / "junction" / marker).write_text(text, encoding="utf-8")
            subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "junction" / "config"), str(outside)], capture_output=True,
                           creationflags=NO_WINDOW, check=True)
            subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "junction" / "logs"), str(root / "junction" / "marker-holder")],
                           capture_output=True, creationflags=NO_WINDOW, check=True)
            (root / "junction in" / "target").mkdir()
            (root / "junction in" / "target" / marker).write_text(text, encoding="utf-8")
            subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "junction in" / "config"), str(root / "junction in" / "target")],
                           capture_output=True, creationflags=NO_WINDOW, check=True)
            for name, home in {"record-ok": root / "record-ok", "record-other": root / "elsewhere", "record-case": root / "RECORD-CASE",
                               "record-empty": "", "record-number": 5, "record-list": [1]}.items():
                (root / name).mkdir()
                document = home if name == "record-list" else {"home": str(home) if isinstance(home, Path) else home}
                (root / name / "runtime.json").write_text(json.dumps(document), encoding="utf-8")
            (root / "record-bad").mkdir()
            (root / "record-bad" / "runtime.json").write_text("{nope", encoding="utf-8")
            (root / "record-bytes").mkdir()
            (root / "record-bytes" / "runtime.json").write_bytes(b"\xff\xfe\x00")
            (root / "record-bom").mkdir()
            (root / "record-bom" / "runtime.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"home": str(root / "record-bom")}).encode())
        extra = ["@/full/config/settings.json", "@/full/config/../outside", "@/outside", "@/junction/config", "@/junction/config/secret.txt",
                 "@/full", "@/FULL/Config", "@/missing", "@/full/config/advanced/sub"]
        template = []
        for home in ("empty", "marked", "only config", "unmarked", "full", "junction", "junction in", "record-ok", "record-other",
                     "record-list", "record-bad", "record-empty", "record-number", "record-case", "record-bytes", "record-bom", "missing"):
            template.append(["paths.report", "@/" + home, "@/root", ENV, "@/", False, extra])
        # `junction` has config/ a junction out of the home (ensure() refuses it, both ways) and `junction in` has config/ a
        # junction to a folder inside the home: `Path.is_symlink()` is false for it, so the tag's ensure() lets it pass, and
        # so does car-config's, whose link probe is car-platform's (the one reparse-tag reader, D3; the harness wires it in).
        for home in ("empty", "marked", "full", "junction", "junction in", "config a file"):
            template.append(["paths.mutate", "@/" + home, "@/root", ENV, "@/", False, extra])
        # a file of the home that the mutation made is then listed: so is what it did NOT make
        self.pair("owned", template, tree=tree)
        # The junction inside the home, on its own and spelled out: ensure() passes (None, not a ConfigError) in the tag's and in
        # car-config's, and what it left behind is the same; the one probe is car-platform's `is_symlink`, a junction is not a link.
        ours, theirs = self.roots("junction-in")
        for root in (ours, theirs):
            tree(root)
        with core.Harness(reference.scratch_environment(theirs)) as harness:
            _number, line = harness.call("leaves.batch", cases=[["paths.mutate", str(theirs / "junction in"), str(theirs / "root"),
                                                                 dict(ENV, USERPROFILE=str(theirs)), str(theirs), False, []]])
        answer = json.loads(line.decode("utf-8"))["reply"]["value"][0]["ok"]
        self.assertIsNone(answer["ensure"], "a junction inside the home passes ensure() as the tag lets it")
        self.assertTrue(answer["claim_home"])
        RECORD.append("Paths ownership: owns, owns_home (marker, config's marker, runtime.json of seven kinds), the owned state, advanced, "
                      "account and log files, the account folders by depth, confined (a junction out of the home, one inside it), and "
                      "ensure() and claim_home() on 6 scratch homes (one whose config/ is a file: FileExistsError, no logs/) equal the tag's, a junction inside the home passing ensure() as the tag's "
                      "Path.is_symlink() lets it (car-platform's one link probe)")

"""gh, as the compatibility report runs it (car-adv `report/github.rs`), held to the tag's `report/github.py`.

Nothing here starts gh, finds the real one or reaches GitHub. The reference is run with the tag's own stand-in for gh
(`advanced/tests/ghfake.py`: `FakeGh`, which answers as GitHub would for one person, from a few facts a test sets), and a
recorder around it writes down every call - the argument list, the environment (as a digest), the folder, the bytes on
standard input, the timeout and the creation flags - and what it was answered. The Rust side runs the same program of
`inspect` and `publish` steps over a runner that answers that script in order, writing down the calls it is made; the
answers (what each step found or was refused with, what was written, what it slept) and the calls must equal the tag's.

* InspectDiff - every question a check asks, over the people and states GitHub can be in: no gh, signed out, another
  login, the same login in other letters (the full Unicode case folding of a name and its ASCII lookalikes), a door that
  is shut, a file filed, a pull request open (and of exactly this file), a fork named otherwise, a base that is no SHA,
  pages of pull requests of every shape (empty, adjacent, not JSON, not lists, past recursion), every call failing or
  hanging, and a runner that raises.
* PublishDiff - every write in its order: a new fork waited for, one kept, a branch made or reset, the file on standard
  input, the pull request, a stop between any two writes (by a refusal, by the flow's own stop, by any other error), a
  pull request gh will not repeat, an address it answers with in odd ways.
* PureDiff - `blob_sha`, `destination`, `spelling`, `title`, `body`, base64, the environment gh starts with, the pull
  request address matcher, and `find_gh` over folders on a PATH of every kind.

The job object gh runs in (KILL_ON_JOB_CLOSE) is not here: it is S7.3b's car-platform `job.rs`, and the tag's tests of it
start real processes (`JobTests`), which no seat does.
"""
from __future__ import annotations

import unittest

from rustdiff import advreport

RECORD = []

PRELUDE = r'''
import hashlib, os, subprocess
from ghfake import FakeGh, pull, LOGIN, MAIN, NOT_FOUND
from codex_auto_resume_advanced.report import flow, github

VERSION = "codex-cli 0.158.0"
REPORT = {"codex_version": VERSION, "reporter": {"tool_version": "0.6.14-beta"}}
RAW = '{"format": "a report"}\n'
TARGET = "docs/evidence/community/%s/codex-cli-0.158.0.json" % LOGIN
BRANCH = "compat-report/codex-cli-0.158.0"
FORK = "%s/codex-auto-resume-windows" % LOGIN
EXE = r"C:\Tools\gh\gh.exe"
CWD = SCRATCH

def digest(env):
    return hashlib.sha256(json.dumps(sorted(env.items())).encode("utf-8")).hexdigest()

class Recorder:
    """The runner the tag is given: FakeGh's answers, every call and answer written down."""
    def __init__(self, fake, raises=None):
        self.fake, self.script, self.raises = fake, [], dict(raises or {})

    def __call__(self, argv, *, env, cwd, stdin, timeout, creationflags):
        call = {"argv": list(argv), "env": digest(env), "cwd": cwd,
                "stdin": None if stdin is None else stdin.decode("ascii"), "timeout": timeout, "flags": creationflags}
        index = len(self.script)
        try:
            if index in self.raises:
                raise self.raises[index]("boom")
            answer = self.fake(argv, env=env, cwd=cwd, stdin=stdin, timeout=timeout, creationflags=creationflags)
        except github.GhTimeout:
            self.script.append({"call": call, "answer": {"raise": "GhTimeout"}})
            raise
        except Exception as error:
            self.script.append({"call": call, "answer": {"raise": type(error).__name__}})
            raise
        self.script.append({"call": call, "answer": [answer[0], answer[1], answer[2]]})
        return answer

def error_of(error):
    found = {"error": type(error).__name__}
    code = getattr(error, "code", None)
    if code is not None and not isinstance(code, int):
        found["code"] = str(code)
    return found

def ready_dict(found):
    return {"exe": found.exe, "who": found.who, "login": found.login, "fork": found.fork, "branch": found.branch,
            "target": found.target, "base": found.base, "has_fork": found.has_fork, "has_branch": found.has_branch,
            "cwd": found.cwd, "written": list(found.written), "writes": found.writes()}

def run_program(program, runner, sleeps, fake):
    out, found, last = [], None, None
    for step in program:
        kind = step[0]
        if kind == "fake":
            for name, value in step[1].items():
                setattr(fake, name, value)
        elif kind == "inspect":
            raw, report, login, exe, cwd = step[1:]
            found = None
            try:
                got = github.inspect(raw.encode("ascii"), report, login, exe=exe, cwd=cwd, runner=runner, sleep=sleeps.append)
            except Exception as error:
                out.append(error_of(error))
                continue
            if isinstance(got, github.Ready):
                found, last = got, (raw, report)
                out.append({"ready": ready_dict(got)})
            elif isinstance(got, github.Web):
                out.append({"web": {"why": str(got.why), "who": got.who}})
            else:
                out.append({"sent": got.url})
        else:
            options = step[1] or {}
            stop = options.get("stop")
            asked = []

            def before():
                asked.append(1)
                if stop and len(asked) > stop["after"]:
                    word = stop.get("with")
                    if word == "stopped":
                        raise flow.Stopped("paused")
                    if word == "error":
                        raise RuntimeError("boom")
                    raise github.ReportRefused("not_on")
            if found is None:
                out.append({"skipped": "inspect found nothing to publish"})
                continue
            raw, report = last
            try:
                url = github.publish(found, raw.encode("ascii"), report, before=before, runner=runner, sleep=sleeps.append)
                out.append({"url": url, "written": list(found.written)})
            except Exception as error:
                out.append(dict(error_of(error), written=list(found.written)))
    return out

def gh_case(program, fake=None, raises=None, **given):
    fake = fake if fake is not None else FakeGh(**given)
    recorder, sleeps = Recorder(fake, raises), []
    try:
        result = {"ok": {"steps": run_program(program, recorder, sleeps, fake),
                         "calls": [entry["call"] for entry in recorder.script], "sleeps": [float(each) for each in sleeps]}}
    except Exception as error:
        result = error_of(error)
    CASES.append(["github.run", [step for step in program if step[0] != "fake"], [{"answer": entry["answer"]} for entry in recorder.script]])
    RESULTS.append(result)

def inspect_step(raw=RAW, report=REPORT, login=LOGIN, exe=EXE, cwd=CWD):
    return ["inspect", raw, report, login, exe, cwd]

def check(**given):
    gh_case([inspect_step()], **given)

def sent(**given):
    gh_case([inspect_step(), ["publish", None]], **given)
'''

INSPECT_SCRIPT = PRELUDE + r'''
from ghfake import FakeGh
check()
check(fork="fork", branch=True)
check(fork="fork")
gh_case([inspect_step(exe=None)])
gh_case([inspect_step(exe=None, report={"codex_version": "codex-cli 0.1.0-alpha.2", "reporter": {}}, login="a-b")])
check(signed_in=False)
check(who="SomeoneElse")
check(who="Some One")
check(who="x" * 40)
check(who="")
check(who="ExampleUser2")
for who in ("exampleuser", "EXAMPLEUSER", "ExampleUsEr", "ExampleUser "):
    check(who=who)
for login, who in (("sam", "\u017fam"), ("Sam", "\u017fam"), ("kay", "\u212Aay"), ("mass", "ma\u00df"), ("mass", "MA\u1e9e"), ("ffa", "\ufb00a"),
                   ("fia", "\ufb01a"), ("ffia", "\ufb03a"), ("sta", "\ufb05a"), ("sta", "\ufb06a"), ("flA", "\ufb02A"), ("a", "\u0430"), ("i", "\u0130"),
                   ("k", "K"), ("ss", "\u00df"), ("a-b", "A-\u017f"), ("sam", "\uff53am"), ("sam", "Sam"), ("sam", "SAM"), ("s", "\u017f"), ("sam", "sam")):
    gh_case([inspect_step(login=login)], who=who)
# the refusals GitHub's own answers make, each before any write
for given in (dict(open_door=False), dict(filed=True), dict(pulls=[pull(ref="compat-report/codex-cli-0.157.0")]), dict(fork="other"),
              dict(base="not a sha"), dict(base=MAIN.upper()), dict(base=MAIN + "0"), dict(base=MAIN[:-1]), dict(base=""), dict(base="\u0663" * 40),
              dict(fail=("repos/%s/pulls" % github.REPOSITORY,)), dict(hang=("user",)), dict(hang=("auth",)), dict(hang=("pulls?",)),
              dict(hang=("heads/main",)), dict(fail=("git/ref/heads/main",)), dict(fail=("user",)), dict(fail=("contents/docs/evidence",)),
              dict(fail=("contents/" + TARGET,)), dict(fork="fork", fail=("repos/%s" % FORK,)), dict(fork="fork", fail=("git/ref/heads/compat",)),
              dict(fork="fork", branch=True, fail=("git/ref/heads/compat",))):
    check(**given)
# another person's pull requests are none of this login's; the list as GitHub can make it
check(pulls=[pull(login="SomeoneElse"), pull(owner="SomeoneElse"), pull(ref="patch-1")])
check(pulls=[None, 5, {"head": 1}, {"user": {"login": LOGIN}, "head": {"ref": 5}}, {"user": 4}, {"html_url": 5}, "text", [1]])
check(pulls=[{"user": {"login": LOGIN}, "head": {"ref": BRANCH, "repo": {"owner": {"login": LOGIN}}}, "html_url": 5}])
check(pulls=[{"user": {"login": LOGIN}, "head": {"ref": BRANCH, "repo": {"owner": {"login": LOGIN}}}}])
open_one = pull(ref=BRANCH)
for given in (dict(fork="fork", branch=True, pulls=[open_one], contents={(TARGET, BRANCH): github.blob_sha(RAW.encode("ascii"))}),
              dict(fork="fork", branch=True, pulls=[open_one], contents={(TARGET, BRANCH): github.blob_sha(b"other bytes\n")}),
              dict(fork="fork", branch=True, pulls=[open_one]),
              dict(fork="fork", branch=True, pulls=[pull(ref=BRANCH, number=1234567890)], contents={(TARGET, BRANCH): github.blob_sha(RAW.encode("ascii"))}),
              dict(fork="fork", branch=True, pulls=[pull(ref=BRANCH, number=123456789)], contents={(TARGET, BRANCH): github.blob_sha(RAW.encode("ascii"))}),
              dict(fork="fork", branch=True, pulls=[pull(ref=BRANCH, number=0)], contents={(TARGET, BRANCH): github.blob_sha(RAW.encode("ascii"))}),
              dict(fork="fork", branch=True, pulls=[dict(open_one, html_url="https://example.com/pull/1")], contents={(TARGET, BRANCH): github.blob_sha(RAW.encode("ascii"))}),
              dict(fork="fork", branch=True, pulls=[dict(open_one, html_url="https://github.com/%s/pull/\u0661\u0662" % github.REPOSITORY)], contents={(TARGET, BRANCH): github.blob_sha(RAW.encode("ascii"))}),
              dict(fork="fork", branch=True, pulls=[dict(open_one, html_url="x https://github.com/%s/pull/3" % github.REPOSITORY)], contents={(TARGET, BRANCH): github.blob_sha(RAW.encode("ascii"))}),
              dict(fork="fork", branch=True, pulls=[open_one, pull(ref=BRANCH, number=8)], contents={(TARGET, BRANCH): github.blob_sha(RAW.encode("ascii"))}),
              dict(fork="fork", branch=True, pulls=[pull(ref=BRANCH + "x")], contents={(TARGET, BRANCH + "x"): github.blob_sha(RAW.encode("ascii"))}),
              dict(fork="fork", branch=True, pulls=[open_one], contents={(TARGET, BRANCH): "\n"})):
    check(**given)

def endpoint(name, method="GET"):
    def matches(words):
        return words[:1] == ["api"] and "-X" in words and words[words.index("-X") + 1] == method and words[words.index("-X") + 2] == name
    return matches

def mentions(part):
    return lambda words: part in " ".join(words)

class Odd(FakeGh):
    """A FakeGh that answers one question as the field says, whatever GitHub would."""
    def __init__(self, odd, **given):
        super().__init__(**given)
        self.odd = odd

    def answer(self, words):
        for asked, answer in self.odd:
            if asked(words):
                return answer
        return super().answer(words)

for pages in ("", "[]", "[] []", "[][]", "[]\n\u00a0[]", "{}", "[1] x", "not json", "[NaN]", "[1,]", " \n ", "[" * 3000, "[]" + " " * 5 + "[1]",
              json.dumps([pull(ref="patch-1")]), json.dumps([pull(ref=BRANCH)]) + json.dumps([pull(ref=BRANCH, number=9)]),
              "null", "7", '"s"', "[1] [2] {}"):
    gh_case([inspect_step()], fake=Odd([(mentions("pulls?"), (0, pages, ""))]))
for info in ("", "{}", "[]", "not json", '{"fork": false}', '{"fork": true}', '{"fork": true, "parent": {"full_name": "someone/else"}}',
             '{"fork": 1, "parent": {"full_name": "%s"}}' % github.REPOSITORY, '{"fork": "yes", "parent": 5}', '{"fork": true, "parent": []}',
             "[" * 3000, '{"fork": [], "parent": {"full_name": "%s"}}' % github.REPOSITORY):
    gh_case([inspect_step()], fake=Odd([(endpoint("repos/%s" % FORK), (0, info, ""))], fork="fork"))
gh_case([inspect_step()], fake=Odd([(endpoint("repos/%s" % FORK), (1, "", "gh: Not Found (HTTP 404)"))], fork="fork"))
gh_case([inspect_step()], fake=Odd([(endpoint("repos/%s" % FORK), (1, '{"message": "Not Found", "status":"404"}', ""))], fork="fork"))
gh_case([inspect_step()], fake=Odd([(endpoint("repos/%s" % FORK), (1, '{"message": "Not Found", "status" : "404" }', ""))], fork="fork"))
gh_case([inspect_step()], fake=Odd([(endpoint("repos/%s" % FORK), (1, '{"status":"4\u00a004"}', ""))], fork="fork"))
gh_case([inspect_step()], fake=Odd([(endpoint("repos/%s" % FORK), (2, "", "(HTTP 404)"))], fork="fork"))
gh_case([inspect_step()], fake=Odd([(endpoint("repos/%s" % FORK), (0, "", "(HTTP 404)"))], fork="fork"))
gh_case([inspect_step()], fake=Odd([(endpoint("repos/%s/git/ref/heads/main" % github.REPOSITORY), (0, "\n" + MAIN + "\n", ""))]))
gh_case([inspect_step()], fake=Odd([(endpoint("user"), (0, " ExampleUser", ""))]))
# a runner that raises, at every call of a check
for index in range(8):
    for error in (OSError, ValueError, subprocess.SubprocessError, RuntimeError, KeyError):
        gh_case([inspect_step()], raises={index: error}, fork="fork", branch=True)
# other versions and logins
for report in ({"codex_version": "codex-cli 0.158.0-alpha.2", "reporter": {}}, {"codex_version": "x", "reporter": {}}, {"codex_version": 5}, {"codex_version": None},
               {}, {"codex_version": "codex-cli \u00e9.1.0", "reporter": {}}, {"codex_version": "codex-cli 0.1.0", "reporter": {"tool_version": "9"}}):
    gh_case([inspect_step(report=report)])
for login in ("a", "x-y-z", "ExampleUser"):
    gh_case([inspect_step(login=login)], who=login)
finish()
'''

PUBLISH_SCRIPT = PRELUDE + r'''
RAWB = RAW.encode("ascii")

def program(*options, **given):
    steps = [inspect_step(), ["publish", options[0] if options else None]]
    gh_case(steps, **given)

program()
program(fork="fork", branch=True)
program(fork="fork")
program(branch=True)
for after in range(0, 5):
    for how in ("refused", "stopped", "error"):
        program({"stop": {"after": after, "with": how}})
        program({"stop": {"after": after, "with": how}}, fork="fork", branch=True)
program(made_fork="ExampleUser/codex-auto-resume-windows-1")
program(made_fork="")
for waits in (0, 1, 5, github.FORK_WAITS - 1, github.FORK_WAITS, github.FORK_WAITS + 3):
    program(fork_ready_after=waits)
program(hang=("forks",))
program(hang=("git/refs",))
program(hang=("contents/" + TARGET,))
program(hang=("pr",))
program(fail=("forks",))
program(fail=("git/refs",))
program(fail=("contents/" + TARGET,))
program(fork="fork", branch=True, fail=("git/refs/heads/compat-report",))
program(fork="fork", branch=True, fail=("git/ref/heads",))
for answer in ((1, "", "it failed"), (1, "", "a pull request already exists"), (0, "", ""), (0, "no address here", ""), (0, "see " + "https://github.com/%s/pull/12345678901" % github.REPOSITORY + " ok", ""),
               (0, "x https://github.com/%s/pull/ y https://github.com/%s/pull/7" % (github.REPOSITORY, github.REPOSITORY), ""),
               (0, "https://github.com/%s/pull/\u0663\u0664" % github.REPOSITORY, ""), (0, "https://github.com/%s/PULL/3" % github.REPOSITORY, ""),
               (2, "https://github.com/%s/pull/3" % github.REPOSITORY, ""), (0, "  https://github.com/%s/pull/42\n" % github.REPOSITORY, "")):
    program(pr_answer=answer)
    program(pr_answer=answer, fork="fork", branch=True)
# a pull request gh refuses to repeat is read from what is open: the list read again, after the writes
gh_case([inspect_step(), ["fake", {"pr_answer": (1, "", "a pull request already exists"), "pulls": [pull(ref=BRANCH, number=9)],
                                   "contents": {(TARGET, BRANCH): github.blob_sha(RAWB)}}], ["publish", None]], fork="fork", branch=True)
gh_case([inspect_step(), ["fake", {"pr_answer": (1, "", "a pull request already exists"), "pulls": [pull(ref=BRANCH, number=9)]}], ["publish", None]],
        fork="fork", branch=True)
gh_case([inspect_step(), ["fake", {"pr_answer": (1, "", "x"), "pulls": [pull(ref=BRANCH, number=9)],
                                   "contents": {(TARGET, BRANCH): github.blob_sha(b"other")}}], ["publish", None]], fork="fork", branch=True)
# the file on standard input, as it goes: a report with characters past ASCII in its name and a long one
for report in ({"codex_version": "codex-cli 0.158.0-alpha.2", "reporter": {"tool_version": "0.6.14-beta"}},
               {"codex_version": "codex-cli 0.158.0", "reporter": {"tool_version": "0.6.14-beta \u00e9\u4e2d"}},
               {"codex_version": "codex-cli \u00e9\u4e2d \U0001F600", "reporter": {"tool_version": "1"}}):
    for raw in (RAW, "x", "xx", "xxx", "a" * 1000, '{"k": "v"}\n' * 40):
        gh_case([inspect_step(raw=raw, report=report), ["publish", None]], fork="fork")
# every fork wait the tag is given, and the sleeps it makes
program(fork_ready_after=3)
finish()
'''

PURE_SCRIPT = PRELUDE + r'''
import shutil
for raw in ("", "hello\n", "x" * 1000, "é"):
    case("github.blob_sha", raw, ref=lambda raw=raw: github.blob_sha(raw.encode("utf-8")))
case("github.blob_sha", "hello\n", ref=lambda: github.blob_sha(b"hello\n"))
for version in ("codex-cli 0.158.0", "codex-cli 0.158.0-alpha.2.3", "", "x", 5, None, "codex-cli \u00e9", "codex-cli 0.1.0\n"):
    for login in ("ExampleUser", "a-b", 5, None):
        case("github.destination", version, login, ref=lambda version=version, login=login: list(github.destination(version, login)))
for login, who in (("ExampleUser", "exampleuser"), ("ExampleUser", "ExampleUser"), ("ExampleUser", ""), ("ExampleUser", "other"), ("sam", "\u017fam")):
    case("github.spelling", login, who, ref=lambda login=login, who=who: github.spelling(login, who))
for report in ({"codex_version": "codex-cli 0.158.0"}, {"codex_version": 5}, {"codex_version": "\u00e9"}):
    case("github.title", report, "ExampleUser", ref=lambda report=report: github.title(report, "ExampleUser"))
for version in ("0.6.14-beta", "", "9", "\u00e9"):
    case("github.body", version, ref=lambda version=version: github.body(version))
import base64
for data in ("", "a", "ab", "abc", "abcd", "x" * 100):
    case("github.base64", data, ref=lambda data=data: base64.b64encode(data.encode("ascii")).decode("ascii"))
case("github.environment", ref=lambda: github.environment())
repo = github.PROJECT_PAGE
for text in ("", repo + "/pull/1", repo + "/pull/123456789", repo + "/pull/1234567890", repo + "/pull/", "x " + repo + "/pull/5 y", repo + "/pull/\u0663", repo + "/pull/1x",
             "a" + repo + "/pull/1", repo + "/pull/ " + repo + "/pull/8", repo + "/PULL/1", repo + "/pull/12345678901234", repo + "/pull/0" * 3,
             "https://github.com/other/repo/pull/1"):
    for whole in (False, True):
        case("github.pull", text, whole, ref=lambda text=text, whole=whole: (lambda found: found.group(0) if found else None)(
            (github.PULL.fullmatch if whole else github.PULL.search)(text)))

# find_gh: PATH entries of every kind
root = Path(SCRATCH) / "ghs"
def folder(name, gh=True):
    made = root / name
    made.mkdir(parents=True, exist_ok=True)
    if gh:
        (made / "gh.exe").write_bytes(b"MZ")
    return made
first, second, empty = folder("first"), folder("second"), folder("empty", gh=False)
here, home, app = folder("here"), root / "home", folder("home/app")
real, tools = folder("real"), folder("home/tools")
profile = folder("profile", gh=False)
(profile / "gh.exe").write_bytes(b"MZ")
shims = folder("profile/scoop/shims")
dirgh = root / "dirgh"
(dirgh / "gh.exe").mkdir(parents=True, exist_ok=True)
sep = os.pathsep
def find(path, unsafe=(), cwd=None):
    os.chdir(str(cwd or root))
    case("github.find_gh", path, [str(each) for each in unsafe], str(cwd or root),
         ref=lambda: github.find_gh(path, unsafe=tuple(unsafe)))
find(sep.join([str(root / "empty"), str(first), str(second)]))
find(sep.join([".", "here", '"%s"' % here, str(here) + os.sep, str(app), str(home), str(real)]), unsafe=(home,), cwd=here)
find(sep.join([".", str(here), str(app)]), unsafe=(home,), cwd=here)
find("")
find("   ")
find(sep.join([str(profile), str(shims)]), unsafe=(home,), cwd=profile)
find(sep.join([str(profile), str(tools)]), unsafe=(home,), cwd=profile)
find(sep.join(["relative\\dir", "C:gh", "\\\\", str(first)]))
find(sep.join(['"%s"' % first]))
find(sep.join(["  %s  " % first]))
find(sep.join([str(first).upper(), str(second)]), unsafe=(str(first).lower(),))
find(sep.join([str(first).replace("\\", "/")]))
find(sep.join([str(first) + "\\.", str(second)]))
find(sep.join([str(first) + "\\..\\second"]))
find(sep.join([str(root / "nope"), str(dirgh), str(second)]))
find(sep.join([str(first), str(second)]), unsafe=(first,))
find(sep.join([str(first), str(second)]), unsafe=(root,))
find(sep.join([str(first), str(second)]), unsafe=(str(root / "second"),))
find(sep.join([str(first), str(second)]), unsafe=(root / "other", str(root / "first" / "deeper")))
find(sep.join([str(first), str(second)]), cwd=first)
find(sep.join([str(first), str(second)]), cwd=root)
find(sep.join(["", str(first), "", ""]))
find(sep.join(["\\\\?\\" + str(first)]))
os.chdir(SCRATCH)
finish()
'''


class InspectDiff(advreport.ReportDiff):
    def test_what_a_check_asks_and_finds(self):
        found = self.family(INSPECT_SCRIPT, label="gh-inspect", expect_cases=150)
        kinds = set()
        for result in found["results"]:
            for step in result.get("ok", {}).get("steps", []):
                kinds.update(step)
        for kind in ("ready", "web", "sent", "error"):
            self.assertIn(kind, kinds)
        codes = {step.get("code") for result in found["results"] for step in result.get("ok", {}).get("steps", [])}
        for code in ("gh_spelling", "not_open", "already_filed", "pr_open", "fork_named_otherwise", "base_invalid",
                     "gh_failed", "gh_timeout"):
            self.assertIn(code, codes, code)
        RECORD.append("gh inspect: %d programs - every refusal, web and sent, the full Unicode case folding of a name, "
                      "pages of every shape, every call failing, hanging or raising; calls (argv, environment, folder, "
                      "stdin, timeout, flags) equal in order" % len(found["cases"]))


class PublishDiff(advreport.ReportDiff):
    def test_every_write_in_its_order(self):
        found = self.family(PUBLISH_SCRIPT, label="gh-publish", expect_cases=80)
        urls = [step for result in found["results"] for step in result.get("ok", {}).get("steps", []) if "url" in step]
        self.assertTrue(urls)
        sleeps = [result["ok"]["sleeps"] for result in found["results"] if "ok" in result and result["ok"]["sleeps"]]
        self.assertTrue(sleeps)
        RECORD.append("gh publish: %d programs - the writes, a stop between each (refused, stopped, any error), a fork "
                      "waited for, the pull request gh will not repeat, the file on stdin" % len(found["cases"]))


class PureDiff(advreport.ReportDiff):
    def test_the_pure_functions_and_find_gh(self):
        found = self.family(PURE_SCRIPT, label="gh-pure", expect_cases=100)
        RECORD.append("gh pure: %d cases - blob_sha, destination, spelling, title, body, base64, the environment, the "
                      "pull request matcher, find_gh over every kind of PATH" % len(found["cases"]))


if __name__ == "__main__":
    unittest.main()

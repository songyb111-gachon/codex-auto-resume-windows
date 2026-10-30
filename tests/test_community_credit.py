"""Credit for a compatibility report, only when its sender chose it (v0.6.20, build/community_file.py CREDIT).

A report that says `"credit": true` adds its pull request's author - the login the survey has for the account, which
community_check holds equal to the report's folder - to docs/CONTRIBUTORS.md and README.md's thanks line on main, and
to their Korean twins on dev, once per person, in a fixed sentence. Each rule here fails with that rule reverted:
default off writes nothing; the login is the author's, never the file's; nothing a report says can reach the
documents; a person is credited once; a bot and the owner never; whatever stops a filing stops its credit; a withdrawal
leaves a credit as it is; and the workflow's write step takes a credit only in the planner's shape.

Scratch worlds of tests/test_community_file.py: no network, no GitHub.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import test_community_file as base  # noqa: E402
from test_community_file import NOW, VERSION, World, commit, git, sample  # noqa: E402

filer, reader = base.filer, base.reader

CONTRIBUTORS = """# Contributors

## songyb111-gachon

Project creator and maintainer.

## People who reported, suggested and tested

Everyone below is a person outside the project who helped it, in the order they first did.

- [@cervinho](https://github.com/cervinho) asked for the computer to shut down.
- [@kano0222](https://github.com/kano0222) reported that a conversation an agent made was never recovered, and
  traced it to the exact rule in the code.

## A note on the AI contributors

Tools, not people.
"""
THANKS = """# Tool

## Credits and license

Thanks to everyone who
reported a problem - [@cervinho](https://github.com/cervinho) and [@kano0222](https://github.com/kano0222) among them;
the changelog names them.
"""
CONTRIBUTORS_KO = """# 기여자

## 문제를 알리고, 제안하고, 시험해 주신 분들

- [@cervinho](https://github.com/cervinho) 님은 종료 기능을 요청했습니다.
- [@kano0222](https://github.com/kano0222) 님은 문제를 알렸습니다.

## AI 기여자에 대한 참고
"""
THANKS_KO = """# 도구

모든 분께 감사드립니다([@cervinho](https://github.com/cervinho), [@kano0222](https://github.com/kano0222) 님 등).
"""


def digest(text) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mapping(contributors=CONTRIBUTORS, thanks=THANKS) -> bytes:
    made = {"documents": {"README.ko.md": "README.md", "docs/CONTRIBUTORS.ko.md": "docs/CONTRIBUTORS.md"},
            "reviewed": {"README.md": digest(thanks), "docs/CONTRIBUTORS.md": digest(contributors)}}
    return (json.dumps(made, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def credited(login="User7", version=VERSION, **changes) -> dict:
    report = sample(login=login, version=version)
    report["credit"] = True
    report.update(changes)
    return report


def credit_world(root) -> World:
    """A scratch world whose main has the two English documents and the language map, and whose dev has their
    Korean twins too."""
    world = World(root)
    main = commit(world.origin, world.base, {"README.md": THANKS.encode("utf-8"),
                                             filer.CONTRIBUTORS: CONTRIBUTORS.encode("utf-8"),
                                             filer.KO_BRANCH: mapping()}, "docs", date="2026-09-20T12:00:00Z")
    git(world.origin, "update-ref", "refs/heads/main", main)
    dev = commit(world.origin, main, {"docs/GUIDE.ko.md": "# 안내\n".encode("utf-8"),
                                      filer.THANKS_KO: THANKS_KO.encode("utf-8"),
                                      filer.CONTRIBUTORS_KO: CONTRIBUTORS_KO.encode("utf-8")},
                 "Korean", date="2026-09-21T00:00:00Z")
    git(world.origin, "update-ref", "refs/heads/dev", dev)
    world.base, world.dev = main, dev
    return world


class CreditCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = credit_world(Path(folder.name) / "world")

    def tip(self, name):
        chain = self.world.chain()
        raw = self.world.show(chain[-1], name) if chain else None
        return raw.decode("utf-8") if raw is not None else None

    def changed(self):
        main = git(self.world.checkout, "rev-parse", "refs/remotes/origin/main")
        return sorted(git(self.world.checkout, "diff", "--name-only", main, self.world.chain()[-1]).splitlines())


class FilingCreditTests(CreditCase):
    def test_default_off_writes_nothing(self):
        self.world.pr(7, sample(login="User7"))
        self.world.plan()
        self.assertEqual(len(self.world.chain()), 1)
        self.assertNotIn(filer.CONTRIBUTORS, self.changed())
        self.assertNotIn("README.md", self.changed())
        self.assertNotIn(filer.KO_BRANCH, self.changed())

    def test_a_chosen_credit_names_the_author_once_in_the_fixed_sentence(self):
        self.world.pr(7, credited())
        self.world.plan()
        self.assertEqual(self.changed(), sorted([reader.canonical_path("User7", VERSION), filer.INDEX, filer.README,
                                                 filer.COUNTS, filer.CONTRIBUTORS, "README.md", filer.KO_BRANCH]))
        contributors = self.tip(filer.CONTRIBUTORS)
        line = "- [@User7](https://github.com/User7) reported compatibility on Codex %s." % VERSION
        self.assertEqual(contributors.count(line), 1)
        # At the end of the list of people, before the next section.
        self.assertLess(contributors.index("[@kano0222]"), contributors.index(line))
        self.assertLess(contributors.index(line), contributors.index("## A note on the AI contributors"))
        thanks = self.tip("README.md")
        self.assertIn(", [@kano0222](https://github.com/kano0222) and [@User7](https://github.com/User7) among them;",
                      thanks)
        reviewed = json.loads(self.tip(filer.KO_BRANCH))["reviewed"]
        self.assertEqual(reviewed, {"README.md": digest(thanks), "docs/CONTRIBUTORS.md": digest(contributors)})

    def test_the_login_is_the_pull_requests_author_never_the_files(self):
        """A report filed under another login than its author's is refused before anything is written; and the
        planner credits the login it is given for the author, which must be the report's own folder."""
        self.world.pr(7, credited(login="Mallory"), login="User7", path=reader.canonical_path("User7", VERSION))
        self.world.plan()
        self.assertEqual(self.world.chain(), [])
        planner = self.world.plan()
        path = reader.canonical_path("User7", VERSION)
        files = planner.filing_files(planner.reports(), path, credited(), login="Someone")
        self.assertNotIn(filer.CONTRIBUTORS, files)

    def test_nothing_a_report_says_reaches_the_documents(self):
        hostile = ["a\nb", "x<script>", "[x](https://evil.example)", "User7)\n- [@evil](x", "dependabot[bot]", "",
                   "-leading", "a" * 40]
        show = {filer.CONTRIBUTORS: CONTRIBUTORS.encode(), "README.md": THANKS.encode(), filer.KO_BRANCH: mapping()}.get
        for login in hostile:
            with self.subTest(login=login):
                self.assertEqual(filer.credit_files(show, login, VERSION), {})
        for version in ("codex-cli 0.1.0\n- [@evil](x)", "0.1.0", "codex-cli 0.1.0 <b>", "codex-cli 01.0.0"):
            with self.subTest(version=version):
                self.assertEqual(filer.credit_files(show, "User7", version), {})
        report = credited(note="# heading\n<img src=x>\n[link](y)")
        self.world.pr(7, report)
        self.world.plan()
        for name in (filer.CONTRIBUTORS, "README.md"):
            self.assertNotIn("heading", self.tip(name))
            self.assertNotIn("<img", self.tip(name))

    def test_a_person_is_credited_once(self):
        self.world.filed_by_hand(credited(), reporter_id=507, number=6)
        show = {filer.CONTRIBUTORS: self.world.show("refs/heads/main", filer.CONTRIBUTORS, self.world.origin),
                "README.md": THANKS.encode()}.get
        once = filer.credit_files(show, "User7", VERSION)
        twice_show = {name: data for name, data in once.items()}
        self.assertEqual(filer.credit_files(lambda name: twice_show.get(name), "user7", "codex-cli 0.156.0"), {})
        self.assertEqual(filer.credit_files({filer.CONTRIBUTORS: CONTRIBUTORS.encode(),
                                             "README.md": THANKS.encode()}.get, "KANO0222", VERSION), {})

    def test_a_bot_or_the_owner_is_never_credited(self):
        for login in ("songyb111-gachon", "SONGYB111-GACHON", "github-actions[bot]", "dependabot[bot]"):
            with self.subTest(login=login):
                self.assertFalse(filer.credit_login(login))
        self.assertTrue(filer.credit_login("User7"))

    def test_the_kill_switch_and_a_blocked_account_stop_the_credit_too(self):
        self.world.pr(7, credited())
        self.world.plan({"AUTOFILE": "off"})
        self.assertEqual(self.world.chain(), [])
        self.world.plan({"BLOCKED": "507"})
        self.assertEqual(self.world.chain(), [])

    def test_a_withdrawal_leaves_a_credit_as_it_is(self):
        path = reader.canonical_path("User7", VERSION)
        files = filer.withdrawal({path: credited()}, path, 507, None, NOW)
        self.assertFalse(set(files) & {filer.CONTRIBUTORS, "README.md", filer.KO_BRANCH, filer.CONTRIBUTORS_KO,
                                       filer.THANKS_KO})

    def test_dev_is_left_for_promote_when_main_credited_someone_in_an_earlier_run(self):
        """The write job takes a Korean credit only for this run's filings, so the planner does not offer another."""
        self.world.filed_by_hand(credited(login="User8"), reporter_id=508, number=8)
        show = {name: self.world.show("refs/heads/main", name, self.world.origin)
                for name in (filer.CONTRIBUTORS, "README.md", filer.KO_BRANCH)}
        files = filer.credit_files(show.get, "User8", VERSION)
        self.world.on_main(files, filer.commit_message("User8", VERSION, 508, 8))
        planner = self.world.plan()
        self.assertEqual((self.world.out / "dev").read_text(encoding="utf-8"), "")
        self.assertTrue(any("Korean documents" in line for line in planner.summary), planner.summary)

    def test_dev_takes_the_credit_in_its_korean_documents(self):
        self.world.pr(7, credited())
        self.world.plan()
        merge = (self.world.out / "dev").read_text(encoding="utf-8").split()[1]
        korean = self.world.show(merge, filer.CONTRIBUTORS_KO).decode("utf-8")
        self.assertIn("- [@User7](https://github.com/User7) 님은 Codex %s에서 호환성을 보고해 주셨습니다." % VERSION, korean)
        self.assertIn("[@kano0222](https://github.com/kano0222), [@User7](https://github.com/User7) 님 등)",
                      self.world.show(merge, filer.THANKS_KO).decode("utf-8"))
        for name in (filer.CONTRIBUTORS, "README.md", filer.KO_BRANCH):
            self.assertEqual(self.world.show(merge, name), self.world.show(self.world.chain()[-1], name))


@unittest.skipUnless(base.git_bash(), "no bash to run the workflow's step with")
class WriteStepCreditTests(CreditCase):
    def test_the_write_step_files_a_credit_and_brings_it_to_dev(self):
        self.world.pr(7, credited())
        self.world.plan()
        code, said = self.world.write()
        self.assertEqual(code, 0, said)
        main = self.world.main()
        self.assertIn(b"[@User7](https://github.com/User7) reported compatibility",
                      self.world.show(main, filer.CONTRIBUTORS, self.world.origin))
        dev = git(self.world.origin, "rev-parse", "refs/heads/dev")
        self.assertIn("[@User7](https://github.com/User7) 님은".encode("utf-8"),
                      self.world.show(dev, filer.CONTRIBUTORS_KO, self.world.origin))

    def tampered(self, files):
        """A plan whose one commit is the filer's but for `files` set over it."""
        self.world.pr(7, credited())
        self.world.plan()
        planned = self.world.chain()[-1]
        main = git(self.world.checkout, "rev-parse", "refs/remotes/origin/main")
        names = git(self.world.checkout, "diff", "--name-only", main, planned).splitlines()
        made = {name: self.world.show(planned, name) for name in names}
        made.update(files)
        forged = commit(self.world.checkout, main, made, filer.commit_message("User7", VERSION, 507, 7))
        (self.world.out / "chain").write_bytes(forged.encode("ascii") + b"\n")
        (self.world.out / "dev").write_bytes(b"")
        git(self.world.checkout, "update-ref", "refs/plan/main", forged)
        (self.world.out / "plan.bundle").unlink()
        git(self.world.checkout, "bundle", "create", str(self.world.out / "plan.bundle"), "refs/plan/main", "^" + main)

    def assertRefused(self, fragment):
        before = self.world.main()
        code, said = self.world.write()
        self.assertEqual(code, 1, said)
        self.assertIn(fragment, said)
        self.assertEqual(self.world.main(), before)

    def test_a_credit_for_another_login_is_refused(self):
        line = "- [@Mallory](https://github.com/Mallory) reported compatibility on Codex %s." % VERSION
        self.tampered({filer.CONTRIBUTORS: CONTRIBUTORS.replace("## A note", line + "\n\n## A note").encode("utf-8")})
        self.assertRefused("a credit is not")

    def test_words_of_its_own_in_the_contributors_list_are_refused(self):
        self.tampered({filer.CONTRIBUTORS: (CONTRIBUTORS + "<script>x</script>\n").encode("utf-8")})
        self.assertRefused("a credit is not")

    # ------------------------------------------------ a plan forged on dev's side (the W7 review's C2)
    def rebundle(self, main_tip, dev_merge, dev_base):
        world = self.world
        main = git(world.checkout, "rev-parse", "refs/remotes/origin/main")
        git(world.checkout, "update-ref", "refs/plan/main", main_tip)
        git(world.checkout, "update-ref", "refs/plan/dev", dev_merge)
        (world.out / "chain").write_bytes(main_tip.encode("ascii") + b"\n")
        (world.out / "dev").write_bytes(("%s %s\n" % (dev_base, dev_merge)).encode("ascii"))
        (world.out / "plan.bundle").unlink()
        git(world.checkout, "bundle", "create", str(world.out / "plan.bundle"), "refs/plan/main", "refs/plan/dev",
            "^" + main, "^" + dev_base)

    def forged_dev(self, files, login="User7"):
        """The planner's own plan for a credited report from `login`, but dev's merge with `files` set over it."""
        world = self.world
        world.pr(7, credited(login=login), login=login)
        world.plan()
        dev_base, merge = (world.out / "dev").read_text(encoding="utf-8").split()
        tip = world.chain()[-1]
        with tempfile.TemporaryDirectory() as folder:
            index = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
            git(world.checkout, "read-tree", merge, env=index)
            for path, data in files.items():
                blob = git(world.checkout, "hash-object", "-w", "--no-filters", "--stdin", data=data)
                git(world.checkout, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, path), env=index)
            tree = git(world.checkout, "write-tree", env=index)
        self.rebundle(tip, git(world.checkout, "commit-tree", tree, "-p", dev_base, "-p", tip, "-m", "dev merge"),
                      dev_base)

    def assertDevRefused(self, fragment):
        dev = git(self.world.origin, "rev-parse", "refs/heads/dev")
        code, said = self.world.write()
        self.assertEqual(code, 1, said)
        self.assertIn(fragment, said)
        self.assertEqual(git(self.world.origin, "rev-parse", "refs/heads/dev"), dev)

    def test_a_korean_thanks_link_whose_text_is_not_its_address_is_refused(self):
        evil = THANKS_KO.replace(" 님 등)", ", [@User7](https://github.com/User7), [@Mallory](https://github.com/evil-site) 님 등)")
        self.forged_dev({filer.THANKS_KO: evil.encode("utf-8")})
        self.assertDevRefused("dev's credit is not the filer's thanks")

    def test_a_korean_thanks_for_someone_this_run_did_not_credit_is_refused(self):
        evil = THANKS_KO.replace(" 님 등)", ", [@User7](https://github.com/User7), [@cervinho2](https://github.com/cervinho2) 님 등)")
        self.forged_dev({filer.THANKS_KO: evil.encode("utf-8")})
        self.assertDevRefused("dev's credit names no one this run credited")

    def test_a_korean_contributors_line_for_someone_this_run_did_not_credit_is_refused(self):
        line = "- [@User8](https://github.com/User8) 님은 Codex %s에서 호환성을 보고해 주셨습니다." % VERSION
        self.world.filed_by_hand(sample(login="User8", failed=True), reporter_id=508, number=8)
        korean = CONTRIBUTORS_KO.replace("\n\n## AI", "\n" + line + "\n\n## AI")
        self.forged_dev({filer.CONTRIBUTORS_KO: korean.encode("utf-8")})
        self.assertDevRefused("dev's credit names no one this run credited")

    def test_a_language_map_change_beyond_a_digest_is_refused(self):
        changed = json.loads(mapping())
        changed["documents"]["evil.md"] = "x"
        self.tampered({filer.KO_BRANCH: (json.dumps(changed, indent=2) + "\n").encode("utf-8")})
        self.assertRefused("more of the language map")


if __name__ == "__main__":
    unittest.main()

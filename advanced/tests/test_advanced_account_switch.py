"""Switch the Codex account (v0.6.20, plans/v0619-design/D-account.md): the card's read and Codex's own sign-out and
sign-in.

The Dashboard's card reads the account (advanced-account) only while account_switch stands on or is watched, and shows
the address masked; its button - only while the capability is on and MAL passed on the Codex in force - runs Codex's own
`codex logout` then `codex login` (codex/account.switch) on a thread of the Dashboard's, as argument lists in the job
object with no console, and the card reads how it ended. The product never asks Codex for a sign-in method, never opens
Codex's sign-in file, and nothing but the Dashboard's command handler starts a switch.

Every child here is a fake runner and every read a fake: no Codex runs, nobody is signed out, no credential is touched.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import account, protocol  # noqa: E402
from codex_auto_resume_advanced.control import account as card  # noqa: E402
from codex_auto_resume_advanced.registry import ACCOUNT_SWITCH  # noqa: E402
from codex_auto_resume_advanced.report import github  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, Measurement, Refusal, Verdict  # noqa: E402

CAP = "account_switch"
ONE = {"account": {"type": "chatgpt", "email": "someone@example.com", "planType": "plus"}}
PACKAGE = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced"


class Backend:
    """core's Backend as a switch uses it: the argv and the environment core's codex children run with."""
    codex_home = Path("C:/scratch/codex-home")

    def _argv(self):
        return ["C:/scratch/codex.exe", "-c", "analytics.enabled=false"]

    def _environment(self):
        return {"CODEX_HOME": str(self.codex_home), "OTEL_SDK_DISABLED": "true"}


class Runner:
    """report/github.run_process's shape: each call written down, and what it answers, by the subcommand."""

    def __init__(self, **answers):
        self.calls, self.answers = [], answers

    def __call__(self, argv, *, env, cwd, stdin, timeout, creationflags=None):
        self.calls.append({"argv": list(argv), "env": env, "cwd": cwd, "stdin": stdin, "timeout": timeout})
        found = self.answers.get(argv[-1], 0)
        if isinstance(found, BaseException):
            raise found
        return found, "", ""


class SwitchTests(unittest.TestCase):
    def switch(self, runner, present=True):
        return account.switch(None, backend=Backend(), runner=runner,
                              reader=lambda paths: account.parse(ONE if present else {"account": None}
                                                                 if present is False else None))

    def test_codex_s_own_logout_then_login_as_argument_lists_in_its_own_environment(self):
        runner = Runner()
        self.assertEqual(self.switch(runner), account.SIGNED_IN)
        self.assertEqual([call["argv"] for call in runner.calls],
                         [Backend()._argv() + ["logout"], Backend()._argv() + ["login"]])
        for call in runner.calls:
            self.assertEqual((call["env"], call["cwd"], call["stdin"]),
                             (Backend()._environment(), str(Backend.codex_home), None))
        self.assertEqual([call["timeout"] for call in runner.calls], [account.LOGOUT_SECONDS, account.LOGIN_SECONDS])
        self.assertEqual(account.LOGIN_SECONDS, 600, "ten minutes in the browser")

    def test_how_it_ended_is_read_back_from_codex(self):
        self.assertEqual(self.switch(Runner(login=1), present=False), account.CANCELLED)
        self.assertEqual(self.switch(Runner(), present=None), account.FAILED)
        self.assertEqual(self.switch(Runner(login=1), present=True), account.SIGNED_IN)

    def test_a_login_not_finished_in_ten_minutes_is_timed_out_and_a_child_that_cannot_run_failed(self):
        self.assertEqual(self.switch(Runner(login=github.GhTimeout())), account.TIMED_OUT)
        runner = Runner(logout=OSError("not in the job"))
        self.assertEqual(self.switch(runner), account.FAILED)
        self.assertEqual(len(runner.calls), 1, "no sign-in after a sign-out that could not run")
        self.assertEqual(account.switch(None, backend=object(), runner=Runner()), account.FAILED)

    def test_the_default_runner_is_the_job_s_with_no_console_and_no_shell(self):
        used = []
        with patch.object(github, "run_process", lambda argv, **options: used.append(argv) or (0, "", "")):
            account.switch(None, backend=Backend(), reader=lambda paths: account.parse(ONE))
        self.assertEqual(len(used), 2)
        from codex_auto_resume.win.kernel import NO_WINDOW
        self.assertTrue(github.FLAGS & NO_WINDOW)
        self.assertIn("shell=False", Path(github.__file__).read_text(encoding="utf-8"))


class CardCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="usage_probe")
        self.measured = {}
        self.rt = self.runtime(ACCOUNT_SWITCH)
        self.rt.arming.catalogs = statement.CATALOGS
        self.reads, self.jobs, self.ran = [], [], []
        card._SWITCHES.clear()
        self.addCleanup(card._SWITCHES.clear)
        self.reader = lambda paths: self.reads.append(paths) or account.parse(ONE)

    def on(self, state="armed"):
        definition = ACCOUNT_SWITCH
        result = self.rt.arming.arm(CAP, state=state, revision=definition.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(definition)],
                                    actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)

    def measure(self):
        self.measured[Measurement.MAL] = (Verdict.PASS, ac.ENGINE)

    def start(self):
        return card.switch(self.rt, start=self.jobs.append, run=lambda paths: self.ran.append(paths) or self.outcome)

    def codes(self):
        with self.rt.state._read() as connection:
            return [found[0] for found in connection.execute("SELECT code FROM journal")]


class CardTests(CardCase):
    def test_off_nothing_is_read_and_no_switch_starts(self):
        self.assertEqual(card.view(self.rt, reader=self.reader), {"done": False, "refusal": Refusal.NOT_ON})
        self.measure()
        self.outcome = account.SIGNED_IN
        self.assertEqual(self.start()["refusal"], Refusal.NOT_ON)
        self.assertEqual((self.reads, self.jobs), ([], []))

    def test_on_the_card_reads_the_plan_and_the_masked_address_and_no_more(self):
        self.on()
        answer = card.view(self.rt, reader=self.reader)
        self.assertEqual(answer, {"done": True, "refusal": None, "present": True, "plan": "plus", "kind": "chatgpt",
                                  "mask": account.mask("someone@example.com"), "button": False, "switch": None})
        self.assertNotIn("someone@example.com", str(answer))

    def test_until_mal_passed_no_button_and_a_switch_is_refused(self):
        self.on()
        self.outcome = account.SIGNED_IN
        self.assertEqual(self.start()["refusal"], Refusal.SWITCH_UNMEASURED)
        self.measure()
        self.assertTrue(card.view(self.rt, reader=self.reader)["button"])

    def test_watched_it_reads_and_offers_no_button(self):
        self.on(state="shadow")
        self.measure()
        self.assertFalse(card.view(self.rt, reader=self.reader)["button"])
        self.outcome = account.SIGNED_IN
        self.assertEqual(self.start()["refusal"], Refusal.NOT_ON)

    def test_a_switch_waits_unread_then_says_how_it_ended_and_is_counted(self):
        self.on()
        self.measure()
        self.outcome = account.CANCELLED
        self.assertEqual(self.start(), {"done": True, "refusal": None, "switch": "waiting"})
        self.assertEqual(self.start()["refusal"], Refusal.SWITCH_RUNNING, "one at a time")
        waiting = card.view(self.rt, reader=self.reader)
        self.assertEqual((waiting["switch"], waiting["present"], self.reads), ("waiting", None, []))
        self.jobs[0]()
        self.assertEqual(self.ran, [self.rt.paths])
        self.assertEqual(card.view(self.rt, reader=self.reader)["switch"], account.CANCELLED)
        codes = self.codes()
        self.assertEqual((codes.count("account.switch_asked"), codes.count("account.not_signed_in")), (1, 1))

    def test_a_switch_that_raises_is_failed_and_another_may_start(self):
        self.on()
        self.measure()

        def broken(paths):
            raise RuntimeError("no codex")
        card.switch(self.rt, start=self.jobs.append, run=broken)
        self.jobs[0]()
        self.assertEqual(card.switching(self.rt), account.FAILED)
        self.outcome = account.SIGNED_IN
        self.assertTrue(self.start()["done"])

    def test_the_bridge_answers_both_for_the_dashboard_alone(self):
        self.assertEqual(surfaces.bridge(self.rt, "advanced-account-switch", {})["refusal"], Refusal.NOT_ON)
        self.assertEqual(surfaces.bridge(self.rt, "advanced-account", {"x": 1})["refusal"], Refusal.INVALID_REQUEST)
        with patch.object(account, "read", self.reader):
            self.assertEqual(surfaces.bridge(self.rt, "advanced-account", {})["refusal"], Refusal.NOT_ON)
        self.assertEqual(self.reads, [])
        names = {tool["name"] for tool in surfaces.TOOLS}
        self.assertFalse([name for name in names if "account" in name], "no MCP tool reaches either")


class StructureTests(unittest.TestCase):
    """B11 and K3 by the source: one caller of the switch, no sign-in method anywhere but the forbidden set, and no
    product code that names Codex's sign-in file."""

    @staticmethod
    def sources(root):
        return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)

    def test_only_the_dashboard_s_command_handler_starts_a_switch(self):
        callers = []
        for path in self.sources(PACKAGE):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute) and node.attr == "switch" and isinstance(node.value, ast.Name)
                        and node.value.id == "account"):
                    callers.append(path.relative_to(PACKAGE).as_posix())
        self.assertEqual(sorted(set(callers)), ["control/account.py"])
        for folder in ("engine", "report", "codex"):
            for path in self.sources(PACKAGE / folder):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("control.account", text, path.name)
                self.assertNotIn("control import account", text, path.name)

    def test_no_sign_in_method_is_named_but_in_the_forbidden_set(self):
        self.assertTrue({"account/login/start", "account/login", "account/logout"} <= protocol.FORBIDDEN_METHODS)
        for path in self.sources(PACKAGE):
            text = path.read_text(encoding="utf-8")
            if path.name == "protocol.py":
                text = text.replace('"account/login/start", "account/login", "account/logout",', "")
            for word in ("account/login", "account/logout"):
                self.assertNotIn(word, text, path.relative_to(PACKAGE).as_posix())

    def test_no_product_code_opens_codex_s_sign_in_file(self):
        """No string the code holds names it - a comment or a docstring that says it is never read aside."""
        for root in (ac.ROOT / "src" / "codex_auto_resume", PACKAGE):
            for path in self.sources(root):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                documents = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr)}
                held = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                        and isinstance(node.value, str) and id(node) not in documents]
                self.assertFalse([text for text in held if "auth.json" in text.lower()], path.as_posix())


if __name__ == "__main__":
    unittest.main()

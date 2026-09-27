"""v0.6.11: Diagnostics' own tools, and the prompts to ask Codex in nine languages.

* The log, searched: this product's own log - written from a fixed table (logbook.py) - read by the
  bridge and never errors.log, the lines that hold the search given back newest last.
* Who may open the state folder: one word from the folder's access list (win/acl.py), the rule apart
  from the asking so it is held here without asking this machine anything.
* Show me what happens: made-up rows for the Dashboard and one made-up card from the watcher's icon.
  The module both take it from imports neither the store nor the engine; asking for it leaves the
  state and its journal byte for byte as they were; the card's buttons carry no URI and it is never a
  toast; and nothing is started.
* Starter prompts: the English ones are the prompts plugin.json gives Codex, every language has its
  own, and the panel names them.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import srcscan  # noqa: E402
from codex_auto_resume import control, controlcli, demo, l10n, notifier  # noqa: E402
from codex_auto_resume.control import tools  # noqa: E402
from codex_auto_resume.control.records import describe_record  # noqa: E402
from codex_auto_resume.domain.vocabulary import StateAccess  # noqa: E402
from codex_auto_resume.mcp import panel  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.win import acl  # noqa: E402
from test_control import THREAD, ControlTestCase, detection  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OWN = "S-1-5-21-1000000000-2000000000-3000000000-1001"


# ------------------------------------------------------------------------------ the log
class LogSearchTests(ControlTestCase):
    def write_log(self):
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        older = self.paths.log_file.with_name(self.paths.log_file.name + ".1")
        older.write_text("[2026-09-27 09:00:00] thread %s: waiting for reset\n" % THREAD, encoding="utf-8")
        self.paths.log_file.write_text(
            "[2026-09-27 10:00:00] auto-resume is enabled\n"
            "not a line the formatter writes\n"
            "[2026-09-27 10:01:00] thread %s: continuation submitted\n"
            "[2026-09-27 10:02:00] watcher stopped\n" % THREAD, encoding="utf-8")
        self.paths.error_log.write_text("[2026-09-27 10:03:00] Traceback: private words\n", encoding="utf-8")

    def test_every_line_the_formatter_wrote_oldest_file_first_newest_last(self):
        self.write_log()
        found = self.control.search_logs()
        self.assertEqual([line["at"] for line in found["lines"]],
                         ["2026-09-27 09:00:00", "2026-09-27 10:00:00", "2026-09-27 10:01:00", "2026-09-27 10:02:00"])
        self.assertEqual((found["matched"], found["total"]), (4, 4))
        self.assertNotIn("private words", json.dumps(found), "errors.log is never read")

    def test_a_search_ignores_case_and_a_limit_keeps_the_newest(self):
        self.write_log()
        found = self.control.search_logs("THREAD")
        self.assertEqual([line["text"].split(": ")[1] for line in found["lines"]],
                         ["waiting for reset", "continuation submitted"])
        self.assertEqual(self.control.search_logs(None, 1)["lines"][0]["at"], "2026-09-27 10:02:00")
        self.assertEqual(self.control.search_logs("nothing like this")["lines"], [])

    def test_a_search_is_short_text_with_no_control_character(self):
        for query in ("x" * 101, "a\nb", 5):
            with self.subTest(query=str(query)[:10]), self.assertRaises(control.ControlError):
                self.control.search_logs(query)
        self.assertEqual(self.control.search_logs()["lines"], [], "no log yet is no lines")

    def test_the_bridge_answers_it(self):
        self.write_log()
        reply = controlcli.dispatch(self.control, "logs", {"query": "enabled"})
        self.assertEqual([line["at"] for line in reply["result"]["lines"]], ["2026-09-27 10:00:00"])


# ---------------------------------------------------------------- who may open the state folder
class StateAccessTests(unittest.TestCase):
    def test_the_rule(self):
        verdict = acl.verdict
        self.assertEqual(verdict([OWN, "S-1-5-18", "S-1-5-32-544", "S-1-3-0"], OWN), "owner_only")
        self.assertEqual(verdict([OWN, "S-1-15-3-1024-1"], OWN), "owner_only", "an app's sandbox is no account")
        for other in ("S-1-5-32-545", "S-1-1-0", "S-1-5-11", "S-1-5-21-1-2-3-1002"):
            with self.subTest(other):
                self.assertEqual(verdict([OWN, other], OWN), "shared")
        self.assertEqual(verdict(None, OWN), "unknown")
        self.assertEqual(verdict([OWN], None), "unknown")
        self.assertEqual(verdict([], OWN), "owner_only", "a folder nobody may open is nobody else's either")

    def test_another_local_account_is_another_account_even_codexs_own_sandbox(self):
        """Codex's Windows sandbox gives its own local accounts - a group of them, and an identifier of its own -
        a way into AppData and Temp, so a state folder there reads as shared. It is: a command Codex runs in its
        sandbox runs as one of those accounts, and could read and change the pending tasks. Only an app's own
        sandbox (S-1-15-), which runs as this account, is not another; the note then says where the folder is
        this account's alone."""
        sandbox_group, sandbox_identifier = "S-1-5-21-1-2-3-1011", "S-1-5-21-4-5-6-1019343860"
        for other in (sandbox_group, sandbox_identifier):
            with self.subTest(other):
                self.assertEqual(acl.verdict([OWN, "S-1-5-18", "S-1-5-32-544", other], OWN), "shared")

    def test_the_note_says_where_the_folder_is_this_accounts_alone(self):
        """"Install it under your own user folder" told a person whose folder was under AppData - inside their user
        folder already - to do what they had done. The place that helps is the installer's own, by its name."""
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                self.assertIn(".codex-auto-resume", l10n.catalog(locale)["diag.state_shared_note"])

    def test_it_never_raises_and_answers_one_of_three_words(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn(acl.state_access(folder), set(StateAccess))
            self.assertEqual(acl.state_access(Path(folder) / "missing"), "unknown")
        with patch.object(acl, "allowed_sids", side_effect=OSError("boom")):
            self.assertEqual(acl.state_access("C:\\"), "unknown")

    def test_it_keeps_no_identifier_and_writes_nothing(self):
        source = (ROOT / "src" / "codex_auto_resume" / "win" / "acl.py").read_text(encoding="utf-8")
        for writer in ("SetNamedSecurityInfo", "SetSecurityInfo", "SetFileSecurity", "SetEntriesInAcl"):
            self.assertNotIn(writer, source)
        with patch.object(acl, "allowed_sids", return_value=[OWN, "S-1-1-0"]), \
                patch.object(acl, "_own_sid", return_value=OWN):
            self.assertEqual(acl.state_access("C:\\"), "shared")


class StateAccessControlTests(ControlTestCase):
    def test_the_bridge_says_one_word(self):
        with patch.object(acl, "state_access", return_value="owner_only"):
            reply = controlcli.dispatch(self.control, "state-access", {})
        self.assertEqual(reply, {"ok": True, "result": {"access": "owner_only"}})


# --------------------------------------------------------------------- show me what happens
class DemoModuleTests(unittest.TestCase):
    def test_it_imports_neither_the_store_nor_the_engine(self):
        path = srcscan.modules()["codex_auto_resume.demo"]
        targets = {entry.target for entry in srcscan.imports(path)}
        self.assertFalse({name for name in targets if name.startswith(("codex_auto_resume.store",
                                                                        "codex_auto_resume.engine",
                                                                        "codex_auto_resume.codex"))})
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        self.assertFalse([node for node in ast.walk(tree) if isinstance(node, ast.Call)
                          and getattr(node.func, "id", None) == "open"], "and opens no file")

    def test_its_rows_are_made_up_whole_and_have_the_keys_a_row_has(self):
        rows = demo.rows(1000.0)
        self.assertEqual(rows["seconds"], 60)
        record = dict(detection(), state="waiting_reset", next_retry_at=1060.0, reset_at=1060.0, detected_at=1000.0,
                      recovery_attempts=0, no_progress_count=0, chain_continuations=0,
                      chain_origin_id="0" * 64, parent_interruption_id=None, budget_resets=0,
                      cancel_requested=False, recovery_turn_status=None, user_joined=False, after_user_work=False,
                      outcome_at=None, first_queued_at=None, gate_eval=None, gate_eval_at=None, last_error=None)
        listed = set(describe_record(record)) | {"thread_enabled", "tier", "attempt_limit", "name", "project",
                                                 "cwd_basename"}
        for name in ("pending", "history"):
            with self.subTest(name):
                self.assertEqual(set(rows[name]) - {"demo"}, listed)
                self.assertIs(rows[name]["demo"], True)
                self.assertEqual((rows[name]["interruption_id"], rows[name]["thread_id"]), (demo.DEMO_KEY, demo.DEMO_THREAD))
        self.assertEqual((rows["pending"]["code"], rows["pending"]["eligible_at"]), ("waiting_reset", 1060.0))
        self.assertEqual((rows["history"]["code"], rows["history"]["terminal"]), ("recovered", True))
        self.assertTrue(demo.DEMO_KEY.endswith("de30") and set(demo.DEMO_KEY[:60]) == {"0"}, "obviously fake")


class DemoControlTests(ControlTestCase):
    def fingerprint(self):
        found = {}
        for path in sorted(self.paths.state_dir.glob("state.sqlite*")):
            found[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return found

    def test_asking_for_it_leaves_the_state_and_its_journal_as_they_were_and_starts_nothing(self):
        with Store(self.paths.state_dir) as store:
            store.set_enabled(True, 100.0)
            store.register(detection(), 100.0)
            events = store.events()
        before = self.fingerprint()
        with patch.object(control.Control, "start_watcher", side_effect=AssertionError("started")), \
                patch("subprocess.Popen", side_effect=AssertionError("a process")):
            reply = controlcli.dispatch(self.control, "demo", {})
        self.assertTrue(reply["ok"])
        self.assertIs(reply["result"]["asked"], False, "no watcher here holds the demo event")
        self.assertEqual(self.fingerprint(), before)
        with Store(self.paths.state_dir) as store:
            self.assertEqual(store.events(), events)
        self.assertEqual(set(reply["result"]), {"seconds", "pending", "history", "asked"})


class DemoCardTests(unittest.TestCase):
    def test_its_buttons_carry_no_uri_and_do_nothing(self):
        notice = notifier.build_demo(time.time())
        self.assertEqual(notice.kind, "demo")
        self.assertTrue(notice.actions)
        self.assertEqual({uri for _label, uri in notice.actions}, {""})
        for _label, uri in notice.actions:
            self.assertEqual(notifier.activate(uri, control=object(), open_dashboard=lambda page: 1 / 0), "ignored")
        self.assertIn(demo.DEMO_THREAD, notice.origin, "made up, and says so by its id")
        self.assertTrue(notice.title.startswith(l10n.text("demo.card_title", l10n.current()).split("{title}")[0]))

    def test_it_is_never_a_toast(self):
        notice = notifier.build_demo(time.time())
        shown = []
        self.assertFalse(notifier.complete(notice, True, show=lambda *args, **kwargs: shown.append(args)))
        self.assertFalse(notifier.complete(notice, False, show=lambda *args, **kwargs: shown.append(args)))
        self.assertEqual(shown, [])
        self.assertFalse(notifier.show_demo(notice, inbox=None))
        inbox = notifier.Inbox()
        inbox.attach(lambda: True)
        self.assertFalse(notifier.show_demo(notice, inbox=inbox, setting=False), "the card turned off: nothing")
        blocked = {name: None for name in notifier.PROBES}
        blocked["session_locked"] = True
        self.assertFalse(notifier.show_demo(notice, inbox=inbox, probe=lambda: blocked))
        self.assertEqual(inbox.take(), [])
        allowed = {"notification_state": 5, "notification_mode": 0, "app_notifications": 0,
                   "screen_reader": False, "remote_session": False, "session_locked": False}
        self.assertTrue(notifier.show_demo(notice, inbox=inbox, probe=lambda: allowed))
        self.assertEqual(inbox.take(), [notice])


class DemoTrayTests(unittest.TestCase):
    def test_the_icon_draws_it_only_when_its_event_was_signalled(self):
        from codex_auto_resume.ui import tray

        class Event:
            def __init__(self):
                self.signalled = [False, True, False]

            def taken(self):
                return self.signalled.pop(0)
        asked = []
        icon = tray.Tray(demo_name="state", on_demo=lambda: asked.append(1))
        icon._demo = Event()
        for _ in range(3):
            icon._look_for_demo()
        self.assertEqual(asked, [1])
        self.assertIsNone(tray.Tray()._open_demo(), "no demo asked for: no event made")


# ------------------------------------------------------------------------------ starter prompts
class StarterPromptTests(unittest.TestCase):
    KEYS = ("starter.setup", "starter.status", "starter.settings")

    def test_the_english_ones_are_the_prompts_plugin_json_gives_codex(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        english = l10n.catalog("en")
        self.assertEqual(manifest["interface"]["defaultPrompt"], [english[key] for key in self.KEYS])

    def test_every_language_has_its_own(self):
        english = l10n.catalog("en")
        keys = [key for key in english if key.startswith("starter.")]
        self.assertEqual(len(keys), 7)
        for locale in l10n.LOCALES:
            if locale == "en":
                continue
            for key in keys:
                with self.subTest(locale=locale, key=key):
                    self.assertNotEqual(l10n._read(locale)[key], english[key])

    def test_the_panel_names_them_and_ships_them_in_every_language(self):
        names, _prefixes = panel.panel_keys()
        self.assertTrue({"starter.title", "starter.note", "starter.status", "starter.pending", "starter.pause",
                         "starter.settings"} <= names)
        for locale, table in panel.panel_catalogs().items():
            with self.subTest(locale):
                self.assertIn("starter.pending", table)


if __name__ == "__main__":
    unittest.main()

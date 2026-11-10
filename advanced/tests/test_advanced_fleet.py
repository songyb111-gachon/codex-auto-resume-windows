"""See your other PCs (fleet_view, v0.6.22, engine/fleet.py, control/fleet.py): this PC's status written whole into a
folder a person syncs, and the other PCs' files read from it, checked.

Every home and every folder is a temporary one, and every synced file is one made here. No network is reached anywhere.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest advanced/tests/test_advanced_fleet.py
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import config, statusfile  # noqa: E402
from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume_advanced import registry, standards, statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.control import fleet as card  # noqa: E402
from codex_auto_resume_advanced.engine import fleet  # noqa: E402
from codex_auto_resume_advanced.registry import FLEET_VIEW  # noqa: E402
from codex_auto_resume_advanced.vocabulary import BridgeCommand, OptionKey, Refusal, WordingKey  # noqa: E402

PACKAGE = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced"
LOCALES = sorted(path.stem for path in (PACKAGE / "locales").glob("*.json"))
THREAD = "11111111-1111-7111-8111-111111111111"
SECRET_ROW = {"interruption_id": "22222222-2222-7222-8222-222222222222", "thread_id": THREAD, "state": "waiting_reset",
              "category": "usage_limit", "reset_at": ac.NOW + 900, "label": "a title nobody may see",
              "cwd": "C:\\Users\\ExampleUser\\secret-project"}


def status(now=ac.NOW, **changes) -> dict:
    made = statusfile.content(now=now, version="0.6.22", running=True, enabled=True, observe_only=False, engine="verified",
                              rows=(), reading=None)
    made.update(changes)
    return made


def peer(alias="desk", now=ac.NOW, **changes) -> dict:
    made = fleet.document(status(now), alias)
    made.update(changes)
    return made


class Done:
    """A pass already over: the seam for running a pass inside the test."""
    def is_alive(self):
        return False


def inline(run):
    run()
    return Done()


class Hanging:
    """A pass that never ends, as on a drive that stopped answering."""
    def is_alive(self):
        return True


class FleetCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.catalogs = statement.CATALOGS
        self.compat = ac.view(capability="engine_present")
        self.scratch = Path(tempfile.mkdtemp(prefix="car-fleet-"))
        self.addCleanup(lambda: shutil.rmtree(self.scratch, ignore_errors=True))
        self.folder = self.scratch / "synced"
        self.folder.mkdir()
        self.codex = self.scratch / "codex-home"
        self.codex.mkdir()
        self.paths.ensure()
        for stand_in in (patch.object(config, "codex_home", return_value=self.codex),
                         patch("codex_auto_resume_advanced.codex.inuse.home", return_value=self.codex)):
            stand_in.start()
            self.addCleanup(stand_in.stop)
        self.rt = self.runtime(FLEET_VIEW)
        self.rt.arming.catalogs = statement.CATALOGS
        self.code = self.rt._code_of(FLEET_VIEW)
        self.code._status = lambda now: status(now)
        self.code._spawn = inline

    def on(self, state="armed"):
        result = self.arm(self.rt, "fleet_view", state=state,
                          warnings=[str(w) for w in self.rt.arming.warnings(FLEET_VIEW)])
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)

    def save(self, alias="laptop", folder=None):
        return card.save(self.rt, alias, str(folder or self.folder), self.rt.state.meta()["generation"])

    def look(self, after=0):
        self.now += after
        answer = self.rt.tick(object())
        if answer is not DEFER:
            answer.run(lambda: None)
        return answer

    def journal(self):
        return [entry["code"] for entry in self.rt.state.journal(capability="fleet_view")]

    def stamp(self, key):
        return self.rt.state.stamped("fleet_view", key)

    def put(self, name, value):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        (self.folder / name).write_bytes(data)


class DefinitionTests(unittest.TestCase):
    def test_it_is_in_the_registry_with_what_it_departs_from_and_its_place(self):
        self.assertIs(registry.REGISTRY.get("fleet_view"), FLEET_VIEW)
        self.assertEqual(FLEET_VIEW.departs_from, ("C4", "D1", "D2", "F3"))
        self.assertLessEqual(set(FLEET_VIEW.departs_from), set(standards.DEPARTABLE))
        order = registry.SHOWN_ORDER
        self.assertEqual(order[order.index("fleet_view") - 1], "idle_update_check", "among the rare cases")
        self.assertGreater(order.index("fleet_view"), order.index("status_feed"))
        self.assertEqual(FLEET_VIEW.wordings, (WordingKey.FLEET_ALIAS, WordingKey.FLEET_FOLDER))

    def test_every_language_says_it_and_names_each_standard(self):
        for locale in LOCALES:
            own = statement.CATALOGS.catalog(locale)
            with self.subTest(locale):
                self.assertTrue(own[statement.name_key("fleet_view")].strip())
                for standard in FLEET_VIEW.departs_from:
                    self.assertIn(standard, own["statement.fleet_view.departs"])
                self.assertEqual(own["page.fleet.ignored"].count("{n}"), 1)
        for key in [key for key in statement.PAGE_KEYS if ".fleet." in key]:
            for locale in LOCALES:
                self.assertTrue(statement.CATALOGS.catalog(locale).get(key, "").strip(), (locale, key))

    def test_the_commands_are_answered_and_take_only_their_arguments(self):
        self.assertNotIn(BridgeCommand.ADVANCED_FLEET, surfaces.UNANSWERED)
        self.assertNotIn(BridgeCommand.ADVANCED_FLEET_SAVE, surfaces.UNANSWERED)
        self.assertEqual(surfaces.ARGUMENTS[BridgeCommand.ADVANCED_FLEET], frozenset())
        self.assertEqual(surfaces.ARGUMENTS[BridgeCommand.ADVANCED_FLEET_SAVE], frozenset({"alias", "folder", "generation"}))

    def test_no_network_no_process_and_no_way_to_send(self):
        """Fails with any networking, process or sending import in either file: read-only, a folder and nothing else."""
        for path in (PACKAGE / "engine" / "fleet.py", PACKAGE / "control" / "fleet.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    names.add((node.module or "").split(".")[0])
            with self.subTest(path.name):
                self.assertFalse(names & {"socket", "http", "urllib", "ssl", "ftplib", "smtplib", "subprocess", "ctypes"})
        self.assertNotIn("dispatch", (PACKAGE / "control" / "fleet.py").read_text(encoding="utf-8"))


class OffTests(FleetCase):
    """Case 1: off, nothing is written or read, and no thread."""

    def test_off_a_tick_writes_nothing_reads_nothing_and_starts_no_thread(self):
        self.on()
        self.save()
        self.rt.arming.disarm("fleet_view", actor="dashboard")
        self.rt.states(fresh=True)
        before = {thread.name for thread in threading.enumerate()}
        self.code._spawn = fleet._thread
        with patch.object(fleet, "read_peers", side_effect=AssertionError("read")), \
                patch.object(fleet, "write", side_effect=AssertionError("written")):
            self.assertIs(self.look(after=fleet.EVERY + 1), DEFER)
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertNotIn("car-fleet", {thread.name for thread in threading.enumerate()} - before)

    def test_off_the_card_answers_from_the_state_without_touching_the_folder(self):
        self.on()
        self.save()
        self.rt.arming.disarm("fleet_view", actor="dashboard")
        self.rt.states(fresh=True)
        self.put("desk.json", peer())
        with patch.object(fleet, "read_peers", side_effect=AssertionError("read")), \
                patch.object(fleet, "folder_problem", side_effect=AssertionError("looked at")):
            found = card.view(self.rt)
        self.assertEqual(found["peers"], [])
        self.assertEqual(found["state"], "off")

    def test_watched_nothing_is_written_either(self):
        self.on("shadow")
        self.rt.state.set_wording("fleet_view", WordingKey.FLEET_ALIAS, "laptop",
                                  generation=self.rt.state.meta()["generation"], actor="dashboard")
        self.rt.state.set_wording("fleet_view", WordingKey.FLEET_FOLDER, str(self.folder),
                                  generation=self.rt.state.meta()["generation"], actor="dashboard")
        self.look()
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertIn("would_have", self.journal())

    def test_paused_the_plug_asks_nothing_so_the_watcher_writes_nothing(self):
        self.assertEqual(FLEET_VIEW.points, frozenset({registry.Point.TICK}))

    def test_the_status_says_it_is_on_only_while_it_is(self):
        self.assertEqual(surfaces.fleet_view(self.rt), {})
        self.on()
        self.assertEqual(surfaces.fleet_view(self.rt), {"fleet_on": True})
        self.rt.arming.disarm("fleet_view", actor="dashboard")
        self.rt.states(fresh=True)
        self.assertEqual(surfaces.fleet_view(self.rt), {})

    def test_it_runs_on_a_thread_of_its_own_while_on_and_only_one(self):
        self.on()
        self.save()
        release = threading.Event()
        started = []

        def spawn(run):
            started.append(run)
            worker = threading.Thread(target=release.wait, daemon=True, name="car-fleet")
            worker.start()
            return worker
        self.code._spawn = spawn
        self.look()
        self.assertEqual(len(started), 1, "the pass was handed to a thread rather than run in the tick")
        self.assertEqual(list(self.folder.iterdir()), [], "the tick itself touched the folder")
        self.assertIs(self.look(after=fleet.EVERY + 1), DEFER, "never a second pass beside one that hangs")
        self.assertEqual(len(started), 1)
        release.set()


class WriteTests(FleetCase):
    """Case 2: at most every 5 minutes, atomically, the provenance, and exactly the closed keys."""

    def test_it_writes_exactly_these_keys_and_nothing_else_leaves(self):
        self.on()
        self.save()
        self.code._status = lambda now: statusfile.content(
            now=now, version="0.6.22", running=True, enabled=True, observe_only=False, engine="verified",
            rows=[SECRET_ROW], reading=None)
        self.look()
        written = json.loads((self.folder / "laptop.json").read_text(encoding="utf-8"))
        self.assertEqual(tuple(written), ("format", "alias", "edition", "written_at", "version", "watcher", "recovery",
                                          "engine", "pending", "states", "next_check_at", "usage"))
        self.assertEqual(written["format"], "codex-auto-resume/fleet/1")
        self.assertEqual((written["alias"], written["edition"], written["pending"]), ("laptop", "advanced", 1))
        text = json.dumps(written)
        for private in (THREAD, SECRET_ROW["interruption_id"], "a title nobody may see", "ExampleUser", "secret-project",
                        str(self.folder), str(self.home)):
            self.assertNotIn(json.dumps(private)[1:-1], text)

    def test_at_most_every_five_minutes(self):
        self.on()
        self.save()
        self.look()
        first = (self.folder / "laptop.json").read_bytes()
        self.look(after=fleet.EVERY - 1)
        self.assertEqual((self.folder / "laptop.json").read_bytes(), first)
        self.look(after=1)
        self.assertNotEqual((self.folder / "laptop.json").read_bytes(), first)

    def test_it_replaces_the_file_whole_and_leaves_no_temporary_behind(self):
        self.on()
        self.save()
        replaced = []
        real = os.replace

        def spy(source, target):
            if Path(target).parent != self.folder:          # what the pass read, kept in the edition's own folder
                return real(source, target)
            self.assertTrue(Path(source).name.endswith(".tmp"))
            self.assertEqual(Path(source).parent, Path(target).parent, "beside it, so the replace is atomic")
            replaced.append(json.loads(Path(source).read_text(encoding="utf-8")))
            real(source, target)
        with patch.object(os, "replace", spy):
            self.look()
        self.assertEqual(len(replaced), 1)
        self.assertEqual([path.name for path in self.folder.iterdir()], ["laptop.json"])

    def test_a_failed_replace_leaves_the_old_file_and_no_temporary(self):
        self.on()
        self.save()
        self.look()
        before = (self.folder / "laptop.json").read_bytes()
        with patch.object(os, "replace", side_effect=PermissionError()):
            self.look(after=fleet.EVERY)
        self.assertEqual((self.folder / "laptop.json").read_bytes(), before)
        self.assertEqual([path.name for path in self.folder.iterdir()], ["laptop.json"])

    def test_a_status_that_is_not_the_closed_shape_is_never_written(self):
        with self.assertRaises(ValueError):
            fleet.write(str(self.folder), "laptop", dict(peer("laptop"), title="a title"))
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_unset_nothing_is_written(self):
        self.on()
        self.look()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_the_status_comes_from_core_s_store_as_the_status_file_says_it(self):
        """The real reading, on a scratch store: closed words and counts."""
        made = fleet._status_now(self.paths, ac.NOW)
        self.assertEqual(tuple(made), statusfile.KEYS)
        self.assertEqual(made["pending"], 0)


class ConfinementTests(FleetCase):
    """Case 3: never a link, only a regular file it wrote itself, never inside the home or the Codex home."""

    def junction(self, link, target):
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        self.addCleanup(lambda: os.rmdir(link) if os.path.isdir(link) else None)

    def test_a_folder_inside_the_home_or_the_codex_home_is_refused(self):
        inside = self.paths.home / "shared"
        inside.mkdir()
        beneath = self.codex / "sessions" / "x"
        beneath.mkdir(parents=True)
        for folder in (self.paths.home, inside, self.paths.state_dir, self.codex, beneath):
            with self.subTest(folder):
                self.assertEqual(fleet.folder_problem(str(folder), self.paths), fleet.INSIDE)

    def test_a_junction_is_refused_wherever_it_points(self):
        outside = self.scratch / "elsewhere"
        outside.mkdir()
        for target in (self.paths.home, self.codex, outside):
            link = self.scratch / ("via-" + target.name)
            self.junction(link, target)
            with self.subTest(target):
                self.assertEqual(fleet.folder_problem(str(link), self.paths), fleet.LINK)

    def test_a_folder_under_a_junction_into_the_home_is_inside(self):
        (self.paths.home / "shared").mkdir()
        link = self.scratch / "via-home"
        self.junction(link, self.paths.home)
        self.assertEqual(fleet.folder_problem(str(link / "shared"), self.paths), fleet.INSIDE)

    def test_what_is_no_folder_is_refused(self):
        for bad in ("", None, 3, "relative\\path", "C:relative", "C:\\a\nb", "C:\\" + "x" * 300):
            with self.subTest(bad):
                self.assertEqual(fleet.folder_problem(bad, self.paths), fleet.INVALID)
        file = self.scratch / "a-file"
        file.write_text("x", encoding="utf-8")
        self.assertEqual(fleet.folder_problem(str(file), self.paths), fleet.INVALID)

    def test_a_fit_folder_has_no_problem(self):
        self.assertIsNone(fleet.folder_problem(str(self.folder), self.paths))

    def test_a_folder_that_became_a_junction_is_refused_on_the_next_pass(self):
        self.on()
        self.save()
        self.look()
        shutil.rmtree(self.folder)
        self.junction(self.folder, self.paths.home)
        self.look(after=fleet.EVERY)
        self.look()
        self.assertEqual(self.stamp(OptionKey.FLEET_WAITING), fleet.WAITING_WORDS.index(fleet.LINK) + 1)
        self.assertFalse((self.paths.home / "laptop.json").exists())

    def test_it_overwrites_no_file_it_did_not_write(self):
        self.on()
        self.save()
        for name, data in (("not json", b"a person's notes"), ("another format", json.dumps({"format": "other"}).encode()),
                           ("another alias", json.dumps(peer("desk")).encode()), ("too large", b" " * (fleet.LIMIT + 1))):
            with self.subTest(name):
                (self.folder / "laptop.json").write_bytes(data)
                self.assertEqual(fleet.write(str(self.folder), "laptop", peer("laptop")), fleet.NOT_OURS)
                self.assertEqual((self.folder / "laptop.json").read_bytes(), data)

    def test_it_overwrites_its_own(self):
        self.put("laptop.json", peer("laptop"))
        self.assertEqual(fleet.write(str(self.folder), "laptop", peer("laptop", now=ac.NOW + 1)), fleet.OK)

    def test_a_file_newer_than_it_wrote_is_another_pc_under_the_same_name(self):
        self.put("laptop.json", peer("laptop", now=ac.NOW + 60))
        self.assertEqual(fleet.write(str(self.folder), "laptop", peer("laptop", now=ac.NOW + 300), int(ac.NOW)),
                         fleet.NOT_OURS)
        self.assertEqual(fleet.write(str(self.folder), "laptop", peer("laptop", now=ac.NOW + 300), int(ac.NOW + 60)), fleet.OK)

    def test_it_never_writes_through_a_link(self):
        real = self.scratch / "precious.txt"
        real.write_text("precious", encoding="utf-8")
        target = self.folder / "laptop.json"
        try:
            os.symlink(real, target)
        except OSError:
            # No right to make a link here: the check is the one a link answers to.
            target.write_text(json.dumps(peer("laptop")), encoding="utf-8")
            with patch.object(fleet, "_linked", return_value=True):
                self.assertEqual(fleet.write(str(self.folder), "laptop", peer("laptop")), fleet.NOT_OURS)
            return
        self.assertEqual(fleet.write(str(self.folder), "laptop", peer("laptop")), fleet.NOT_OURS)
        self.assertEqual(real.read_text(encoding="utf-8"), "precious")

    def test_a_cloud_drive_s_placeholder_is_a_file_and_a_junction_s_tag_is_not(self):
        class Stat:
            st_mode = stat.S_IFREG
            st_file_attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT
            st_reparse_tag = 0x9000601A       # a cloud provider's placeholder
        with patch.object(os, "lstat", return_value=Stat()), patch.object(os.path, "islink", return_value=False), \
                patch.object(os.path, "isjunction", return_value=False):
            self.assertFalse(fleet._linked("x"))
            Stat.st_reparse_tag = 0xA0000003  # a mount point
            self.assertTrue(fleet._linked("x"))

    def test_a_rename_takes_only_its_own_old_file(self):
        self.on()
        self.save("old-name")
        self.look()
        self.assertTrue((self.folder / "old-name.json").exists())
        self.save("new-name")
        self.assertFalse((self.folder / "old-name.json").exists())
        self.put("kept.json", b"a person's notes")
        self.assertFalse(fleet.remove_old_name(str(self.folder), "kept"))
        self.assertTrue((self.folder / "kept.json").exists())


HOSTILE_VALUES = {
    "a field too many": lambda: dict(peer(), title="a conversation title"),
    "a field missing": lambda: {key: value for key, value in peer().items() if key != "usage"},
    "the status file's format": lambda: dict(peer(), format=statusfile.FORMAT),
    "a wrong format": lambda: dict(peer(), format="codex-auto-resume/fleet/2"),
    "an alias with a path": lambda: dict(peer(), alias="..\\..\\desk"),
    "an alias with markup": lambda: dict(peer(), alias="<b>desk</b>"),
    "an alias with a control": lambda: dict(peer(), alias="desk\n"),
    "an alias with a bidi override": lambda: dict(peer(), alias="desk\u202e"),
    "an alias too long": lambda: dict(peer(), alias="d" * 33),
    "an empty alias": lambda: dict(peer(), alias=""),
    "an alias as a list": lambda: dict(peer(), alias=["desk"]),
    "another PC's alias": lambda: dict(peer(), alias="other"),
    "a free word as the watcher": lambda: dict(peer(), watcher="<script>"),
    "a free word as recovery": lambda: dict(peer(), recovery="please click"),
    "a free word as the engine": lambda: dict(peer(), engine="x" * 40),
    "a free word as the version": lambda: dict(peer(), version="1.0 please click"),
    "a free edition": lambda: dict(peer(), edition="standard"),
    "a negative count": lambda: dict(peer(), pending=-1),
    "a huge count": lambda: dict(peer(), pending=fleet.PENDING_MOST + 1, states={"waiting_reset": fleet.PENDING_MOST + 1}),
    "a count as a word": lambda: dict(peer(), pending="3"),
    "a count as a boolean": lambda: dict(peer(), pending=True),
    "a count that disagrees": lambda: dict(peer(), pending=3),
    "an unknown state": lambda: dict(peer(), pending=1, states={"anything": 1}),
    "a time as a word": lambda: dict(peer(), written_at="today"),
    "a time before 2000": lambda: dict(peer(), written_at=1.0),
    "a time after 2100": lambda: dict(peer(), written_at=1e14),
    "a next check after 2100": lambda: dict(peer(), next_check_at=1e14),
    "usage with a free field": lambda: dict(peer(), usage={"read_at": ac.NOW, "windows": [{"account": "x"}]}),
    "a list": lambda: [peer()],
    "a number": lambda: 3,
}


class PeerTests(FleetCase):
    """Case 4: at most 16 files of at most 16 KiB, its own alias skipped, anything else ignored and counted."""

    def test_a_peer_is_read_and_its_own_alias_is_skipped(self):
        self.put("desk.json", peer("desk"))
        self.put("LAPTOP.json", peer("LAPTOP"))
        kept, ignored, held = fleet.read_peers(str(self.folder), "laptop")
        self.assertEqual([each["alias"] for each in kept], ["desk"])
        self.assertEqual((ignored, held), (0, 0))

    def test_an_alias_in_any_language_is_a_name(self):
        for alias in ("데스크탑", "الجهاز", "笔记本 2", "büro-pc"):
            self.assertTrue(fleet.alias_valid(alias), alias)

    def test_a_name_windows_will_not_give_a_file_or_with_a_space_at_its_end_is_no_alias(self):
        for alias in ("CON", "nul", "COM1", "lpt9", " desk", "desk "):
            self.assertFalse(fleet.alias_valid(alias), alias)

    def test_every_hostile_shape_is_ignored_counted_and_reaches_no_window(self):
        for name, value in HOSTILE_VALUES.items():
            with self.subTest(name):
                for old in self.folder.iterdir():
                    old.unlink()
                self.put("desk.json", value())
                kept, ignored, _held = fleet.read_peers(str(self.folder), "laptop")
                self.assertEqual((kept, ignored), ([], 1))

    def test_bytes_that_are_no_json_are_ignored(self):
        for name, raw in (("not json", b"{"), ("not utf-8", b"\xff\xfe"), ("empty", b""),
                          ("NaN", json.dumps(peer()).replace(str(peer()["written_at"]), "NaN").encode()),
                          ("deep", b"[" * 15000), ("a huge number", b'{"pending": 1' + b"0" * 9000 + b"}")):
            with self.subTest(name):
                self.put("desk.json", raw)
                self.assertEqual(fleet.read_peers(str(self.folder), "laptop")[:2], ([], 1))

    def test_too_large_is_ignored_unread(self):
        self.put("desk.json", json.dumps(peer()).encode() + b" " * fleet.LIMIT)
        with patch("builtins.open", side_effect=AssertionError("opened")):
            self.assertEqual(fleet.read_peers(str(self.folder), "laptop")[:2], ([], 1))

    def test_a_link_is_ignored(self):
        real = self.scratch / "real.json"
        real.write_text(json.dumps(peer()), encoding="utf-8")
        try:
            os.symlink(real, self.folder / "desk.json")
        except OSError:
            self.put("desk.json", peer())
            with patch.object(fleet, "_linked", return_value=True):
                self.assertEqual(fleet.read_peers(str(self.folder), "laptop")[:2], ([], 1))
            return
        self.assertEqual(fleet.read_peers(str(self.folder), "laptop")[:2], ([], 1))

    def test_a_folder_named_like_a_file_is_ignored(self):
        (self.folder / "desk.json").mkdir()
        self.assertEqual(fleet.read_peers(str(self.folder), "laptop")[:2], ([], 1))

    def test_at_most_sixteen_are_read_and_the_rest_counted(self):
        for index in range(20):
            self.put("pc-%02d.json" % index, peer("pc-%02d" % index))
        kept, ignored, _held = fleet.read_peers(str(self.folder), "laptop")
        self.assertEqual(len(kept), 16)
        self.assertEqual(ignored, 4)
        self.assertEqual(kept[0]["alias"], "pc-00")

    def test_other_files_are_not_looked_at(self):
        self.put("notes.txt", b"x")
        self.put("fleet-123.tmp", b"x")
        self.assertEqual(fleet.read_peers(str(self.folder), "laptop"), ([], 0, 0))

    def test_ignored_files_are_told_once_not_each_pass(self):
        self.on()
        self.save()
        self.put("bad-1.json", b"{")
        self.put("bad-2.json", b"{")
        self.look()
        self.look(after=fleet.EVERY)
        self.look(after=fleet.EVERY)
        self.look(after=fleet.EVERY)
        self.assertEqual(self.journal().count("fleet.ignored"), 1)

    def test_a_thousand_junk_files_coming_and_going_write_one_line_an_hour_and_hold_no_tick(self):
        """F1 (security review 2026-11-06): with one line for each file, 1,000 junk files added and removed every ten
        minutes wrote 1,000 lines a cycle, held the tick 6-9 s, and erased the 5,000-row journal within an hour. Fails with
        the line for each file put back."""
        import time
        self.on()
        self.save()
        self.look()
        self.look(after=1)
        before = len(self.rt.state.journal(limit=5000))
        slowest = 0.0
        for _cycle in range(6):
            for index in range(1000):
                self.put("junk%04d.json" % index, b"{}")
            self.look(after=fleet.EVERY + 1)
            started = time.perf_counter()
            self.look(after=1)
            slowest = max(slowest, time.perf_counter() - started)
            for path in self.folder.glob("junk*.json"):
                path.unlink()
            self.look(after=fleet.EVERY + 1)
            self.look(after=1)
        told = self.journal().count("fleet.ignored")
        self.assertLessEqual(told, 2, "one line an hour at most, whatever the count")
        self.assertGreaterEqual(told, 1)
        self.assertLess(len(self.rt.state.journal(limit=5000)) - before, 20)
        self.assertLess(slowest, 1.0, "the tick that takes a pass up writes a few rows, never one for each file")

    def test_the_bridge_answers_only_checked_words_and_bounded_numbers(self):
        self.on()
        self.save()
        self.put("desk.json", peer("desk"))
        self.put("evil.json", dict(peer("evil"), watcher="<script>"))
        self.look()
        self.look(after=1)
        found = card.view(self.rt, now=ac.NOW)
        self.assertEqual(found["ignored"], 1)
        (row,) = found["peers"]
        self.assertEqual(set(row), {"alias", "watcher", "recovery", "pending", "seen", "written_at", "next_check_at"})
        self.assertEqual(row["alias"], "desk")
        self.assertNotIn("script", json.dumps(found))


class DashboardReadTests(FleetCase):
    """T3 (security review 2026-11-06): the Dashboard's call never waits on the synced folder."""

    def test_the_card_never_touches_the_folder_it_answers_from_the_last_pass(self):
        """Fails with the bridge reading the folder itself again."""
        self.on()
        self.save()
        self.put("desk.json", peer("desk"))
        self.look()
        self.look(after=1)
        with patch.object(fleet, "read_peers", side_effect=AssertionError("the folder was read")), \
                patch.object(fleet, "folder_problem", side_effect=AssertionError("the folder was looked at")), \
                patch.object(os, "scandir", side_effect=AssertionError("the folder was listed")):
            found = card.view(self.rt, now=ac.NOW)
        self.assertEqual([row["alias"] for row in found["peers"]], ["desk"])
        self.assertEqual(found["stand"], fleet.OK)

    def test_a_folder_that_stopped_answering_holds_no_call(self):
        self.on()
        self.save()
        self.look()
        release = threading.Event()
        self.addCleanup(release.set)
        with patch.object(fleet, "folder_problem", side_effect=lambda *a: release.wait(30)):
            done = []
            worker = threading.Thread(target=lambda: done.append(card.view(self.rt)), daemon=True)
            worker.start()
            worker.join(5)
        self.assertTrue(done, "the Dashboard's call waited on the folder")

    def test_what_the_pass_kept_is_checked_again_when_read(self):
        self.on()
        self.save()
        self.put("desk.json", peer("desk"))
        self.look()
        self.look(after=1)
        path = Path(fleet.seen_path(self.paths))
        kept = json.loads(path.read_text(encoding="utf-8"))
        kept["peers"][0]["watcher"] = "<script>"
        path.write_text(json.dumps(kept), encoding="utf-8")
        self.assertIsNone(fleet.read_seen(self.paths))
        self.assertEqual(card.view(self.rt)["peers"], [])

    def test_another_folder_forgets_what_the_last_one_showed(self):
        self.on()
        self.save()
        self.put("desk.json", peer("desk"))
        self.look()
        self.look(after=1)
        other = self.scratch / "other"
        other.mkdir()
        self.save(folder=other)
        self.assertEqual(card.view(self.rt)["peers"], [])


class TimeTests(unittest.TestCase):
    """Case 5: older than 7 days greyed; a clock that disagrees neither crashes nor shows nonsense."""

    def test_fresh(self):
        row = fleet.shown(peer(next_check_at=ac.NOW + 600), ac.NOW + 300)
        self.assertEqual((row["seen"], row["written_at"], row["next_check_at"]), ("fresh", ac.NOW, ac.NOW + 600))

    def test_a_week_is_quiet_and_a_second_more_is_old_with_no_next_check(self):
        self.assertEqual(fleet.shown(peer(), ac.NOW + fleet.STALE)["seen"], "quiet", "M14: last heard, not what it said")
        row = fleet.shown(peer(next_check_at=ac.NOW + fleet.STALE + 100), ac.NOW + fleet.STALE + 1)
        self.assertEqual((row["seen"], row["written_at"], row["next_check_at"]), ("old", ac.NOW, None))

    def test_a_clock_ahead_says_so_and_gives_no_time_of_it(self):
        row = fleet.shown(peer(next_check_at=ac.NOW + 7200), ac.NOW - fleet.CLOCK_SLACK - 1)
        self.assertEqual((row["seen"], row["written_at"], row["next_check_at"]), ("clock", None, None))

    def test_a_little_ahead_is_no_clock_trouble(self):
        self.assertEqual(fleet.shown(peer(), ac.NOW - fleet.CLOCK_SLACK)["seen"], "fresh")

    def test_a_next_check_in_the_past_or_absurdly_far_on_is_not_shown(self):
        self.assertIsNone(fleet.shown(peer(next_check_at=ac.NOW - 1), ac.NOW)["next_check_at"])
        self.assertIsNone(fleet.shown(peer(next_check_at=ac.NOW + fleet.NEXT_MOST + 1), ac.NOW)["next_check_at"])

    def test_this_pc_s_own_time_out_of_range_costs_nothing_but_the_next_check(self):
        made = dict(status(), next_check_at=1.0)
        self.assertIsNone(fleet.document(made, "laptop")["next_check_at"])


class WaitingTests(FleetCase):
    """Case 6: a folder gone or a file held waits and says so, no loop, no storm; off leaves its file and says so."""

    def test_a_folder_that_vanished_waits_tries_once_each_five_minutes_and_journals_once(self):
        self.on()
        self.save()
        self.look()
        shutil.rmtree(self.folder)
        tries = []
        real = fleet.folder_problem

        def counted(*arguments):
            tries.append(1)
            return real(*arguments)
        with patch.object(fleet, "folder_problem", counted):
            for _ in range(5):
                self.look(after=60)         # inside five minutes: nothing more
            self.assertEqual(len(tries), 1)
            for _ in range(3):
                self.look(after=fleet.EVERY)
        self.look()
        self.assertEqual(len(tries), 4)
        self.assertEqual(self.stamp(OptionKey.FLEET_WAITING), fleet.WAITING_WORDS.index(fleet.MISSING) + 1)
        self.assertEqual(self.journal().count("fleet.waiting"), 1)
        self.assertEqual(card.view(self.rt)["stand"], fleet.MISSING)

    def test_it_comes_back_by_itself(self):
        self.on()
        self.save()
        self.look()
        shutil.rmtree(self.folder)
        self.look(after=fleet.EVERY)
        self.look()
        self.folder.mkdir()
        self.look(after=fleet.EVERY)
        self.look()
        self.assertTrue((self.folder / "laptop.json").exists())
        self.assertIsNone(self.stamp(OptionKey.FLEET_WAITING))
        self.assertEqual(card.view(self.rt)["stand"], fleet.OK)
        self.assertEqual([code for code in self.journal() if code.startswith("fleet.")],
                         ["fleet.wrote", "fleet.waiting", "fleet.wrote"])

    def test_a_held_file_waits_and_says_so(self):
        self.on()
        self.save()
        self.look()
        with patch.object(os, "replace", side_effect=PermissionError()):
            self.look(after=fleet.EVERY)
            self.look()
        self.assertEqual(self.stamp(OptionKey.FLEET_WAITING), fleet.WAITING_WORDS.index(fleet.HELD) + 1)
        self.assertEqual(self.journal().count("fleet.waiting"), 1)
        self.assertEqual(card.view(self.rt)["stand"], fleet.HELD)

    def test_a_peer_held_by_a_sync_tool_is_passed_over_not_ignored(self):
        self.put("desk.json", peer("desk"))
        with patch.object(fleet, "_read_one", side_effect=PermissionError()):
            self.assertEqual(fleet.read_peers(str(self.folder), "laptop"), ([], 0, 1))

    def test_a_pass_never_raises(self):
        self.on()
        self.save()
        self.code._status = lambda now: 1 / 0
        self.look()
        self.look()
        self.assertEqual(self.stamp(OptionKey.FLEET_WAITING), fleet.WAITING_WORDS.index(fleet.HELD) + 1)
        self.assertNotIn("tripped", self.journal())

    def test_turned_off_its_file_stays_and_every_language_says_so(self):
        self.on()
        self.save()
        self.look()
        self.rt.arming.disarm("fleet_view", actor="dashboard")
        self.rt.states(fresh=True)
        self.assertTrue((self.folder / "laptop.json").exists())
        english = statement.CATALOGS.catalog("en")
        self.assertIn("stays in the folder", english["statement.fleet_view.stop"])
        self.assertIn("stays in the folder", english["page.fleet.off_note"])


class WordingTests(FleetCase):
    """Case 8: the alias and the folder are `wordings`: text, checked, never logged."""

    def test_they_are_kept_as_wordings(self):
        self.on()
        self.assertTrue(self.save()["done"])
        self.assertEqual(self.rt.state.wordings("fleet_view"),
                         {"fleet_alias": "laptop", "fleet_folder": str(self.folder)})

    def test_neither_reaches_a_journal_a_status_or_a_log(self):
        self.on()
        self.save("Very-Private-Name")
        self.look()
        self.look(after=fleet.EVERY)
        lines = json.dumps(self.rt.state.journal(), default=str)
        self.assertNotIn("Very-Private-Name", lines)
        self.assertNotIn(self.folder.name, lines)
        self.assertEqual(surfaces.fleet_view(self.rt), {"fleet_on": True})

    def test_the_general_wording_command_cannot_keep_them_unchecked(self):
        """Fails with the guard in arming.set_wording gone: a word of anything would go round the checks."""
        self.on()
        for key in (WordingKey.FLEET_ALIAS, WordingKey.FLEET_FOLDER):
            found = self.rt.arming.set_wording("fleet_view", key, "..\\..\\evil",
                                               generation=self.rt.state.meta()["generation"], actor="dashboard")
            self.assertEqual(found["refusal"], Refusal.WORDING_INVALID)
        self.assertEqual(self.rt.state.wordings("fleet_view"), {})

    def test_save_refuses_what_may_not_be_kept(self):
        self.on()
        found = self.save("no/slashes")
        self.assertEqual((found["refusal"], found["problem"]), (Refusal.WORDING_INVALID, "alias"))
        found = self.save("laptop", self.paths.home)
        self.assertEqual((found["refusal"], found["problem"]), (Refusal.WORDING_INVALID, fleet.INSIDE))
        self.assertEqual(self.rt.state.wordings("fleet_view"), {})

    def test_save_refuses_off_and_a_stale_generation(self):
        self.assertEqual(self.save()["refusal"], Refusal.NOT_ON)
        self.on()
        self.assertEqual(card.save(self.rt, "laptop", str(self.folder), -1)["refusal"], Refusal.STALE_GENERATION)

    def test_a_save_asks_for_a_write_at_the_next_tick(self):
        self.on()
        self.save()
        self.look()
        self.save("laptop")
        self.assertIsNone(self.stamp(OptionKey.LAST_FLEET_WRITE))
        self.assertIsNot(self.rt.tick(object()), DEFER)


class ReadOnlyTests(unittest.TestCase):
    """Case 7: no action on a peer, anywhere."""

    def test_the_bridge_has_two_commands_for_it_neither_naming_a_peer(self):
        named = [command for command in BridgeCommand if "fleet" in command]
        self.assertEqual(sorted(named), ["advanced-fleet", "advanced-fleet-save"])
        for command in named:
            self.assertFalse(surfaces.ARGUMENTS[command] & {"peer", "pc", "target", "file"})

    def test_a_peer_s_file_is_opened_for_reading_alone(self):
        source = (PACKAGE / "engine" / "fleet.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        reader = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_read_one")
        text = ast.get_source_segment(source, reader)
        self.assertIn('open(path, "rb")', text)
        for write in ("unlink", "replace", "remove", '"w'):
            self.assertNotIn(write, text)


# ------------------------------------------------------------------ the owner, 2026-11-07: a network share may be the folder
SHARES = ("\\\\server\\share\\synced", "//server/share/synced", "\\\\server\\share", "\\\\server\\share\\",
          "\\\\nas-1\\Shared Docs\\pcs")
DEVICES = ("\\\\?\\C:\\synced", "\\\\.\\C:\\synced", "\\\\?\\UNC\\server\\share\\synced", "//?/C:/synced", "//./C:/synced",
           "\\\\.\\pipe\\synced", "\\\\server", "\\\\server\\", "\\\\\\server\\share", "\\\\server\\\\share", "\\\\ \\share\\x",
           "\\\\..\\share\\x")


class ShareTests(FleetCase):
    """A share (`\\\\server\\share\\...`, `//server/share/...`, a mapped drive whose real path is one) is a folder; a device
    path is not. No share is reached: every file call a share path would make is answered here by the synced folder."""

    def standing_in(self, real=None, same=None):
        """Every call on a share path is answered by the synced folder, or by `same` for os.stat, and realpath by `real`."""
        lstat, stat_, realpath = os.lstat, os.stat, os.path.realpath

        def shared(path):
            return str(path).startswith(("\\\\", "//"))

        def fake_lstat(path, *rest, **named):
            return lstat(self.folder) if shared(path) else lstat(path, *rest, **named)

        def fake_stat(path, *rest, **named):
            if shared(path):
                return stat_(same) if same is not None else stat_(self.folder)
            return stat_(path, *rest, **named)

        def fake_realpath(path, *rest, **named):
            if real is not None and os.path.normcase(str(path)) == os.path.normcase(str(self.folder)):
                return real
            return str(path) if shared(path) else realpath(path, *rest, **named)
        for stand_in in (patch.object(os, "lstat", fake_lstat), patch.object(os, "stat", fake_stat),
                         patch.object(os.path, "realpath", fake_realpath),
                         patch.object(fleet, "_linked", lambda path: False if shared(path) else self.linked(path))):
            stand_in.start()
            self.addCleanup(stand_in.stop)

    def setUp(self):
        super().setUp()
        self.linked = fleet._linked

    def test_a_share_is_a_folder(self):
        """Fails with a share refused (fleet.NETWORK, as it was until 2026-11-07)."""
        self.standing_in()
        for folder in SHARES:
            with self.subTest(folder):
                self.assertIsNone(fleet.folder_problem(folder, self.paths))

    def test_a_device_path_is_refused_without_a_file_call(self):
        """Fails with `\\\\?\\`, `\\\\.\\` or `\\\\?\\UNC\\` written by hand taken for a folder, or looked at to decide."""
        with patch.object(os, "lstat", side_effect=AssertionError("looked at")), \
                patch.object(os, "stat", side_effect=AssertionError("looked at")):
            for folder in DEVICES:
                with self.subTest(folder):
                    self.assertEqual(fleet.folder_problem(folder, self.paths), fleet.INVALID)

    def test_a_mapped_drive_whose_real_path_is_a_share_is_a_folder(self):
        """Fails with a drive refused because its real path is a share's."""
        self.standing_in(real="\\\\server\\share\\synced")
        self.assertIsNone(fleet.folder_problem(str(self.folder), self.paths))

    def test_a_share_that_is_the_codex_home_by_another_name_is_inside(self):
        """An administrative share names this PC's own drive: what the file system says it is decides, not its name."""
        self.standing_in(same=self.codex)
        self.assertEqual(fleet.folder_problem("\\\\localhost\\c$\\somewhere\\.codex", self.paths), fleet.INSIDE)

    def test_the_other_checks_still_hold_on_a_share(self):
        self.standing_in()
        with patch.object(fleet, "_linked", return_value=True):
            self.assertEqual(fleet.folder_problem("\\\\server\\share\\x", self.paths), fleet.LINK)
        file = self.scratch / "a-file"
        file.write_text("x", encoding="utf-8")
        with patch.object(os, "lstat", lambda path, *rest, **named: os.stat(file)):
            self.assertEqual(fleet.folder_problem("\\\\server\\share\\x", self.paths), fleet.INVALID)
        with patch.object(os, "lstat", side_effect=FileNotFoundError()):
            self.assertEqual(fleet.folder_problem("\\\\server\\share\\x", self.paths), fleet.MISSING)

    def test_save_keeps_a_share(self):
        self.on()
        self.standing_in()
        found = card.save(self.rt, "laptop", "\\\\server\\share\\synced", self.rt.state.meta()["generation"])
        self.assertTrue(found["done"], found)
        self.assertEqual(found["folder"], "\\\\server\\share\\synced")


class Blocking:
    """A share whose listing does not answer until `release` is set: os.scandir on the synced folder blocks, and each call
    is counted. Everything else is the real call."""

    def __init__(self, test, folder):
        self.folder = os.path.normcase(str(folder))
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.real = os.scandir
        test.addCleanup(self.release.set)
        stand_in = patch.object(os, "scandir", self)
        stand_in.start()
        test.addCleanup(stand_in.stop)

    def __call__(self, path=".", *rest, **named):
        if os.path.normcase(str(path)) == self.folder:
            self.calls += 1
            self.entered.set()
            self.release.wait(60)
        return self.real(path, *rest, **named)


class LateTests(FleetCase):
    """A share that stopped answering never holds the watcher's tick: past BOUND seconds the pass is given up, says LATE,
    starts nothing beside itself while held, and the next pass reads the share once it answers."""

    def setUp(self):
        super().setUp()
        self.clock = [1000.0]
        self.code._clock = lambda: self.clock[0]
        self.code._spawn = fleet._thread
        self.addCleanup(self.finish)

    def finish(self):
        worker = self.code._worker
        if worker is not None and hasattr(worker, "join"):
            worker.join(10)

    def timed(self, after=0):
        began = time.monotonic()
        answer = self.look(after)
        return answer, time.monotonic() - began

    def test_a_share_that_does_not_answer_holds_no_tick_says_late_and_starts_no_second_access(self):
        """Fails with the tick waiting on the pass, with no word for a share that did not answer in time, or with a second
        pass begun beside one still held."""
        self.on()
        self.save()
        self.put("desk.json", peer("desk"))
        share = Blocking(self, self.folder)
        threads = sum(1 for each in threading.enumerate() if each.name == "car-fleet")
        _answer, took = self.timed()
        self.assertLess(took, 1, "the tick waited on the folder")
        self.assertTrue(share.entered.wait(10), "the pass never reached the folder")
        self.assertIsNone(self.stamp(OptionKey.FLEET_WAITING), "given up before its bound")
        self.clock[0] += fleet.BOUND + 1
        answer, took = self.timed(after=1)
        self.assertIs(answer, DEFER)
        self.assertLess(took, 1)
        self.assertEqual(self.stamp(OptionKey.FLEET_WAITING), fleet.WAITING_WORDS.index(fleet.LATE) + 1)
        self.assertEqual(card.view(self.rt)["stand"], fleet.LATE)
        for _ in range(3):
            self.clock[0] += fleet.EVERY
            answer, took = self.timed(after=fleet.EVERY + 1)
            self.assertIs(answer, DEFER, "a second pass beside the one still held")
            self.assertLess(took, 1)
        self.assertEqual(share.calls, 1, "a second access to the folder while the first still hangs")
        self.assertEqual(sum(1 for each in threading.enumerate() if each.name == "car-fleet"), threads + 1)
        self.assertEqual([code for code in self.journal() if code.startswith("fleet.")], ["fleet.waiting"])

    def test_once_the_share_answers_the_next_pass_reads_it_and_the_late_one_keeps_nothing(self):
        """Fails with the given-up pass's late answer taken for the next pass's, or with no pass after it."""
        self.on()
        self.save()
        self.put("desk.json", peer("desk"))
        share = Blocking(self, self.folder)
        self.look()
        self.assertTrue(share.entered.wait(10))
        self.clock[0] += fleet.BOUND + 1
        self.look(after=1)
        share.release.set()
        self.code._worker.join(10)
        self.assertFalse(self.code._worker.is_alive())
        self.look(after=1)                         # what the late pass came to is dropped; it is not five minutes yet
        self.assertEqual(self.stamp(OptionKey.FLEET_WAITING), fleet.WAITING_WORDS.index(fleet.LATE) + 1)
        self.assertEqual(card.view(self.rt)["peers"], [], "the given-up pass kept what it read")
        self.code._spawn = inline
        self.look(after=fleet.EVERY)
        self.look()
        self.assertEqual(share.calls, 2)
        self.assertIsNone(self.stamp(OptionKey.FLEET_WAITING))
        found = card.view(self.rt)
        self.assertEqual((found["stand"], [row["alias"] for row in found["peers"]]), (fleet.OK, ["desk"]))

    def test_a_slow_pass_of_quick_accesses_is_not_late(self):
        """Each access has its bound, not the pass: files read one after another, each in time, are no LATE however long
        they take together. A tick is asked between each two, as the watcher's would be."""
        self.on()
        self.save()
        self.code._spawn = inline
        real = fleet._read_one
        asked = []

        def slow(*arguments):
            self.clock[0] += fleet.BOUND - 1
            self.code._give_up_late()
            asked.append(1)
            return real(*arguments)
        for name in ("a", "b", "c"):
            self.put(name + ".json", peer(name))
        with patch.object(fleet, "_read_one", slow):
            self.look()
        self.look()
        self.assertEqual(len(asked), 3)
        self.assertIsNone(self.stamp(OptionKey.FLEET_WAITING))
        self.assertEqual(len(card.view(self.rt)["peers"]), 3)


class BoundedSaveTests(FleetCase):
    """The Dashboard's save looks at the folder on a thread of its own, waited on BOUND seconds at most, one at a time."""

    def test_a_share_that_does_not_answer_is_answered_late_and_held_once(self):
        """Fails with the save waiting on the folder, or starting a second look beside one still held."""
        self.on()
        release = threading.Event()
        self.addCleanup(release.set)
        looks = []

        def hanging(*arguments):
            looks.append(1)
            release.wait(60)
            return None
        with patch.object(fleet, "BOUND", 0.3), patch.object(fleet, "folder_problem", hanging):
            for _ in range(2):
                began = time.monotonic()
                found = self.save(folder="\\\\server\\share\\synced")
                self.assertLess(time.monotonic() - began, 2, "the save waited on the folder")
                self.assertEqual((found["done"], found.get("problem")), (False, fleet.LATE))
            self.assertEqual(len(looks), 1, "a second look beside the one still held")
            release.set()
            for each in threading.enumerate():
                if each.name == "car-fleet-access":
                    each.join(10)
        self.assertTrue(self.save()["done"])

    def test_what_the_look_raised_reaches_the_save(self):
        with patch.object(fleet, "folder_problem", side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                fleet.bounded(lambda: fleet.folder_problem("C:\\x", self.paths))
        self.assertEqual(fleet.bounded(lambda: 7), 7)

    def test_the_page_and_every_language_name_the_word(self):
        english = statement.CATALOGS.catalog("en")
        self.assertIn("did not answer in time", english["page.fleet.stand.late"])
        self.assertIn("page.fleet.stand.late", statement.PAGE_KEYS)
        for locale in LOCALES:
            with self.subTest(locale):
                catalog = json.loads((PACKAGE / "locales" / (locale + ".json")).read_text(encoding="utf-8"))
                self.assertTrue(catalog["page.fleet.stand.late"].strip())
        self.assertIn("network share", english["statement.fleet_view.does"])
        self.assertIn("anyone who can read that share", english["statement.fleet_view.risks"])
        self.assertNotIn("network path", english["page.fleet.stand.refused"])


if __name__ == "__main__":
    unittest.main()

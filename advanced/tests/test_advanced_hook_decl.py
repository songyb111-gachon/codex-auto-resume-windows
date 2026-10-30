"""Continue inside the turn (stop_hook_continuation, v0.6.20): the Stop hook's declaration (control/hookplugin.py) -
written into this product's own plugin copies only while the capability is on, and removed when it is not.

Held here, on a scratch installation home and a scratch Codex home only: it is written into the installation's root and
each advanced copy Codex keeps of this plugin, and nowhere else - not Codex's config.toml, not another plugin, not a
standard copy; it is removed at a turn-off, at every capability off, at an edition change and at a tripwire, and written
back at the capability's tick while on (a Repair replaced the files); a file someone else wrote is never replaced or
removed; the one write and the one removal are the seam a test replaces, and a format MHK settles differently changes
only FORMAT; and nothing anywhere in the product names a way past Codex's hook trust.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume_advanced.control import hookplugin  # noqa: E402
from codex_auto_resume_advanced.hook import format as hookformat  # noqa: E402
from codex_auto_resume_advanced.registry import STOP_HOOK  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, OffReason  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CAPABILITY = "stop_hook_continuation"
CACHE = ("plugins", "cache", "codex-auto-resume-windows", "codex-auto-resume")


def plugin(folder, advanced=True):
    (folder / ".codex-plugin").mkdir(parents=True)
    (folder / ".codex-plugin" / "plugin.json").write_text('{"name": "codex-auto-resume"}\n', encoding="utf-8")
    (folder / "src" / ("codex_auto_resume_advanced" if advanced else "codex_auto_resume")).mkdir(parents=True)
    return folder


def snapshot(folder) -> dict:
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(Path(folder).rglob("*")) if path.is_file()}


class Scratch(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        where = Path(temporary.name)
        self.paths = config.Paths(where / "home")
        self.installation = plugin(where / "home" / "app")
        self.codex_home = where / "codex-home"
        self.copy = plugin(self.codex_home.joinpath(*CACHE, "0.6.20"))
        self.standard_copy = plugin(self.codex_home.joinpath(*CACHE, "0.6.18"), advanced=False)
        plugin(self.codex_home / "plugins" / "cache" / "someone-else" / "their-plugin" / "1.0")
        (self.codex_home / "config.toml").write_text("[features]\nplugin_hooks = true\n", encoding="utf-8")
        self.before = snapshot(self.codex_home)

    def declared(self, root):
        path = root.joinpath(*hookformat.FORMAT.file)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


class DeclarationTests(Scratch):
    def test_written_into_our_two_roots_and_nowhere_else(self):
        self.assertEqual(hookplugin.write(self.paths, self.codex_home), 2)
        expected = hookformat.declaration(str(hookplugin.launcher(self.paths)))
        self.assertEqual(self.declared(self.installation), expected)
        self.assertEqual(self.declared(self.copy), expected)
        changed = {name for name, data in snapshot(self.codex_home).items() if self.before.get(name) != data}
        self.assertEqual(changed, {"/".join(CACHE + ("0.6.20",) + hookformat.FORMAT.file)})
        self.assertIsNone(self.declared(self.standard_copy), "a standard copy has no handler to run")
        self.assertTrue(hookplugin.present(self.paths, self.codex_home))
        self.assertEqual(hookplugin.write(self.paths, self.codex_home), 0, "already as it should be")

    def test_removed_whole_when_off(self):
        hookplugin.follow(self.paths, self.codex_home, True)
        self.assertEqual(hookplugin.follow(self.paths, self.codex_home, False), 2)
        self.assertIsNone(self.declared(self.installation))
        self.assertEqual(snapshot(self.codex_home), self.before, "Codex's home exactly as it was")
        self.assertFalse(self.installation.joinpath(hookformat.FORMAT.file[0]).exists(), "its folder too")

    def test_a_file_someone_else_wrote_is_never_replaced_or_removed(self):
        theirs = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "C:\\tools\\mine.exe"}]}]}}
        path = self.copy.joinpath(*hookformat.FORMAT.file)
        path.parent.mkdir()
        path.write_text(json.dumps(theirs), encoding="utf-8")
        hookplugin.follow(self.paths, self.codex_home, True)
        self.assertEqual(self.declared(self.copy), theirs)
        hookplugin.follow(self.paths, self.codex_home, False)
        self.assertEqual(self.declared(self.copy), theirs)

    def test_the_one_write_and_the_one_removal_are_the_seam(self):
        written, removed = [], []
        with patch.object(hookplugin, "WRITER", lambda path, document: written.append((Path(path), document))), \
                patch.object(hookplugin, "REMOVER", lambda path: removed.append(Path(path))):
            hookplugin.follow(self.paths, self.codex_home, True)
            # Resolved on both sides: CI's TEMP is in 8.3 form (RUNNER~1) where the product names the long one.
            self.assertEqual(sorted(path.resolve() for path, _ in written),
                             sorted(root.joinpath(*hookformat.FORMAT.file).resolve() for root in (self.installation, self.copy)))
            self.assertEqual(snapshot(self.codex_home), self.before, "nothing written past the seam")
            hookplugin.write_declaration(self.copy.joinpath(*hookformat.FORMAT.file), written[0][1])
            hookplugin.follow(self.paths, self.codex_home, False)
            self.assertEqual([path.resolve() for path in removed], [self.copy.joinpath(*hookformat.FORMAT.file).resolve()])

    def test_another_format_changes_only_the_constant(self):
        """What MHK may settle differently - a file the manifest names, the command inside the plugin, the installation's
        root alone - is FORMAT's, and the writer follows it."""
        other = dataclasses.replace(hookformat.FORMAT, manifest_key="hooks", command="contained",
                                    roots=("installation",), file=("hooks.json",))
        self.assertEqual(hookplugin.follow(self.paths, self.codex_home, True, other), 1)
        written = json.loads(self.installation.joinpath("hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(hookformat.commands_in(written, other), ["./hook/codex-auto-resume-hook.exe"])
        manifest = json.loads(self.installation.joinpath(".codex-plugin", "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["hooks"], "./hooks.json")
        self.assertEqual(snapshot(self.codex_home), self.before)
        hookplugin.follow(self.paths, self.codex_home, False, other)
        manifest = json.loads(self.installation.joinpath(".codex-plugin", "plugin.json").read_text(encoding="utf-8"))
        self.assertNotIn("hooks", manifest)
        self.assertFalse(self.installation.joinpath("hooks.json").exists())

    def test_a_target_outside_its_root_is_refused(self):
        escaping = dataclasses.replace(hookformat.FORMAT, file=("..", "..", "escaped.json"))
        self.assertIsNone(hookplugin.target(self.installation, escaping))
        self.assertEqual(hookplugin.write(self.paths, self.codex_home, escaping), 0)
        self.assertFalse((self.installation.parent.parent / "escaped.json").exists())


class FollowsTheCapabilityTests(ac.AdvancedCase):
    """Arming moves it: turned on, the declaration stands; off, every capability off, an edition change or a tripwire,
    it is gone; and the capability's tick puts it back while on."""

    def setUp(self):
        super().setUp()
        where = Path(self.home).parent
        plugin(Path(self.home) / "app")
        self.codex_home = where / "codex-home"
        plugin(self.codex_home.joinpath(*CACHE, "0.6.20"))
        (self.codex_home / "config.toml").write_text("[features]\nplugin_hooks = true\n", encoding="utf-8")
        self.before = snapshot(self.codex_home)
        catalog = where / "hook-catalogs"
        catalog.mkdir()
        self.catalogs = ac.catalogs(catalog, STOP_HOOK)
        environment = patch.dict(os.environ, {"CODEX_HOME": str(self.codex_home)})
        environment.start()
        self.addCleanup(environment.stop)
        self.runtime = self.runtime(STOP_HOOK)

    def turn_on(self):
        runtime = self.runtime
        result = runtime.arming.arm(CAPABILITY, state="armed", revision=STOP_HOOK.revision,
                                    generation=runtime.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=list(runtime.arming.warnings(STOP_HOOK)), actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.assertTrue(hookplugin.present(self.paths, self.codex_home))

    def test_turned_on_it_stands_and_turned_off_it_goes(self):
        self.assertFalse(hookplugin.present(self.paths, self.codex_home))
        self.turn_on()
        self.runtime.arming.disarm(CAPABILITY, actor=Actor.DASHBOARD)
        self.assertFalse(hookplugin.present(self.paths, self.codex_home))
        self.assertEqual(snapshot(self.codex_home), self.before)

    def test_every_capability_off_an_edition_change_and_a_tripwire_take_it_away(self):
        for off in (lambda: self.runtime.arming.all_off(actor=Actor.DASHBOARD),
                    lambda: self.runtime.arming.edition_entered(),
                    lambda: self.runtime.arming.trip(CAPABILITY, OffReason.HOOK_EXCEPTION)):
            with self.subTest(off):
                self.turn_on()
                off()
                self.assertFalse(hookplugin.present(self.paths, self.codex_home))

    def test_watching_writes_nothing(self):
        runtime = self.runtime
        result = runtime.arming.arm(CAPABILITY, state="shadow", revision=STOP_HOOK.revision,
                                    generation=runtime.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=list(runtime.arming.warnings(STOP_HOOK)), actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.assertFalse(hookplugin.present(self.paths, self.codex_home), "a hook that only watched would still act")

    def test_its_tick_puts_it_back_after_a_repair(self):
        self.turn_on()
        hookplugin.remove(self.paths, self.codex_home)                  # what a Repair's fresh files look like
        code = ac.code_of(self.runtime, CAPABILITY)
        code.tick({})
        self.assertTrue(hookplugin.present(self.paths, self.codex_home))


class NoBypassTests(unittest.TestCase):
    def test_nothing_names_a_way_past_codex_s_hook_trust(self):
        """Codex's own trust prompt gates the hook; the product never bypasses it or tells anyone how."""
        found = []
        for tree in ("src", "advanced/src", "gui", "advanced/gui", "build", "scripts", "skills", "advanced/skills"):
            for path in sorted((ROOT / tree).rglob("*")):
                if path.is_file() and path.suffix in (".py", ".cs", ".ps1", ".json", ".md", ".cmd", ".txt", ".toml"):
                    text = path.read_text(encoding="utf-8", errors="replace").lower()
                    if "bypass-hook-trust" in text or "bypass_hook_trust" in text or "hook-trust-bypass" in text:
                        found.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()

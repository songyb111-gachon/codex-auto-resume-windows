"""The Stop hook's declaration (car-adv `control/hookplugin.rs`, `hook/format.rs`) held to the tag's.

Never a real plugin copy: every tree is a scratch folder the script builds - the installation's `app` and the copies Codex
keeps under `plugins/cache/<marketplace>/<plugin>/<version>` - twice, one for the tag and one for car-adv, and each runs the
same program of `write`, `remove`, `present`, `roots`, `target`, `follow` and edits of the tree between them. Both answer
each step and leave a tree, and both must be the same: every file's bytes, every folder.

The trees: complete, with one root or none, copies without the advanced package or its manifest, a cache or an installation
or a hooks folder that is a junction, and a declaration file that is ours (absolute or contained), someone else's, mixed,
not JSON, an empty hooks object, a folder - written, kept, replaced and removed under every format the tag can be built
with (both commands, one root or both, a manifest key).
"""
from __future__ import annotations

import unittest

from rustdiff import advreport

RECORD = []

SCRIPT = r'''
import dataclasses, shutil, sys
from codex_auto_resume import config
from codex_auto_resume_advanced.control import hookplugin
from codex_auto_resume_advanced.hook import format as hookformat

FORMATS = {
    "shipped": hookformat.FORMAT,
    "contained": dataclasses.replace(hookformat.FORMAT, command="contained"),
    "manifest": dataclasses.replace(hookformat.FORMAT, manifest_key="hooks"),
    "contained_manifest": dataclasses.replace(hookformat.FORMAT, command="contained", manifest_key="hooks"),
    "installation": dataclasses.replace(hookformat.FORMAT, roots=("installation",)),
    "copy": dataclasses.replace(hookformat.FORMAT, roots=("codex_copy",)),
}
OURS_ABSOLUTE = "<home>\\app\\hook\\codex-auto-resume-hook.exe"
SCRATCH_ROOT = Path(SCRATCH)
COUNT = [0]

def plugin(root, manifest=True, package=True):
    root.mkdir(parents=True, exist_ok=True)
    if manifest:
        (root / ".codex-plugin").mkdir(exist_ok=True)
        (root / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "codex-auto-resume", "version": "0.6.26"}), encoding="utf-8")
    if package:
        (root / "src" / "codex_auto_resume_advanced").mkdir(parents=True, exist_ok=True)

def copy_root(base, version):
    return base / "codex" / "plugins" / "cache" / hookplugin.MARKETPLACE / hookplugin.PLUGIN / version

def build(kind):
    COUNT[0] += 1
    base = SCRATCH_ROOT / ("tree-%d" % COUNT[0])
    base.mkdir()
    (base / "product").mkdir()
    app = base / "product" / "app"
    if kind in ("complete", "file_ours", "file_ours_contained", "file_foreign", "file_bad", "file_empty", "file_mixed", "file_dir", "file_other_event", "same_version_twice"):
        plugin(app)
        plugin(copy_root(base, "0.6.26"))
        plugin(copy_root(base, "0.6.25"))
        (copy_root(base, "0.6.24")).mkdir(parents=True)
        plugin(copy_root(base, "0.6.23"), manifest=False)
        plugin(copy_root(base, "0.6.22"), package=False)
        plugin(copy_root(base, "0.6.21B"))
    elif kind == "installation":
        plugin(app)
    elif kind == "copies":
        plugin(copy_root(base, "0.6.26"))
    elif kind == "junction_cache":
        plugin(app)
        plugin(base / "elsewhere" / "0.6.26")
        cache = copy_root(base, "0.6.26").parent
        cache.parent.mkdir(parents=True)
        import _winapi
        _winapi.CreateJunction(str(base / "elsewhere"), str(cache))
    elif kind == "junction_app":
        plugin(base / "real-app")
        import _winapi
        _winapi.CreateJunction(str(base / "real-app"), str(app))
        plugin(copy_root(base, "0.6.26"))
    elif kind == "junction_hooks":
        plugin(app)
        (base / "elsewhere").mkdir()
        import _winapi
        _winapi.CreateJunction(str(base / "elsewhere"), str(app / "hooks"))
        plugin(copy_root(base, "0.6.26"))
    elif kind == "none":
        pass
    hooks = [app / "hooks" / "hooks.json", copy_root(base, "0.6.26") / "hooks" / "hooks.json", copy_root(base, "0.6.25") / "hooks" / "hooks.json"]
    home = str(base / "product").replace("/", "\\")
    absolute = home + "\\app\\hook\\codex-auto-resume-hook.exe"
    def stand(path, text):
        if path.parent.exists() or kind.startswith("file"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    def declared(command, event="Stop"):
        return json.dumps({"hooks": {event: [{"hooks": [{"type": "command", "command": command, "timeout": 10}]}]}})
    if kind == "file_ours":
        stand(hooks[0], declared(absolute)); stand(hooks[1], declared(absolute).replace('"timeout": 10', '"timeout": 99'))
    elif kind == "file_ours_contained":
        stand(hooks[0], declared("./hook/codex-auto-resume-hook.exe")); stand(hooks[1], declared(absolute))
    elif kind == "file_foreign":
        stand(hooks[0], declared("C:\\tools\\other.exe")); stand(hooks[1], declared(absolute)); stand(hooks[2], declared("x", "PreToolUse"))
    elif kind == "file_bad":
        stand(hooks[0], "not json"); stand(hooks[1], "[1, 2]"); stand(hooks[2], "")
    elif kind == "file_empty":
        stand(hooks[0], '{"hooks": {}}'); stand(hooks[1], "{}"); stand(hooks[2], '{"hooks": {"Stop": []}}')
    elif kind == "file_mixed":
        stand(hooks[0], json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": absolute}, {"type": "command", "command": "C:\\tools\\other.exe"}]}]}}))
        stand(hooks[1], json.dumps({"hooks": {"Stop": [{"hooks": [{"command": absolute}]}], "Other": [{"hooks": [{"command": "./hook/codex-auto-resume-hook.exe"}]}]}}))
        stand(hooks[2], json.dumps({"hooks": {"Stop": [{"hooks": [{"command": 5}]}]}}))
    elif kind == "file_dir":
        hooks[0].mkdir(parents=True)
    elif kind == "file_other_event":
        stand(hooks[0], declared(absolute, "SessionStart")); stand(hooks[1], "\ufeff" + declared(absolute))
    return base

def make_case(kind, name, codex, program):
    reference_base, rust_base = build(kind), build(kind)
    tree_a = str(reference_base)
    home = reference_base / "product"
    paths = config.Paths(home)
    codex_home = (reference_base / "codex") if codex else None
    fmt = FORMATS[name]
    def shown(path):
        return str(path).replace(tree_a, "<base>")
    def dump(base):
        files, folders = {}, []
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(base).as_posix()
            if path.is_dir():
                folders.append(relative)
            else:
                files[relative] = path.read_bytes().decode("utf-8", "replace").replace(
                    tree_a.replace("\\", "\\\\"), "<escaped>").replace(tree_a, "<base>")
        return {"files": dict(sorted(files.items())), "folders": sorted(folders)}
    steps = []
    for step in program:
        kind_of = step[0]
        try:
            if kind_of == "write":
                steps.append(hookplugin.write(paths, codex_home, fmt))
            elif kind_of == "remove":
                steps.append(hookplugin.remove(paths, codex_home, fmt))
            elif kind_of == "present":
                steps.append(hookplugin.present(paths, codex_home, fmt))
            elif kind_of == "roots":
                steps.append([shown(root) for root in hookplugin.roots(paths, codex_home, fmt)])
            elif kind_of == "target":
                found = hookplugin.target(reference_base / step[1], fmt)
                steps.append(None if found is None else shown(found))
            elif kind_of == "command":
                steps.append(hookplugin.command(paths, fmt).replace(tree_a, "<base>"))
            elif kind_of == "follow":
                steps.append(hookplugin.follow(paths, codex_home, step[1], fmt))
            elif kind_of == "put":
                path = reference_base / step[1]
                if step[2] is None:
                    path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(step[2], encoding="utf-8")
                steps.append(None)
            elif kind_of == "dump":
                steps.append(dump(reference_base))
        except OSError:
            steps.append({"error": "OSError"})
    CASES.append(["plugin.run", str(rust_base), str(rust_base / "codex") if codex else None, name, program])
    RESULTS.append({"ok": {"steps": steps, "tree": dump(reference_base)}})

KINDS = ["complete", "installation", "copies", "none", "junction_cache", "junction_app", "junction_hooks", "file_ours", "file_ours_contained",
         "file_foreign", "file_bad", "file_empty", "file_mixed", "file_dir", "file_other_event"]
PROGRAMS = [
    [["roots"], ["present"], ["command"], ["write"], ["write"], ["present"], ["dump"], ["remove"], ["remove"], ["present"]],
    [["follow", True], ["follow", True], ["follow", False], ["follow", False]],
    [["write"], ["put", "product/app/hooks/hooks.json", '{"hooks": {"Stop": [{"hooks": [{"command": "C:\\\\x.exe"}]}]}}'], ["write"], ["remove"], ["present"],
     ["put", "product/app/hooks/hooks.json", None], ["remove"], ["write"]],
    [["target", "product/app"], ["target", "codex/plugins/cache/codex-auto-resume-windows/codex-auto-resume/0.6.26"], ["target", "nowhere"], ["target", "product"]],
]
for name in FORMATS:
    for kind in KINDS:
        for codex in (True, False):
            for program in (PROGRAMS if name == "shipped" else PROGRAMS[:2] if name == "manifest" else PROGRAMS[:1]):
                if codex or name in ("shipped", "manifest"):
                    make_case(kind, name, codex, program)
finish()
'''


class PluginDiff(advreport.ReportDiff):
    EXAMPLE = "advhook"

    def test_the_declaration_written_followed_and_removed(self):
        found = self.family(SCRIPT, label="hook-plugin", expect_cases=200, chunk=100)
        written = [step for result in found["results"] for step in result["ok"]["steps"] if isinstance(step, int) and step > 0]
        self.assertTrue(written)
        RECORD.append("hook plugin: %d programs over %d trees and 6 formats - write, remove, present, roots, target, follow, "
                      "foreign and damaged declarations, junctions; every step and the whole tree equal"
                      % (len(found["cases"]), len(set(case[1] for case in found["cases"]))))


if __name__ == "__main__":
    unittest.main()

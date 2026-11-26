"""The watcher host's contracts with car_core.dll (v0.6.27, P6 step 0): the C# half of the done-check.

rust/crates/car-host/src/abi.rs makes the six exports (export_core!) and holds the closed event and action tables;
gui/HostCore.cs imports the six and gui/ISurfaces.cs names the tables for the surfaces. This module holds the C# to
the Rust, read from the sources: HostCore.cs imports exactly the six, each with the C# type of abi.rs's Rust type;
no other C# file imports car_core.dll; ISurfaces.cs's names are abi.rs's, word for word and in order, and the popup's
calls are CONTROL_CALLS. The two files compile alone with the in-box csc (they are not on gui/window.sources, so
nothing else compiles them until gui/host.sources, S6.2b). Nothing here loads the DLL or shows a window.
car-host's tests/abi_exports.rs is the Rust half: the built DLL's PE export table and the six's types.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import guiscan

ROOT = Path(__file__).resolve().parents[1]
ABI = ROOT / "rust" / "crates" / "car-host" / "src" / "abi.rs"
HOST_CORE = ROOT / "gui" / "HostCore.cs"
SURFACES = ROOT / "gui" / "ISurfaces.cs"
MODEL = ROOT / "src" / "codex_auto_resume" / "ui" / "popup" / "model.py"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"

# The C# type of each Rust type the exports use: a request is a byte[] the marshaller pins for the call, a length a
# size_t, the reply's length an out size_t, a reply (and car_free's buffer) a raw pointer.
PARAMETER = {"*const u8": "byte[]", "usize": "UIntPtr", "*mut usize": "out UIntPtr", "u32": "uint",
             "*mut u8": "IntPtr"}
RESULT = {"*mut u8": "IntPtr", "i32": "int", None: "void"}

EXPORT = re.compile(r'#\[unsafe\(no_mangle\)\]\s*pub (?:unsafe )?extern "C" fn (\w+)\(([^)]*)\)(?:\s*->\s*([^{]+?))?\s*\{')
IMPORT = re.compile(r'\[DllImport\(([^\]]*)\)\]\s*private static extern (\w+) (\w+)\(([^)]*)\);')


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def rust_list(text: str, name: str) -> list[str]:
    found = re.search(r"pub const %s: \[&str; \d+\] = \[(.*?)\];" % name, text, re.S)
    if not found:
        raise AssertionError("abi.rs has no %s" % name)
    return re.findall(r'"([^"]*)"', found.group(1))


def rust_names(text: str, enum: str) -> list[str]:
    """`<enum>::X => "word"`: the words of its `name()`, in order (the only arms of that shape)."""
    return re.findall(r'%s::\w+ => "([a-z_]+)"' % enum, text)


def rust_fields(text: str, enum: str, variant: str) -> list[str]:
    found = re.search(r'%s::%s(?: \| %s::\w+)* => &\[([^\]]*)\]' % (enum, variant, enum), text)
    if not found:
        raise AssertionError("abi.rs gives %s::%s no fields" % (enum, variant))
    return re.findall(r'"([^"]*)"', found.group(1))


def exports() -> dict[str, tuple[list[str], str | None]]:
    """abi.rs's six exports: name -> (the parameters' Rust types, the result's or None)."""
    table = {}
    for name, parameters, result in EXPORT.findall(read(ABI)):
        types = [part.split(":", 1)[1].strip() for part in parameters.split(",") if part.strip()]
        table[name] = (types, result.strip() if result else None)
    return table


def imports() -> dict[str, tuple[str, list[str], str]]:
    """HostCore.cs's DllImports: method name -> (the attribute's arguments, the parameters' C# types, the result)."""
    table = {}
    for attribute, result, name, parameters in IMPORT.findall(read(HOST_CORE)):
        types = [" ".join(part.split()[:-1]) for part in parameters.split(",") if part.strip()]
        table[name] = (attribute, types, result)
    return table


def csharp_strings(text: str, owner: str) -> dict[str, str]:
    body = re.search(r"internal static class %s\s*\{(.*?)\n    \}" % owner, text, re.S)
    if not body:
        raise AssertionError("ISurfaces.cs has no %s" % owner)
    return dict(re.findall(r'internal const string (\w+) = "([^"]*)";', body.group(1)))


def csharp_array(text: str, owner: str, name: str) -> list[str]:
    body = re.search(r"internal static class %s\s*\{(.*?)\n    \}" % owner, text, re.S).group(1)
    found = re.search(r"internal static readonly string\[\] %s = \{(.*?)\};" % name, body, re.S)
    if not found:
        raise AssertionError("%s has no %s" % (owner, name))
    return [item.strip() for item in found.group(1).split(",") if item.strip()]


class ExportTests(unittest.TestCase):
    def test_abi_rs_makes_the_six_of_its_table(self):
        table = exports()
        self.assertEqual(list(table), rust_list(read(ABI), "EXPORTS"))
        self.assertEqual(len(table), 6)
        for name, (parameters, result) in table.items():
            with self.subTest(name):
                self.assertTrue(set(parameters) <= set(PARAMETER), parameters)
                self.assertIn(result, RESULT)

    def test_host_core_imports_exactly_the_six_with_their_types(self):
        table, imported = exports(), imports()
        self.assertEqual(sorted(imported), sorted(table))
        self.assertEqual(read(HOST_CORE).count("DllImport("), 6, "a seventh import, or one this test cannot read")
        for name, (parameters, result) in table.items():
            attribute, csharp, returned = imported[name]
            with self.subTest(name):
                self.assertEqual(csharp, [PARAMETER[kind] for kind in parameters])
                self.assertEqual(returned, RESULT[result])
                arguments = [part.strip() for part in attribute.split(",")]
                self.assertEqual(arguments[0], "Dll")
                self.assertIn('EntryPoint = "%s"' % name, arguments)
                self.assertIn("CallingConvention = CallingConvention.Cdecl", arguments)
                self.assertIn("ExactSpelling = true", arguments)
        self.assertIn('internal const string Dll = "car_core.dll";', read(HOST_CORE))
        self.assertIn("internal const int Abi = 1;", read(HOST_CORE))
        self.assertIn("pub const ABI: i64 = 1;", read(ABI))

    def test_every_reply_is_freed_in_a_finally(self):
        text = read(HOST_CORE)
        take = re.search(r"private static string Take\(IntPtr buffer, UIntPtr length\)\s*\{(.*?)\n        \}", text, re.S)
        self.assertIsNotNone(take)
        self.assertRegex(take.group(1), r"finally\s*\{\s*car_free\(buffer, length\);\s*\}")
        # The one place car_free is called, and every reply-giving import goes through Take.
        self.assertEqual(text.count("car_free(buffer, length)"), 1)
        for name in ("car_start", "car_bridge", "car_next_event", "car_post_action"):
            with self.subTest(name):
                self.assertEqual(len(re.findall(r"IntPtr reply = %s\(" % name, text)), 1)
        self.assertEqual(text.count("return Take(reply, length);"), 4)

    def test_no_other_csharp_file_imports_the_core(self):
        named = []
        for folder in (ROOT / "gui", ROOT / "advanced" / "gui", ROOT / "build" / "setup"):
            for path in sorted(folder.glob("*.cs")):
                if path != HOST_CORE and "car_core" in read(path):
                    named.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(named, [])


class SurfaceTests(unittest.TestCase):
    def test_the_event_names_are_abi_rs_names(self):
        events = csharp_strings(read(SURFACES), "HostEvents")
        self.assertEqual(list(events.values()), rust_names(read(ABI), "EventKind"))
        self.assertEqual(csharp_array(read(SURFACES), "HostEvents", "All"), list(events))

    def test_the_action_names_are_abi_rs_names(self):
        actions = csharp_strings(read(SURFACES), "HostActions")
        self.assertEqual(list(actions.values()), rust_names(read(ABI), "ActionKind"))
        self.assertEqual(csharp_array(read(SURFACES), "HostActions", "All"), list(actions))
        self.assertEqual(len(actions), 14)

    def test_the_popup_calls_are_control_calls(self):
        tree = ast.parse(read(MODEL))
        calls = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                     and any(getattr(target, "id", None) == "CONTROL_CALLS" for target in node.targets))
        self.assertEqual(rust_list(read(ABI), "POPUP_CALLS"), list(calls))
        self.assertEqual([item.strip('"') for item in csharp_array(read(SURFACES), "HostActions", "PopupCalls")],
                         list(calls))

    def test_isurfaces_has_one_method_per_event_but_ended(self):
        body = re.search(r"internal interface ISurfaces\s*\{(.*?)\n    \}", read(SURFACES), re.S).group(1)
        methods = re.findall(r"^\s*void (\w+)\(([^)]*)\);", body, re.M)
        kinds = [kind for kind in rust_names(read(ABI), "EventKind") if kind != "ended"]
        # "surfaces" is Start (P6-DESIGN 4.1); every other kind is its own name.
        named = ["Start" if kind == "surfaces" else kind.capitalize() for kind in kinds]
        self.assertEqual([name for name, _ in methods], named)
        self.assertEqual(dict(methods)["Start"], "SurfacesEvent surfaces")
        self.assertEqual(dict(methods)["Close"], "")

    def test_the_surfaces_event_carries_abi_rs_fields(self):
        body = re.search(r"internal sealed class SurfacesEvent\s*\{(.*?)\n    \}", read(SURFACES), re.S).group(1)
        properties = re.findall(r"internal [\w<>, ]+ (\w+) \{ get; set; \}", body)
        fields = rust_fields(read(ABI), "EventKind", "Surfaces")
        # Every field of the wire, in order, and the pump's own Actions after them.
        self.assertEqual(properties, [field.capitalize() for field in fields] + ["Actions"])


class BuildTests(unittest.TestCase):
    def test_the_shipped_window_does_not_compile_them(self):
        for name in ("gui/HostCore.cs", "gui/ISurfaces.cs"):
            with self.subTest(name):
                self.assertNotIn(name, guiscan.manifest())
                self.assertIn(name, guiscan.HOST)
                self.assertNotIn(name.replace("/", "\\").split("\\")[-1],
                                 read(ROOT / "build" / "make_gui.ps1"))

    @unittest.skipUnless(CSC.is_file(), "needs the in-box C# compiler")
    def test_they_compile_alone_with_no_warning(self):
        with tempfile.TemporaryDirectory(prefix="car-host-contract-") as folder:
            done = subprocess.run(
                [str(CSC), "-nologo", "-target:library", "-platform:x64", "-warnaserror",
                 "-out:" + str(Path(folder) / "HostContract.dll"), str(HOST_CORE), str(SURFACES)],
                capture_output=True, encoding="locale", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()

"""What Python 3.15 takes away, held off every Python file of the repository while the sources still run on 3.13 and 3.14.

The CI's 3.15 lanes only reach what a test runs. A call on a rare path - a build step, an error branch, a measurement -
would break on the first person's PC that takes it, so these read the code instead of running it: what What's New in
3.15 lists as removed, and what it lists as deprecated with a date or none. Nothing here imports the code it reads.

Read by name, from the syntax tree: a word in a string or a comment is no finding, and an object of our own that has a
method by one of these names has to be called something else. That is cheap, and it is the price of having no list of
exceptions to keep.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
TREES = ("src", "advanced/src", "build", "scripts", "tests", "advanced/tests")
# What a build leaves under build/ is not the repository's code.
NOT_SOURCE = frozenset(("__pycache__", "cache", "stage", "dist"))

# An attribute or a bare name, wherever it is read. 3.15 removed the first group; the second is deprecated in it.
GONE_NAMES = {name: "removed in 3.15" for name in (
    "__cached__", "ByteString", "SetPointerType", "glob0", "glob1", "CGIHTTPRequestHandler", "load_module", "is_reserved",
    "java_ver", "co_lnotab", "no_type_check_decorator", "getmark", "setmark", "getmarkers")}
GONE_NAMES.update({name: "deprecated by 3.15" for name in (
    "__loader__", "__package__", "get_event_loop_policy", "set_event_loop_policy", "AbstractEventLoopPolicy",
    "DefaultEventLoopPolicy", "WindowsSelectorEventLoopPolicy", "WindowsProactorEventLoopPolicy", "expand_makefile_vars",
    "_enablelegacywindowsfsencoding", "utcnow", "utcfromtimestamp", "commonprefix", "FileType", "_clear_type_cache",
    "notifyAll", "isSet", "isDaemon", "setDaemon", "getName", "setName", "currentThread", "activeCount", "splitattr",
    "splithost", "splitnport", "splitpasswd", "splitport", "splitquery", "splittag", "splittype", "splituser", "splitvalue",
    "js_output", "PROTOCOL_TLS", "PROTOCOL_TLSv1", "PROTOCOL_TLSv1_1", "PROTOCOL_TLSv1_2", "PROTOCOL_SSLv3")})
GONE_MODULES = {"sre_compile": "removed in 3.15", "sre_constants": "removed in 3.15", "sre_parse": "removed in 3.15",
                "profile": "deprecated by 3.15, removed in 3.17: profiling.tracing, or cProfile, which stays"}
# `<module>.__version__`: deprecated in these modules by 3.15, removed in 3.20. sys.version_info says it.
VERSIONED = frozenset(("argparse", "csv", "ctypes", "decimal", "imaplib", "ipaddress", "json", "logging", "optparse", "pickle",
                       "platform", "re", "socketserver", "tabnanny", "tarfile", "zlib"))
_YEAR = re.compile(r"%[YyG]")
_DAY = re.compile(r"%[de]")


def sources():
    for tree in TREES:
        for path in sorted((ROOT / tree).rglob("*.py")):
            if not NOT_SOURCE.intersection(path.relative_to(ROOT).parts):
                yield path


def parsed():
    for path in sources():
        yield path.relative_to(ROOT).as_posix(), ast.parse(path.read_bytes())


def dotted(node) -> str:
    """`a.b.c` for a chain of plain names, or "" for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = dotted(node.value)
        return inner and inner + "." + node.attr
    return ""


def keyword(call, name):
    return next((item.value for item in call.keywords if item.arg == name), None)


def called_name(call) -> str:
    return call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")


def _call_findings(call) -> list:
    name, whole, found = called_name(call), dotted(call.func), []
    if name == "strptime" and len(call.args) > 1:
        form = call.args[1]
        if isinstance(form, ast.Constant) and isinstance(form.value, str) and _DAY.search(form.value) \
                and not _YEAR.search(form.value):
            found.append("strptime of a day with no year: a ValueError on 3.15")
    if whole.endswith("sqlite3.connect") and len(call.args) > 1:
        found.append("sqlite3.connect: everything after the database is keyword-only on 3.15")
    if name in ("create_function", "create_aggregate") and {"name", "narg", "n_arg", "func", "aggregate_class"} \
            & {item.arg for item in call.keywords}:
        found.append("%s: its first three parameters are positional-only on 3.15" % name)
    if name in ("set_authorizer", "set_progress_handler", "set_trace_callback") and call.keywords:
        found.append("%s: its first parameter is positional-only on 3.15" % name)
    if name == "RLock" and (call.args or call.keywords):
        found.append("RLock with arguments: a TypeError on 3.15")
    if whole.startswith("hashlib.") and keyword(call, "string") is not None:
        found.append("hashlib's string=: deprecated by 3.15")
    if name == "files" and "resources" in whole and keyword(call, "package") is not None:
        found.append("importlib.resources.files(package=): removed in 3.15")
    if name == "rmtree" and keyword(call, "onerror") is not None:
        found.append("rmtree's onerror=: deprecated; onexc= runs on every Python we support")
    if whole == "codecs.open":
        found.append("codecs.open: deprecated; open() with an encoding")
    if name == "warn" and whole != "warnings.warn":
        found.append("a logger's warn(): deprecated; warning()")
    if whole == "asyncio.iscoroutinefunction":
        found.append("asyncio.iscoroutinefunction: removed in 3.16; inspect's")
    if name == "SSLContext" and not call.args and keyword(call, "protocol") is None:
        found.append("ssl.SSLContext() with no protocol: deprecated; ssl.create_default_context()")
    if name == "NamedTuple" and len(call.args) == 1 and call.keywords:
        found.append("NamedTuple's keyword syntax: a TypeError on 3.15")
    if name == "TypedDict" and (len(call.args) == 1 or (len(call.args) == 2 and isinstance(call.args[1], ast.Constant))):
        found.append("TypedDict with no fields argument: a TypeError on 3.15")
    if name == "add_argument" and len(call.args) > 1 and keyword(call, "dest") is None:
        words = [item.value for item in call.args if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        if any(len(word) == 2 and word[0] == "-" for word in words) and any(len(word) > 2 and word[:2] != "--" for word in words):
            found.append("add_argument with a short and a single-dash long option: its dest changes on 3.15")
    return found


def findings(tree) -> list:
    """(line, why) for everything in one parsed file that 3.15 removes or deprecates."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in GONE_NAMES:
                found.append((node.lineno, "%s: %s" % (node.attr, GONE_NAMES[node.attr])))
            elif node.attr == "__version__" and dotted(node.value) in VERSIONED:
                found.append((node.lineno, "%s.%s: deprecated by 3.15; sys.version_info" % (dotted(node.value), node.attr)))
        elif isinstance(node, ast.Name) and node.id in GONE_NAMES:
            found.append((node.lineno, "%s: %s" % (node.id, GONE_NAMES[node.id])))
        elif isinstance(node, ast.Import):
            found += [(node.lineno, "import %s: %s" % (item.name, GONE_MODULES[item.name]))
                      for item in node.names if item.name in GONE_MODULES]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module in GONE_MODULES:
                found.append((node.lineno, "from %s: %s" % (node.module, GONE_MODULES[node.module])))
            found += [(node.lineno, "from %s import %s: %s" % (node.module, item.name, GONE_NAMES[item.name]))
                      for item in node.names if item.name in GONE_NAMES]
            found += [(node.lineno, "typing.Text: deprecated") for item in node.names
                      if node.module == "typing" and item.name == "Text"]
        elif isinstance(node, ast.Call):
            found += [(node.lineno, why) for why in _call_findings(node)]
    return found


class RemovedApiTests(unittest.TestCase):
    def test_no_python_file_uses_what_3_15_removes_or_deprecates(self):
        found = ["%s:%d %s" % (name, line, why) for name, tree in parsed() for line, why in findings(tree)]
        self.assertEqual(found, [])

    def test_the_reading_sees_each_kind_of_finding(self):
        """A scan that finds nothing has to be shown able to find something."""
        for source, word in (("x = __cached__\n", "__cached__"), ("m.__loader__\n", "__loader__"),
                             ("path.is_reserved()\n", "is_reserved"), ("import sre_parse\n", "sre_parse"),
                             ("from profile import Profile\n", "profile"), ("from typing import ByteString\n", "ByteString"),
                             ("import json\njson.__version__\n", "json.__version__"),
                             ("time.strptime(t, '%m-%d')\n", "strptime"), ("sqlite3.connect(p, 3)\n", "sqlite3.connect"),
                             ("threading.RLock(1)\n", "RLock"), ("shutil.rmtree(p, onerror=f)\n", "onerror"),
                             ("hashlib.sha256(string=b'')\n", "string="), ("log.warn('x')\n", "warn"),
                             ("NamedTuple('P', x=int)\n", "NamedTuple"), ("TypedDict('T')\n", "TypedDict"),
                             ("parser.add_argument('-f', '-foo')\n", "add_argument"), ("datetime.utcnow()\n", "utcnow"),
                             ("connection.set_trace_callback(trace_callback=f)\n", "set_trace_callback")):
            with self.subTest(source=source):
                self.assertIn(word, " ".join(why for _line, why in findings(ast.parse(source))))

    def test_what_stays_is_not_a_finding(self):
        for source in ("time.strptime(t, '%Y-%m-%d')\n", "sqlite3.connect(p, timeout=3)\n", "warnings.warn('x')\n",
                       "s = '__cached__'\n", "connection.set_authorizer(f)\n", "shutil.rmtree(p, onexc=f)\n",
                       "NamedTuple('P', [('x', int)])\n", "TypedDict('T', {})\n"):
            with self.subTest(source=source):
                self.assertEqual(findings(ast.parse(source)), [])


if __name__ == "__main__":
    unittest.main()

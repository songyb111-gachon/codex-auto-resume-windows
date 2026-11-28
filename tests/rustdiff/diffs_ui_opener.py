"""S6.4e: the Dashboard opener - `ui/tray/dashboard.py` (`open_dashboard`, `open_chat`, `row_argument`) and the hand-over to
a window that is already open (`win/handover.py`: `hand_over`, `windows_of`, `ask`, `request_text`, `spelled`) - against the
port's own Rust (car-watcher's `dashboard.rs`, car-platform's `handover.rs`, compiled again by car-harness's build.rs over a
scratch world: rust/crates/car-harness/src/opener.rs).

The world is the same on both sides and is the case's: the top-level windows EnumWindows lists (visible or not, owned or
not, the process, the class, what each answers a WM_COPYDATA), the program each process runs, whether the start fails. The
reference's `handover._dll` answers from it (so its `windows_of`, `_image`, `ask` and `hand_over` run as written) and its
`dashboard.subprocess` records the start; Rust's copies call the world's names in place of Windows'. Compared: the result
or the refusal (class and message), every hand-over asked for (the exe, the page, the row), every image asked for (one per
process), every process let come forward, every message sent (window, message, wparam, the mark, the byte count, the bytes,
the flags, the timeout) and every start (argv, working folder, creation flags, the command line). Nothing is started, no
real window is looked at or sent anything.

* OpenerDiff - `open_dashboard` over homes (installed or not, a folder named like the exe, spaces and unicode, a trailing
  separator), every page and the odd ones, rows good and malformed, and worlds: no window, one that takes, one that refuses,
  one that is not sent to, several (the first that takes ends it), every filter (invisible, owned, no process, another
  class, another program of the same name, an image that cannot be read, one process with two windows, the same file
  spelled another way, a class longer than the buffer); the proxy's answered hand-over; `open_chat` over threads; a
  start that fails.
* PiecesDiff - `row_argument`, `request_text`, `spelled` over scratch paths, `windows_of`, the constants.
"""
from __future__ import annotations

import unittest

from rustdiff.surface import Surface, counted

RECORD: list[str] = []

WORLD = r'''
import ctypes as C, os, subprocess as _sp, types
from pathlib import Path
from codex_auto_resume.ui.tray import dashboard
from codex_auto_resume.win import handover

class World:
    def set(self, spec):
        spec = spec or {}
        self.windows = list(spec.get("windows", []))
        self.images = {pid: image for pid, image in spec.get("images", [])}
        self.answer = spec.get("hand_over")
        self.fails = spec.get("start") == "oserror"
        self.handed, self.asked_images, self.allowed, self.asks, self.started = [], [], [], [], []

    def of(self, window):
        return next((each for each in self.windows if each["window"] == window), {})

W = World()
W.set({})

def _unit(name):
    def mark(function):
        return function
    return mark

class User32:
    def EnumWindows(self, callback, lparam):
        for each in list(W.windows):
            if not callback(each["window"], lparam):
                break
        return 1

    def IsWindowVisible(self, window):
        return 1 if W.of(window).get("visible") else 0

    def GetWindow(self, window, command):
        return W.of(window).get("owner", 0) or None

    def GetWindowThreadProcessId(self, window, pid):
        pid._obj.value = W.of(window).get("pid", 0)
        return 1

    def GetClassNameW(self, window, buffer, size):
        units = W.of(window).get("class", "").encode("utf-16-le")[:2 * (size - 1)]
        buffer.value = units.decode("utf-16-le")
        return len(units) // 2

    def AllowSetForegroundWindow(self, pid):
        W.allowed.append(pid)
        return 1

    def SendMessageTimeoutW(self, window, message, wparam, lparam, flags, timeout, result):
        copy = handover._CopyData.from_address(lparam.value)
        data = C.string_at(copy.lpData, copy.cbData) if copy.lpData else b""
        W.asks.append({"window": window, "message": message, "wparam": wparam, "mark": copy.dwData, "size": copy.cbData,
                       "data": data.hex(), "flags": flags, "timeout": timeout})
        found = W.of(window)
        result._obj.value = found.get("answer", 0)
        return found.get("sent", 0)

class Kernel32:
    def OpenProcess(self, access, inherit, pid):
        W.asked_images.append(pid)
        return 0 if W.images.get(pid) is None else 0x1000 + pid

    def QueryFullProcessImageNameW(self, process, flags, buffer, size):
        buffer.value = W.images[process - 0x1000]
        size._obj.value = len(buffer.value)
        return 1

    def CloseHandle(self, process):
        return 1

class Method:
    """A stand-in function `_call` may set restype and argtypes on, as it does on ctypes' own."""
    def __init__(self, bound):
        self.bound = bound
    def __call__(self, *args):
        return self.bound(*args)

class Dll:
    def __init__(self, inner):
        self.inner = inner
    def __getattr__(self, name):
        return Method(getattr(self.inner, name))

DLLS = {"user32": Dll(User32()), "kernel32": Dll(Kernel32())}
handover._dll = lambda name: DLLS[name]

REAL_HAND_OVER = handover.hand_over

def hand_over(exe, page=None, row=None):
    W.handed.append([str(exe), page, row])
    if W.answer is not None:
        return W.answer
    return REAL_HAND_OVER(exe, page, row)

handover.hand_over = hand_over

class Starts:
    CREATE_NO_WINDOW = _sp.CREATE_NO_WINDOW

    def Popen(self, args, cwd=None, close_fds=False, creationflags=0, **rest):
        W.started.append({"argv": list(args), "cwd": cwd, "flags": creationflags,
                          "command_line": _sp.list2cmdline(list(args))})
        CLOSE_FDS.append(close_fds)
        if W.fails:
            raise OSError("not started")
        return types.SimpleNamespace(pid=0)

CLOSE_FDS = []
dashboard.subprocess = Starts()

def recorded(call):
    try:
        result = {"ok": call()}
    except Exception as error:
        result = {"error": type(error).__name__, "message": str(error)}
    return {"result": result, "handed": W.handed, "images": W.asked_images, "allowed": W.allowed, "asks": W.asks,
            "started": W.started}

def open_dashboard(home, page, row, world):
    W.set(world)
    return recorded(lambda: dashboard.open_dashboard(Path(home), page, row=row))

def open_chat(home, thread, world):
    W.set(world)
    return recorded(lambda: dashboard.open_chat(Path(home), thread))

def row_argument(row):
    try:
        return {"ok": dashboard.row_argument(row)}
    except Exception as error:
        return {"error": type(error).__name__, "message": str(error)}

def windows_of(exe, world):
    W.set(world)
    found = handover.windows_of(exe)
    return {"found": [list(each) for each in found], "images": W.asked_images}

def consts():
    return [handover.OPEN_REQUEST_MARK, handover.OPEN_REQUEST_TAKEN, handover.FORMS_CLASS, handover.ANSWER_MILLISECONDS,
            list(dashboard.ROW_DIALOGS), list(dashboard.PAGES)]

OPS = {"opener.dashboard": open_dashboard, "opener.chat": open_chat, "opener.row_argument": row_argument,
       "opener.request_text": lambda page, row: handover.request_text(page, row),
       "opener.spelled": lambda path: handover.spelled(path), "opener.windows_of": windows_of, "opener.consts": consts}

KEY = "ab" * 32
THREAD = "12345678-89ab-7cde-8f01-23456789abcd"
EXE = "CodexAutoResumeSettings.exe"
scratch = os.getcwd()

def made(*parts, exe=True, folder=False):
    home = os.path.join(scratch, *parts)
    os.makedirs(home, exist_ok=True)
    if exe:
        with open(os.path.join(home, EXE), "wb") as out:
            out.write(b"MZ")                       # a file to find; never run
    if folder:
        os.makedirs(os.path.join(home, EXE), exist_ok=True)
    return home

PLAIN = made("plain", "home")
UNICODE = made("with spaces é 한글 ✓", "home")
EMPTY = made("empty", "home", exe=False)
A_FOLDER = made("folder", "home", exe=False, folder=True)
OTHER = made("other", "home")
HOMES = [PLAIN, UNICODE, EMPTY, A_FOLDER]
TAKEN, MARK = handover.OPEN_REQUEST_TAKEN, handover.OPEN_REQUEST_MARK
FORMS = "WindowsForms10.Window.8.app.0.141b42a_r8_ad1"

def window(number, pid, *, visible=True, owner=0, klass=FORMS, sent=1, answer=TAKEN):
    return {"window": number, "pid": pid, "visible": visible, "owner": owner, "class": klass, "sent": sent, "answer": answer}

def worlds(home):
    exe = os.path.join(home, EXE)
    other = os.path.join(OTHER, EXE)
    named = os.path.join(home, "CodexAutoResume.exe")
    return {
        "none": {},
        "takes": {"windows": [window(0x10010, 4100)], "images": [[4100, exe]]},
        "refuses": {"windows": [window(0x10010, 4100, answer=0)], "images": [[4100, exe]]},
        "not sent": {"windows": [window(0x10010, 4100, sent=0)], "images": [[4100, exe]]},
        "answers otherwise": {"windows": [window(0x10010, 4100, answer=TAKEN + 1)], "images": [[4100, exe]]},
        "second takes": {"windows": [window(0x10010, 4100, answer=0), window(0x10020, 4200), window(0x10030, 4300)],
                         "images": [[4100, exe], [4200, exe], [4300, exe]]},
        "filtered": {"windows": [window(0x20001, 5001, visible=False), window(0x20002, 5002, owner=0x99),
                                 window(0x20003, 0), window(0x20004, 5004, klass="WindowsForms10"),
                                 window(0x20005, 5005, klass="windowsforms10.window"), window(0x20006, 5006, klass=""),
                                 window(0x20007, 5007, klass="Chrome_WidgetWin_1"), window(0x20008, 5008),
                                 window(0x20009, 5009), window(0x2000A, 5010), window(0x2000B, 5011)],
                     "images": [[5001, exe], [5002, exe], [5004, exe], [5005, exe], [5006, exe], [5007, exe],
                                [5008, other], [5009, None], [5010, named], [5011, exe]]},
        "one process two windows": {"windows": [window(0x30001, 6000, answer=0), window(0x30002, 6000)],
                                    "images": [[6000, exe]]},
        "spelled otherwise": {"windows": [window(0x40001, 7001, answer=0), window(0x40002, 7002)],
                              "images": [[7001, exe.upper()], [7002, os.path.join(home, "..", "home", EXE)]]},
        "long class": {"windows": [window(0x50001, 8001, klass=FORMS + "x" * 300)], "images": [[8001, exe]]},
        "nothing takes": {"windows": [window(0x60001, 9001, answer=0), window(0x60002, 9002, sent=0)],
                          "images": [[9001, exe], [9002, exe]]},
    }

def slashed(home, spelling=None):
    """An image written with forward slashes (QueryFullProcessImageNameW gives back-slashes), or as `spelling` makes it."""
    exe = os.path.join(home, EXE)
    return {"windows": [window(0x70001, 9501)],
            "images": [[9501, spelling(exe) if spelling else exe.replace("\\", "/")]]}
'''

OPENER = WORLD + r'''
PAGES = list(dashboard.PAGES)
cases = []
pages = [None] + PAGES + ["", "Pending", "pending ", "--page=x", "advanced", "x" * 100, "é"]
for home in HOMES:
    for page in pages:
        cases.append(["opener.dashboard", home, page, None, {}])
good = [["message", KEY, THREAD], ["once_words", KEY, THREAD]]
bad = [["settings", KEY, THREAD], ["message", KEY.upper(), THREAD], ["message", KEY[:-1], THREAD],
       ["message", KEY + "0", THREAD], ["message", "interruption-example", THREAD], ["message", KEY, THREAD.upper()],
       ["message", KEY, "{%s}" % THREAD], ["message", KEY, THREAD + " --page=x"], ["message", KEY + ":x", THREAD],
       ["message", KEY], ["message", KEY, THREAD, "x"], [], "message", 7, 7.5, True, ["message", 7, THREAD],
       ["message", KEY, 7], [7, KEY, THREAD], [None, KEY, THREAD], ["message", None, THREAD],
       ["Message", KEY, THREAD], ["message", KEY, "12345678-89ab-7cde-8f01-23456789abc"]]
for home in (PLAIN, EMPTY, UNICODE):
    for page in (None, "pending", "history", "nope"):
        for row in good + bad:
            cases.append(["opener.dashboard", home, page, row, {}])
for home in (PLAIN, UNICODE):
    for name, world in worlds(home).items():
        for page in (None, "pending", "settings"):
            cases.append(["opener.dashboard", home, page, None, world])
        cases.append(["opener.dashboard", home, "pending", good[0], world])
        cases.append(["opener.dashboard", home, None, good[1], world])
for answer in (True, False):
    for page, row in ((None, None), ("pending", None), ("history", None), ("pending", good[0]), (None, good[1])):
        cases.append(["opener.dashboard", PLAIN, page, row, {"hand_over": answer}])
        cases.append(["opener.dashboard", EMPTY, page, row, {"hand_over": answer}])
threads = [THREAD, THREAD.upper(), "{%s}" % THREAD, THREAD + " ", "", None, 7, [THREAD], "not a conversation",
           "00000000-0000-0000-0000-000000000000"]
for home in HOMES:
    for thread in threads:
        cases.append(["opener.chat", home, thread, {}])
finish(cases, OPS)
'''

KNOWN_SLASHED = WORLD + r'''
cases = []
for home in (PLAIN, UNICODE):
    cases.append(["opener.dashboard", home, "pending", None, slashed(home)])
    cases.append(["opener.windows_of", os.path.join(home, EXE), slashed(home)])
    # Integration 13's edges: only the last separator counts, either kind; a drive-relative name; a name that ends in one
    # (no UNC name: the reference would resolve it over the network).
    for spelling in (lambda exe: exe.replace("\\", "/", 1), lambda exe: exe[:-len(EXE)] + "x/" + EXE,
                     lambda exe: exe[:2] + EXE, lambda exe: exe + "/"):
        cases.append(["opener.windows_of", os.path.join(home, EXE), slashed(home, spelling)])
finish(cases, OPS)
'''

KNOWN_UNPACKED = WORLD + r'''
cases = []
for row in ("abc", "xyz", {"a": 1, "b": 2, "c": 3}, {"message": 1, KEY: 2, THREAD: 3},
            # Integration 13's edges: texts of two, four, none and three non-ASCII characters (no lone surrogate: the
            # harness's pipe is strict UTF-8); a dict of two keys, one whose keys are a once_words row, one whose key is no
            # interruption id.
            "ab", "abcd", "", "\u00e9\u4e2d\U0001f600", {"message": 1, KEY: 2},
            {"once_words": None, KEY: [], THREAD: {}}, {"message": 1, KEY.upper(): 2, THREAD: 3}):
    cases.append(["opener.row_argument", row])
    cases.append(["opener.dashboard", PLAIN, "pending", row, {"hand_over": True}])
finish(cases, OPS)
'''

FAILED_START = WORLD + r'''
cases = []
for home in (PLAIN, UNICODE):
    for page, row in ((None, None), ("pending", None), ("pending", ["message", KEY, THREAD])):
        cases.append(["opener.dashboard", home, page, row, {"start": "oserror"}])
    cases.append(["opener.chat", home, THREAD, {"start": "oserror"}])
finish(cases, OPS)
'''

PIECES = WORLD + r'''
cases = [["opener.consts"]]
rows = [["message", KEY, THREAD], ["once_words", KEY, THREAD], ["message", KEY.upper(), THREAD], ["message", KEY],
        "message", "ab", "abcd", 7, None, [], ["once_words", "", THREAD], ["message", KEY, ""], ["message", KEY, THREAD, None],
        {"message": KEY}, {}]
for row in rows:
    cases.append(["opener.row_argument", row])
texts = [None, "", "pending", "history", "pé", "a\nb", "한"]
for page in texts:
    for row in texts:
        cases.append(["opener.request_text", page, row])
exe = os.path.join(PLAIN, EXE)
for path in (exe, exe.upper(), exe.replace("\\", "/"), os.path.join(PLAIN, "..", "home", EXE), os.path.join(UNICODE, EXE),
             os.path.join(EMPTY, EXE), PLAIN, PLAIN + "\\", os.path.join(PLAIN, "missing", "x.exe")):
    cases.append(["opener.spelled", path])
for name, world in worlds(PLAIN).items():
    for target in (exe, exe.upper(), os.path.join(OTHER, EXE)):
        cases.append(["opener.windows_of", target, world])
finish(cases, OPS)
'''


class OpenerDiff(Surface):
    def test_the_openers(self):
        done = self.family(OPENER, label="opener")
        results = [each.get("ok", {}) for each in done["results"]]
        asks = sum(len(each.get("asks", [])) for each in results if isinstance(each, dict))
        starts = sum(len(each.get("started", [])) for each in results if isinstance(each, dict))
        RECORD.append("opener: %d open_dashboard and %d open_chat cases (homes, pages, rows, worlds of windows; %d messages "
                      "sent to stand-in windows, %d starts recorded, nothing started) equal the tag's" % (
                          counted(done, "opener.dashboard"), counted(done, "opener.chat"), asks, starts))

    def test_a_start_that_fails(self):
        """The reference's `subprocess.Popen` raising (a program Windows cannot start) leaves open_dashboard/open_chat with that
        OSError; so does car-watcher's dashboard.rs since Integration 13 (`OpenError::Os`, by its Python class; S6.4e found it
        dropping the start's error and answering true)."""
        self.family(FAILED_START, label="opener-failed-start")


    def test_an_image_written_with_forward_slashes(self):
        """The reference's `windows_of` takes the image's name with `os.path.basename`, which splits at `/` too, after the
        drive; so does handover.rs since Integration 13 (`ntpath.split`'s tail;
        S6.4e found it splitting at the back-slash only)."""
        self.family(KNOWN_SLASHED, label="opener-slashed")

    def test_a_row_python_unpacks(self):
        """The reference unpacks any three-item iterable as the row - a three-character text, a dict by its keys - and refuses
        it as "not a dialog of the window" (or takes a dict whose keys are a row); so does car-watcher's `row_argument` since
        Integration 13 (S6.4e found it taking only an array). The host only ever sends an array or nothing (api.rs)."""
        self.family(KNOWN_UNPACKED, label="opener-unpacked")


class PiecesDiff(Surface):
    def test_the_pieces(self):
        done = self.family(PIECES, label="opener-pieces")
        RECORD.append("opener pieces: %d row_argument, %d request_text, %d spelled, %d windows_of cases and the constants "
                      "equal the tag's" % (counted(done, "opener.row_argument"), counted(done, "opener.request_text"),
                                           counted(done, "opener.spelled"), counted(done, "opener.windows_of")))

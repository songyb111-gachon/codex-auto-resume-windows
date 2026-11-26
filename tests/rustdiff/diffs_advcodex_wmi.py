"""S7.2c remainder: `codex/wmi_escape.py` (measurement MW's launcher) as the v0.6.26 final has it, held equal to
car-adv's `codex::wmi_escape` - and NEVER run (P7-DESIGN section 4).

On both sides every effect of `probe()` is a scripted stand-in that logs it: the interpreter's launcher, the scratch
folder, the bootstrap written, the job object and its limit, the helper started (its whole argv and creation flags),
OpenProcess/Assign/Resume/Wait/Terminate/CloseHandle, the heartbeat's record, the sleeps and the cleanup. Nothing is
started, opened, written or removed; the compared result is the facts (or what was raised) and the whole call log, in
order, over walks where each step answers otherwise (no launcher, no job, the limit refused, the start raising, the
assign refused, no heartbeat, a heartbeat of every shape, the helper and the heartbeat alive or not, the helper's wait
timing out). Then what the helper would hand `pwsh.run` (the script, the HEARTBEAT_CMD command line every token quoted,
the timeout, the sleep after), the `CODEX_AUTO_RESUME_ARG_*` variables pwsh would set, the heartbeat's record and the
constants.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_wmi`.
"""
from __future__ import annotations

import random

from rustdiff.advcodexd import AdvCodexRestDiff

HEARTBEATS = [None, {"pid": 5150, "in_job": False, "kill_on_close": None}, {"pid": 5150, "in_job": True,
              "kill_on_close": True}, {"pid": True, "in_job": 1, "kill_on_close": "yes"}, {"pid": "5150"}, {},
              [], 0, "text", {"pid": 7.5, "in_job": [], "kill_on_close": {}}, {"pid": -3, "in_job": None}]
SOURCES = ["C:\\Product\\advanced\\src;C:\\Product\\src", "C:\\Program Files\\x y\\src", "C:\\a\"b\\src\\",
           "C:\\\u00e9t\u00e9\\src", ""]


def script(rng: random.Random) -> dict:
    out = {}
    pick = lambda kind, choices: out.__setitem__(kind, [rng.choice(choices) for _ in range(rng.randint(1, 4))])
    if rng.random() < 0.2:
        pick("launcher", ["C:\\Python\\pythonw.exe", "raise", "C:\\Program Files\\Py 3\\pythonw.exe", "C:/x/pythonw.exe"])
    if rng.random() < 0.3:
        pick("workdir", ["C:\\Temp\\car-mw-1", "C:/Temp/car-mw-2/", "D:\\", "C:\\T\u00e9mp\\car-mw-3"])
    if rng.random() < 0.05:
        pick("write", ["raise"])
    for kind, choices in (("job", [300, 0, 301]), ("setinfo", [1, 0]), ("assign", [1, 0]), ("open", [77, 0, 78]),
                          ("wait", [0x102, 0, 0x80, 0xFFFFFFFF]), ("close", [1, 0]), ("terminate", [1, 0])):
        if rng.random() < 0.4:
            pick(kind, choices)
    if rng.random() < 0.1:
        pick("spawn", ["raise", 4101])
    if rng.random() < 0.3:
        pick("wait_child", ["raise", None])
    out["heartbeat"] = [rng.choice(HEARTBEATS)]
    return out


class WmiDiff(AdvCodexRestDiff):
    def test_probe(self):
        rng = random.Random(7212)
        cases = [["wm.constants"]]
        cases += [["wm.probe", {"heartbeat": [beat]}, SOURCES[0]] for beat in HEARTBEATS]
        cases += [["wm.probe", script(rng), rng.choice(SOURCES)] for _ in range(1500)]
        want = self.same("probe", cases)
        self.assertTrue(any(one["ok"].get("facts", {}).get("survived") for one in want[1:]))
        self.assertTrue(any("raised" in one["ok"] for one in want[1:]))

    def test_helper_and_record(self):
        cases = []
        for source in SOURCES:
            for workdir in ("C:\\Temp\\car-mw-1", "C:\\Temp\\car-mw-1\\", "C:", "C:/Temp/x y", ""):
                for launcher in ("C:\\Python\\pythonw.exe", "C:\\Program Files\\Py\\pythonw.exe", "pythonw"):
                    for fails in (False, True):
                        cases.append(["wm.helper", source, workdir, launcher, workdir + "\\bootstrap.py", fails])
        for values in ({"HEARTBEAT_CMD": "\"C:\\x\" \"y\""}, {"HEARTBEAT_CMD": ""}, {"HEARTBEAT_CMD": None},
                       {"HEARTBEAT_CMD": "x" * 16000}, {"HEARTBEAT_CMD": "x" * 16001}, {"HEARTBEAT_CMD": "a\x00b"},
                       {"bad name": "x"}, {"A1": "\u00e9", "B_2": "y"}):
            cases.append(["wm.env", values])
        for pid in (0, 5150, -1, 2 ** 40):
            for in_job in (True, False, None):
                for kill in (True, False, None):
                    cases.append(["wm.record", pid, in_job, kill])
        self.same("helper", cases)

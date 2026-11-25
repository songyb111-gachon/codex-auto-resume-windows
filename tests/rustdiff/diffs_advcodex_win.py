"""S7.2c remainder: `win/waketimer.py` and `win/stopflag.py` as the v0.6.26 final has them, held equal to car-adv's
`win::{waketimer, stopflag}` over car-platform's `wake` traits.

Nothing real is asked of Windows on either side: kernel32 and powrprof are scripted stand-ins that answer each call
kind from a list (a handle, TRUE/FALSE, a power status, a scheme, a value index, or a raise) and log every call with
its arguments - the due time as the c_longlong SetWaitableTimer is handed, the GUIDs as the bytes the structures
hold. A case is one object driven through a walk of its methods; the answers and the whole call log are compared.
`filetime` alone over rounding edges, and the stop event's name for several state folders.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_win`.
"""
from __future__ import annotations

import random

from rustdiff.advcodexd import AdvCodexRestDiff

HANDLES = [501, 0, 7, "raise"]
BOOLS = [1, 0, "raise"]


def timer_script(rng: random.Random) -> dict:
    script = {}
    if rng.random() < 0.5:
        script["create"] = [rng.choice(HANDLES) for _ in range(rng.randint(1, 3))]
    for kind in ("set", "cancel", "close"):
        if rng.random() < 0.4:
            script[kind] = [rng.choice(BOOLS) for _ in range(rng.randint(1, 3))]
    if rng.random() < 0.6:
        script["status"] = [rng.choice([0, 1, 255, 2, "fail", "raise"]) for _ in range(rng.randint(1, 3))]
    if rng.random() < 0.6:
        script["scheme"] = [rng.choice([[0, "00112233445566778899aabbccddeeff"], [0, None], [5, None],
                                        [2, "ffeeddccbbaa99887766554433221100"], [0, "8c5e7fdae8bfa4fa96a6a8a2b2b4c0c1"],
                                        "raise"]) for _ in range(rng.randint(1, 3))]
    for kind in ("ac", "dc"):
        if rng.random() < 0.6:
            script[kind] = [rng.choice([[0, 1], [0, 0], [0, 2], [1, 1], [0, 3], "raise"]) for _ in range(rng.randint(1, 3))]
    if rng.random() < 0.2:
        script["free"] = [rng.choice([None, "raise"]) for _ in range(rng.randint(1, 2))]
    return script


EPOCHS = [0, 1, 1.5, 1767225600, 1767225600.25, 1767225600.00000005, 1767225600.00000015, -1, -0.00000005,
          1e12, 2 ** 80, -(2 ** 70), 1e300, "inf", "-inf", "nan", 0.00000025, 0.00000035, 922337203685.4775807]


def timer_steps(rng: random.Random) -> list:
    out = []
    for _ in range(rng.randint(1, 9)):
        word = rng.choice(["set", "set", "cancel", "close", "allowed", "allowed", "on_battery", "due"])
        out.append([word, rng.choice(EPOCHS)] if word == "set" else [word])
    return out


def stop_script(rng: random.Random) -> dict:
    script = {}
    for kind, choices in (("create", [7, 0, 12, "raise"]), ("open", [9, 0, "raise"]),
                          ("wait", [0, 258, 128, 0xFFFFFFFF, "raise"]), ("close", [1, 0, "raise"])):
        if rng.random() < 0.6:
            script[kind] = [rng.choice(choices) for _ in range(rng.randint(1, 3))]
    return script


WAITS = [0, 0.0004, 0.001, 0.0019, 0.01, -1, 61, 60, 59.9999, "nan", "-inf", 1e9]


def stop_steps(rng: random.Random) -> list:
    out = []
    for _ in range(rng.randint(1, 8)):
        word = rng.choice(["hold", "signalled", "signalled", "wait", "release", "name"])
        if word == "wait":
            seconds = rng.choice(WAITS)
            # The no-handle path sleeps those seconds: keep the walk short where none may be held.
            out.append([word, seconds if not isinstance(seconds, (int, float)) or seconds < 0.02 else 0.001])
        else:
            out.append([word])
    return out


class WinDiff(AdvCodexRestDiff):
    def test_waketimer(self):
        rng = random.Random(7207)
        cases = [["wn.timer", {}, [["allowed"], ["set", 1767225600], ["due"], ["cancel"], ["cancel"], ["close"]]],
                 ["wn.timer", {"create": [0]}, [["set", 5], ["set", 6], ["due"]]],
                 ["wn.timer", {"status": [0]}, [["on_battery"], ["allowed"]]],
                 ["wn.timer", {"scheme": [[0, None]]}, [["allowed"]]],
                 ["wn.timer", {"dc": ["raise"], "status": [0]}, [["allowed"]]],
                 ["wn.timer", {"free": ["raise"]}, [["allowed"]]],
                 ["wn.timer", {"status": ["raise"]}, [["on_battery"], ["allowed"]]]]
        cases += [["wn.timer", timer_script(rng), timer_steps(rng)] for _ in range(1500)]
        self.same("waketimer", cases)

    def test_filetime(self):
        cases = [["wn.filetime", value] for value in EPOCHS]
        cases += [["wn.filetime", n / 10 ** 8] for n in range(-50, 50)]
        cases += [["wn.filetime", 1767225600 + n * 0.00000005] for n in range(0, 40)]
        self.same("filetime", cases)

    def test_stopflag(self):
        rng = random.Random(7208)
        folder = str(self.fresh("stop"))
        folders = [folder, folder + "\\state", folder.upper(), folder + "/x/../y", "relative\\state", "été"]
        cases = [["wn.event_name", each] for each in folders]
        cases += [["wn.stop", folder, {}, [["name"], ["signalled"], ["hold"], ["hold"], ["signalled"], ["wait", 2],
                                           ["release"], ["signalled"]]],
                  ["wn.stop", folder, {"open": [0]}, [["signalled"], ["wait", 0.001]]],
                  ["wn.stop", folder, {"wait": ["raise", 0]}, [["hold"], ["wait", 0.001]]],
                  ["wn.stop", folder, {"close": ["raise"], "wait": [0]}, [["signalled"]]]]
        cases += [["wn.stop", rng.choice(folders), stop_script(rng), stop_steps(rng)] for _ in range(800)]
        self.same("stopflag", cases)

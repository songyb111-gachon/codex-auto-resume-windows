"""The administrator's policy values as the real readers read them (review 4, S4 and note 1): winreg against
car-platform's `WinRegistry`, on a private hive, and `policykeys.read()` against the product's `policy_places`.

A scratch hive file (RegLoadAppKey: private to the process that loads it, gone with its handle; never HKCU or HKLM) is
made by the reference side, which writes each value's raw bytes with RegSetValueExW (any type, any length, as an
administrator's tool could) under `Software\\Policies\\CodexAutoResume`, reads them back with `winreg.QueryValueEx` and
runs the tag's own `policykeys.read()` with both of winreg's roots pointed at the hive. It closes the hive, and the
probe loads the same file and answers `query` of each value and `registry_reads::policy_places` (what the harness and
the product hand `managed.parse`). The stand-in (`FakeRegistry`) is not in the way: this is the Win32 reader.

`places` holds a value's data where `managed.parse` can use it (a text, a number) and null for any other data (bytes, a
list of texts), the convention of `policy_places` and the harness; `raw` is compared where both readers can say it (a
number or a text: a REG_MULTI_SZ is a list to winreg and bytes to car-platform, and `parse` passes over its type).
"""
from __future__ import annotations

import struct
import unittest

from rustdiff.platform_diffs import RECORD, Base, ref

REG_SZ, REG_BINARY, REG_DWORD, REG_MULTI_SZ, REG_QWORD = 1, 3, 4, 7, 11

HIVE = r'''
import ctypes, json, sys, winreg
from ctypes import wintypes
from codex_auto_resume.win import policykeys
request = json.load(sys.stdin)
advapi = ctypes.WinDLL("advapi32")
advapi.RegLoadAppKeyW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.HKEY), wintypes.DWORD, wintypes.DWORD,
                                  wintypes.DWORD]
advapi.RegCreateKeyExW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD,
                                   wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.HKEY), ctypes.c_void_p]
advapi.RegSetValueExW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_char_p,
                                  wintypes.DWORD]
advapi.RegCloseKey.argtypes = [wintypes.HKEY]
hive = wintypes.HKEY()
assert advapi.RegLoadAppKeyW(request["hive"], ctypes.byref(hive), 0xF003F, 0, 0) == 0, "RegLoadAppKeyW"
key = wintypes.HKEY()
assert advapi.RegCreateKeyExW(hive, policykeys.KEY, 0, None, 0, 0xF003F, None, ctypes.byref(key), None) == 0
for name, (kind, data) in request["values"].items():
    raw = bytes.fromhex(data)
    assert advapi.RegSetValueExW(key, name, 0, kind, raw, len(raw)) == 0, name
advapi.RegCloseKey(key)
handle = hive.value
def shown(data):
    return list(data) if isinstance(data, bytes) else data
raw = {}
with winreg.OpenKey(handle, policykeys.KEY, 0, winreg.KEY_READ) as opened:
    for name in policykeys.NAMES:
        try:
            data, kind = winreg.QueryValueEx(opened, name)
            raw[name] = [shown(data), kind]
        except OSError as error:
            raw[name] = {"error": type(error).__name__}
# policykeys.read() with both roots pointed at the hive.
winreg.HKEY_LOCAL_MACHINE = winreg.HKEY_CURRENT_USER = handle
places = [{name: [data if isinstance(data, (int, str)) and not isinstance(data, bool) else None, kind]
           for name, (data, kind) in place.items()} for place in policykeys.read()]
advapi.RegCloseKey(hive)
sys.stdout.write(json.dumps({"raw": raw, "places": places}))
'''


def dword(number: int) -> str:
    return struct.pack("<I", number).hex()


def qword(number: int) -> str:
    return struct.pack("<Q", number).hex()


def multi(*texts: str) -> str:
    return ("".join(text + "\0" for text in texts) + "\0").encode("utf-16-le").hex()


def text(value: str) -> str:
    return (value + "\0").encode("utf-16-le").hex()


# Each scenario: {name: (type, data as hex)}; every name is one of policykeys.NAMES.
SCENARIOS = {
    "qword-binary-multi": {
        "DisableAutoResume": (REG_QWORD, qword(1)),
        "MaxRecoveryAttempts": (REG_QWORD, qword(2 ** 40 + 3)),
        "ForceObserveOnly": (REG_DWORD, dword(0xFFFFFFFF)),
        "QuietHours": (REG_SZ, text("22:00-06:00")),
        "DisableStatusFile": (REG_BINARY, "01"),
        "DisableUpdateCheck": (REG_MULTI_SZ, multi("a", "b")),
        "DisablePowerAction": (REG_BINARY, ""),
    },
    "numbers-as-written": {
        "DisableAutoResume": (REG_DWORD, dword(0)),
        "MaxRecoveryAttempts": (REG_DWORD, dword(5)),
        "DisablePowerAction": (REG_QWORD, qword(0)),
        "QuietHours": (REG_BINARY, text("22:00-06:00")),
        "ForceObserveOnly": (REG_SZ, text("1")),
    },
}


class PolicyHive(Base):
    """Each scenario on a hive of its own: both readers' raw answers and the places `managed.parse` is given."""

    scenarios = SCENARIOS

    def comparable(self, raw: dict, values: dict) -> dict:
        """The values written, but a REG_MULTI_SZ (a list to winreg, bytes to car-platform); an empty REG_BINARY is
        None to winreg and no bytes to car-platform, both null in the places."""
        kept = {}
        for name, answer in raw.items():
            if name not in values or values[name][0] == REG_MULTI_SZ:
                continue
            if isinstance(answer, list) and answer[1] == REG_BINARY and answer[0] in (None, []):
                answer = [[], REG_BINARY]
            kept[name] = answer
        return kept

    def test_the_policy_values_read_as_winreg_reads_them(self):
        for label, values in self.scenarios.items():
            with self.subTest(label):
                hive = self.scratch / ("policy-%s.hive" % label)
                want = ref(HIVE, {"hive": str(hive), "values": {name: list(pair) for name, pair in values.items()}},
                           self.profile)
                with self.probe() as probe:
                    got = probe.ask("hive_policy", hive=str(hive))
                self.assertEqual(got["places"], want["places"], "policy_places differs from policykeys.read()")
                self.assertEqual(self.comparable(got["raw"], values), self.comparable(want["raw"], values),
                                 "the real reader differs from winreg")
        RECORD.append("policy hive: %d scenarios, places and raw values equal to winreg's" % len(self.scenarios))


if __name__ == "__main__":
    unittest.main()

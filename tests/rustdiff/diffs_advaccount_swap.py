"""S7.2b: `codex/swap.py` over a store of saved accounts - read a saved account on a scratch home, switch, settle what a
switch left (`recover`), unwind before Delete all, save the account in use, add one by Codex's own sign-in - held equal
to the v0.6.26 final: every answer, every call a stand-in was asked (the lock, the restart, the account reads, the
sessions, the process list, the clock) and every file left (the sealed profiles with S7.1a's stand-in seal, the intent,
Codex's sign-in file, the scratch homes).

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advaccount_swap`.
"""
from __future__ import annotations

import hashlib

from rustdiff.advaccount import AdvAccountDiff, sign_in
from rustdiff.diffs_advaccount_pure import OTHER

RECORD: list[str] = []
CUR, TGT, OTH = "cur@x.com", "Tgt@X.com", "oth@x.com"


def found(email, present=True, plan="plus"):
    return {"present": present, "plan_word": plan if present else None, "email": email if present else None,
            "kind": "chatgpt" if present else None}


UNKNOWN = {"present": None, "plan_word": None, "email": None, "kind": None}
OUT = found(None, present=False)


def codex_home(config=None, auth=CUR):
    def setup(root):
        home = root / "codex"
        home.mkdir()
        if auth is not None:
            (home / "auth.json").write_bytes(bytes.fromhex(sign_in(auth)))
        if config is not None:
            (home / "config.toml").write_text(config, encoding="utf-8")
    return setup


def spec(**more):
    made = {"home": "prod", "codex": "codex", "saved": [[TGT, "pro", {"hex": sign_in(TGT)}]]}
    made.update(more)
    return made


def step(between=True, answer=("restarted", "closed"), write=None):
    made = {"between": between, "answer": list(answer) if answer is not None else None}
    if write is not None:
        made["write"] = write
    return made


NOW = 1767225600


class SwitchDiff(AdvAccountDiff):
    def test_switch(self):
        quiet = {"inventory": [[]]}
        cases = []

        def switch(restart, reads, *, world=quiet, store=None, target=None, now=NOW):
            cases.append(["sw.switch", store or spec(), target or {"saved": 0}, {"restart": restart},
                          {"read": reads}, now, world])
        switch([step()], [found(CUR), found(TGT)])
        switch([step(False, ("not_running", None))], [found(CUR), found(TGT)])
        switch([step(False, None)], [found(CUR)])
        switch([step(False, ("not_ended", None))], [found(CUR)])
        switch([step(True, ("restart_failed", None))], [found(CUR), found(TGT)])
        switch([step(True, ("not_started", "closed"))], [found(CUR), found(TGT)])
        switch([step(True, ("restarted", "ended"), write=["codex", {"hex": sign_in(CUR, "r9")}])],
               [found(CUR), found(CUR), found(TGT)])
        switch([step(True, ("restarted", "closed"), write=["codex", {"hex": sign_in(OTH)}])],
               [found(CUR), found(OTH)])
        switch([step()], [found(CUR), found(TGT)], world={"inventory": [[OTHER]]})
        switch([step()], [found(CUR), found(TGT)], world={"inventory": [[OTHER], [OTHER], []]})
        switch([step()], [found(CUR), found(TGT)], world={"inventory": ["raise"]})
        switch([step()], [found(None, present=False)])
        switch([step()], [{"present": True, "email": None, "kind": "apikey"}])
        switch([step()], [found(CUR), UNKNOWN, UNKNOWN, UNKNOWN])
        switch([step()], [found(CUR), UNKNOWN, found(TGT)])
        switch([step(), step()], [found(CUR), found(OTH)])
        switch([step(), step(False, None)], [found(CUR), OUT])
        switch([step(), step(True, ("not_running", None))], [found(CUR), found(OTH)])
        switch([step(), step(False, ("not_running", None))], [found(CUR), found(OTH)])
        switch([step()], [found(CUR), found(TGT)], store=spec(lock=["held"]))
        switch([step()], [found(CUR), found(TGT)], target="0000000000000099")
        switch([step()], [found(TGT)])
        switch([step()], [found(CUR), found(TGT)],
               store=spec(saved=[[TGT, "pro", {"hex": sign_in(TGT)}], [CUR, "plus", {"hex": sign_in(CUR, "old")}]]))
        switch([step()], [found(CUR), found(TGT)], target={"saved": 1},
               store=spec(saved=[[TGT, "pro", {"hex": sign_in(TGT)}], [CUR, "plus", {"hex": sign_in(CUR, "old")}]]))
        switch([step()], [found(CUR), found(TGT)], now=None)
        switch([step()], [5])
        switch([step()], [found(CUR), 5])
        switch([step(True, ("restarted", "closed"), write=["codex", {"hex": b"{broken".hex()}])],
               [found(CUR), found(TGT)])
        RECORD.append("switch: %d cases" % len(cases))
        self.same("switch", cases, setup=codex_home(), one_by_one=True)

    def test_switch_on_homes_that_cannot_be_switched(self):
        cases = [["sw.switch", spec(), {"saved": 0}, {"restart": [step()]}, {"read": [found(CUR), found(TGT)]}, NOW,
                  {"inventory": [[]]}]]
        for config in ("cli_auth_credentials_store = \"keyring\"\n", "= broken", "cli_auth_credentials_store = 3\n"):
            self.same("switch-config", cases, setup=codex_home(config=config), one_by_one=True)
        self.same("switch-nofile", cases, setup=codex_home(auth=None), one_by_one=True)


def digest(email):
    return hashlib.sha256(bytes.fromhex(sign_in(email))).hexdigest()


class RecoverDiff(AdvAccountDiff):
    def test_recover_and_unwind(self):
        two = [[TGT, "pro", {"hex": sign_in(TGT)}], [CUR, "plus", {"hex": sign_in(CUR)}]]
        intent = {"from": 1, "to": 0}
        cases = []

        def recover(store, reads, restart=None, world=None):
            cases.append(["sw.recover", store, {"read": reads}, None if restart is None else {"restart": restart},
                          world or {"app_running": [False]}])
        recover(spec(saved=two), [found(TGT)])
        recover(spec(saved=two, intent=intent), [found(TGT)])
        recover(spec(saved=two, intent=intent), [UNKNOWN])
        recover(spec(saved=two, intent=dict(intent, step="back")), [UNKNOWN])
        recover(spec(saved=two, intent=intent), [found(OTH)])
        recover(spec(saved=two, intent=intent), [found(OTH)], world={"app_running": [True]})
        recover(spec(saved=two, intent=intent), [found(OTH)], world={"app_running": [None]})
        recover(spec(saved=two, intent=dict(intent, step="verify")), [found(OTH)])
        recover(spec(saved=two, intent=dict(intent, step="back", tries=2)), [found(OTH)], [step(True, None)],
                world={"app_running": [True]})
        recover(spec(saved=two, intent=dict(intent, step="back", tries=3)), [found(OTH)], [step()],
                world={"app_running": [True]})
        recover(spec(saved=two, intent=dict(intent, step="back", tries=True)), [found(OTH)], [step(False, None)],
                world={"app_running": [True]})
        recover(spec(saved=two, intent=dict(intent, step="back")), [found(OTH)], [step(True, ("restarted", "closed"))])
        recover(spec(saved=two, intent={"from": 1, "to": "00000000000000ff", "put_in": digest(TGT), "to_email": TGT,
                                        "previous": {"hex": sign_in(CUR)}}), [found(TGT)])
        recover(spec(saved=two, intent={"from": 1, "to": "00000000000000ff", "put_in": digest(TGT), "to_email": TGT,
                                        "previous": {"hex": sign_in(CUR)}}), [found(OTH)])
        recover(spec(saved=two, intent={"from": 1, "to": "00000000000000ff", "put_in": digest(OTH), "to_email": TGT}),
                [found(OTH)])
        recover(spec(saved=two, intent={"from": 1, "to": 0, "previous": "!!notbase64"}), [found(OTH)])
        recover(spec(saved=two, intent={"from": 1, "to": 0, "previous": "e30="}), [found(OTH)])
        recover(spec(saved=two, intent={"from": 5, "to": 0}), [found(OTH)])
        recover(spec(saved=two, intent=intent, lock=["held"]), [found(TGT)])
        recover(spec(saved=two, raw={"switch.intent": {"hex": b"garbage".hex()}}), [found(TGT)])
        recover(spec(saved=two, intent=intent), [5])
        recover(spec(saved=two, intent={"from": 1, "to": 0, "put_in": 7}), [found(OTH)])
        RECORD.append("recover: %d cases" % len(cases))
        self.same("recover", cases, setup=codex_home(auth=TGT), one_by_one=True)
        unwinds = [["sw.unwind", spec(saved=two), {}], ["sw.unwind", spec(saved=two, intent=intent), {"app_running": [False]}],
                   ["sw.unwind", spec(saved=two, intent=intent), {"app_running": [True]}],
                   ["sw.unwind", dict(spec(saved=two, intent=intent), codex=None), {}],
                   ["sw.unwind", spec(saved=two, raw={"switch.intent": {"hex": b"x".hex()}}), {}],
                   ["sw.unwind", spec(saved=two, intent={"from": 1, "to": 0, "put_in": digest(OTH)}), {}],
                   ["sw.unwind", spec(saved=two, intent={"from": 1, "to": "00000000000000ff"}), {}],
                   ["sw.unwind", spec(saved=two, intent={"to": 0}), {}],
                   ["sw.unwind", spec(saved=two, intent={"from": 1, "to": 0, "previous": "!!"}), {}]]
        RECORD.append("unwind: %d cases" % len(unwinds))
        self.same("unwind", unwinds, setup=codex_home(auth=TGT), one_by_one=True)


class ReadAndSaveDiff(AdvAccountDiff):
    def test_read_profile(self):
        account = {"account": {"type": "chatgpt", "email": TGT.lower(), "planType": "pro"}}
        usage = {"rateLimits": {"primary": {"usedPercent": 40, "windowDurationMins": 300, "resetsAt": 1767230000},
                                "secondary": {"usedPercent": 100, "windowDurationMins": 10080, "resetsAt": 1767800000}}}
        sessions = [{"account/read": [account], "account/rateLimits/read": [usage]},
                    {"account/read": [account], "account/rateLimits/read": [{}]},
                    {"account/read": [account], "account/rateLimits/read": [usage],
                     "refresh:account/read": [{"hex": sign_in(TGT, "r2")}]},
                    {"account/read": [{"account": None}]},
                    {"account/read": [{"account": {"type": "chatgpt", "email": OTH}}]},
                    {"account/read": [{"account": {"type": "apikey"}}]},
                    {"open": ["raise"]}, {"account/read": ["raise"]},
                    {"account/read": [account], "account/rateLimits/read": ["raise"],
                     "refresh:account/read": [{"hex": sign_in(TGT, "r3")}]},
                    {"account/read": [5]}, {"account/read": [account], "account/rateLimits/read": [5]}]
        cases = []
        for session in sessions:
            cases.append(["sw.read_profile", spec(), {"saved": 0}, session, NOW, {}])
        cases += [["sw.read_profile", spec(lock=["held"]), {"saved": 0}, sessions[0], NOW, {}],
                  ["sw.read_profile", spec(lock=["free", "held"]), {"saved": 0}, sessions[0], NOW, {}],
                  ["sw.read_profile", spec(), "0000000000000099", sessions[0], NOW, {}],
                  ["sw.read_profile", spec(), 5, sessions[0], NOW, {}],
                  ["sw.read_profile", spec(), {"saved": 0}, sessions[0], None, {}],
                  ["sw.read_profile", spec(), {"saved": 0}, sessions[0], 0, {}]]
        RECORD.append("read_profile: %d cases" % len(cases))
        self.same("read-profile", cases, setup=codex_home(), one_by_one=True)

    def test_save_current_and_add_by_login(self):
        cases = [["sw.save_current", spec(), {"read": [found(CUR)]}], ["sw.save_current", spec(), {"read": [OUT]}],
                 ["sw.save_current", spec(), {"read": [found(None)]}], ["sw.save_current", spec(lock=["held"]),
                                                                         {"read": [found(CUR)]}],
                 ["sw.save_current", spec(), {"read": [found(TGT)]}], ["sw.save_current", spec(), {"read": [5]}]]
        account = {"account": {"type": "chatgpt", "email": OTH, "planType": "team"}}
        logins = [({}, {}, {"account/read": [account], "refresh:account/read": [{"hex": sign_in(OTH)}]}),
                  ({}, {"run": [[1, "", ""]]}, {"account/read": [account]}),
                  ({}, {"run": ["timeout"]}, {"account/read": [account]}),
                  ({"make": ["raise"]}, {}, {"account/read": [account]}),
                  ({}, {}, {"account/read": [account]}),
                  ({}, {}, {"account/read": [{"account": {"type": "apikey"}}], "refresh:account/read": [{"hex": sign_in(OTH)}]}),
                  ({}, {}, {"open": ["raise"]}),
                  ({"argv": [["C:/x/codex.exe", "-c", "a=1"]]}, {}, {"account/read": [account],
                                                                    "refresh:account/read": [{"hex": sign_in(OTH)}]})]
        for backend, runner, session in logins:
            cases.append(["sw.add_by_login", spec(), backend, runner, session, None])
        cases.append(["sw.add_by_login", spec(), {}, {}, logins[0][2], 30])
        cases.append(["sw.add_by_login", spec(lock=["free", "held"]), {}, {}, logins[0][2], None])
        RECORD.append("save_current/add_by_login: %d cases" % len(cases))
        self.same("save-add", cases, setup=codex_home(), one_by_one=True)

"""S7.2b: the two capabilities' codes - account_switch's watch (`engine/account.py`: the salted digest, the change of
account holding core's waits and the counting reset rules, `forget`) and account_auto_switch (`engine/autoswitch.py`: the
look, its reasons not to act, the episode, the 24-hour ceiling, the choice of the account with most room, the switch,
what a switch left settled, the person's own put-in, P7's early answer) - each made with scripted seams over a real
advanced state in a scratch home, driven through the same steps on both sides, held equal to the v0.6.26 final: the
calls made, the notices, the codes' memory and the state read back.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advaccount_engines`.
"""
from __future__ import annotations

import time

from rustdiff.advaccount import AdvAccountDiff, sign_in
from rustdiff.diffs_advaccount_pure import OTHER
from rustdiff.diffs_advaccount_swap import CUR, OTH, TGT, codex_home, found, step

RECORD: list[str] = []
SALT = "0" * 63 + "1"
ARMED = [["move", ["account_switch", "armed"], {"actor": "gui", "at": 100.0}]]
RULES = [["add_reset_rule", ["reset_credit", "codex", 300, 2], {"at": 50.0}],
         ["change_rule", [1], {"base": 3, "adopted_at": 60.0}],
         ["save_windows", [[{"bucket": "codex", "minutes": 300, "open_reset_at": None, "open_full": False,
                             "last_closed_at": None, "resets": 1, "hits": 4, "seen_at": 60.0, "misses": 0}]], {}]]
WANTED = [["account_seen", [], {}], ["reset_rules", [], {"pending": False}],
          ["stamped", ["account_switch", "account_changed_at"], {}],
          ["counted_since", ["account_switch", "changed", 0], {}], ["counted_since", ["account_switch", "held", 0], {}]]
WAITING = [{"interruption_id": "a1", "category": "usage_limit", "state": "waiting_for_usage", "detected_at": 100.0},
           {"interruption_id": "a2", "category": "network", "state": "waiting_retry", "detected_at": 100.0},
           {"interruption_id": "a3", "category": "usage_limit", "state": "waiting_for_usage", "detected_at": 100.0}]


class AccountWatchDiff(AdvAccountDiff):
    def test_the_watch(self):
        other = found(OTH)
        cases = []

        def look(seeds, seams, steps, view=None):
            cases.append(["ea.look", "st", seeds, seams, view or {"records": [WAITING]}, steps, WANTED])
        look([], {"read": [found(CUR)]}, [1000])
        look([], {"read": [found(CUR), found(CUR)], "secrets": {"read": [SALT]}}, [1000, 2000])
        look(ARMED, {"read": [found(CUR), found(CUR)], "secrets": {"read": [SALT]}}, [1000, 2000])
        look(ARMED, {"read": [found(CUR), other], "secrets": {"read": [SALT]}, "hold": [2]}, [1000, 2000])
        look(ARMED + RULES, {"read": [found(CUR), other], "secrets": {"read": [SALT]}, "hold": [1]}, [1000, 2000.5])
        look(ARMED + RULES, {"read": [found(CUR), other], "secrets": {"read": [SALT]}, "ours": [True]}, [1000, 2000])
        look(ARMED, {"read": [found(CUR), other], "secrets": {"read": [None]}}, [1000, 2000])
        look(ARMED, {"read": [found(CUR), {"present": None}, found(None, present=False), other],
                     "secrets": {"read": [SALT]}}, [1000, 2000, 3000, 4000])
        look(ARMED, {"read": [found(CUR), other], "secrets": {"read": ["raise"]}}, [1000, 2000])
        look(ARMED, {"read": [found(CUR)], "secrets": {"write": ["raise"]}}, [1000])
        look(ARMED, {"read": [found(CUR), other], "secrets": {"read": [SALT]}, "hold": ["raise"]}, [1000, 2000])
        look(ARMED, {"read": [found(CUR), other], "secrets": {"read": [SALT]}}, [1000, 2000],
             view={"records": ["raise"]})
        look(ARMED, {"read": [found(CUR), other], "secrets": {"read": [SALT]}}, [1000, 2000],
             view={"records": [[{"category": "usage_limit"}]]})
        look(ARMED, {"read": [found(CUR), {"present": True, "email": None, "kind": "apikey", "plan_word": "weird"}],
                     "secrets": {"read": [SALT]}}, [1000, 2000])
        look(ARMED + [["move", ["account_switch", "armed"], {"actor": "gui", "at": 1500.0}]],
             {"read": [found(CUR), other], "secrets": {"read": [SALT]}}, [1000, 2000])
        look([["save_account_seen", ["0123456789abcdef", "plus"], {"at": 500.0}]] + ARMED,
             {"read": [found(CUR)], "secrets": {"read": [SALT]}, "hold": [3]}, [1000])
        look([], {"read": [5]}, [1000])
        RECORD.append("account watch: %d cases" % len(cases))
        self.same("account-watch", cases, one_by_one=True)
        forgets = [["ea.forget", "st", [], {}, WANTED[:1]],
                   ["ea.forget", "st", [["save_account_seen", ["0123456789abcdef", None], {"at": 5.0}]], {}, WANTED[:1]],
                   ["ea.forget", "st", [["save_account_seen", ["0123456789abcdef", None], {"at": 5.0}]],
                    {"delete": ["raise"]}, WANTED[:1]]]
        self.same("account-forget", forgets, one_by_one=True)


AUTO_WANTED = [["stamped", ["account_auto_switch", "auto_switched_at"], {}],
               ["counted_since", ["account_auto_switch", "all_exhausted", 0], {}],
               ["counted_since", ["account_auto_switch", "ceiling", 0], {}],
               ["counted_since", ["account_auto_switch", "switched", 0], {}],
               ["counted_since", ["account_auto_switch", "not_signed_in", 0], {}],
               ["counted_since", ["account_auto_switch", "unverified", 0], {}],
               ["counted_since", ["account_auto_switch", "sweep_failed", 0], {}]]
SETTINGS = {"settings": [{"enabled": True, "observe_only": False}], "records": [WAITING]}
NOW = 1767225600.0
ROOM = {"account/read": [{"account": {"type": "chatgpt", "email": TGT.lower(), "planType": "pro"}}],
        "account/rateLimits/read": [{"rateLimits": {"primary": {"usedPercent": 20, "windowDurationMins": 300,
                                                                "resetsAt": 1767230000}}}]}
FULL = {"account/read": [{"account": {"type": "chatgpt", "email": TGT.lower(), "planType": "pro"}}],
        "account/rateLimits/read": [{"rateLimits": {"primary": {"usedPercent": 99, "windowDurationMins": 300,
                                                                "resetsAt": 1767230000}}}]}


def saved(*emails):
    return [[email, "plus", sign_in(email)] for email in emails]


class AutoSwitchDiff(AdvAccountDiff):
    def test_the_look(self):
        waiting = [dict(each, detected_at=NOW - 400) for each in WAITING]
        view = {"settings": [{"enabled": True, "observe_only": False}], "records": [waiting]}
        happy = {"reader": {"read": [found(CUR), found(CUR), found(TGT)]}, "session": ROOM,
                 "restart": {"restart": [step()]}, "world": {"inventory": [[]]}}
        base = {"home": "st", "codex": "codex", "saved": saved(TGT, CUR)}
        cases = []

        def look(seams, steps, *, spec=None, seen=None, seeds=()):
            cases.append(["ec.look", "st", list(seeds), spec or base, seams, seen or view, steps, AUTO_WANTED])
        look(happy, [NOW])
        look(happy, [NOW], seen={"settings": [{"enabled": False}], "records": [waiting]})
        look(happy, [NOW], seen={"settings": [{"enabled": True, "observe_only": True}], "records": [waiting]})
        look(happy, [NOW], seen={"settings": ["raise"], "records": [waiting]})
        look(happy, [NOW], seen={"settings": [{"enabled": True}], "records": [WAITING]})
        look(dict(happy, busy={"busy": [["turn_running"]]}), [NOW])
        look(dict(happy, world={"inventory": [[OTHER]]}), [NOW])
        look(dict(happy, idle={"idle": [10]}), [NOW])
        look(dict(happy, idle={"idle": [None]}), [NOW])
        look(happy, [NOW, NOW + 60])
        look(dict(happy, session=FULL), [NOW])
        look(happy, [NOW], spec={"home": "st", "codex": "codex", "saved": saved(CUR)})
        look(dict(happy, reader={"read": [{"present": None}]}), [NOW])
        look(happy, [NOW], spec=dict(base, updates=[[0, {"failed_at": 5}]]))
        look(happy, [NOW], spec=dict(base, updates=[[0, {"exhausted_until": int(NOW) + 999}]]))
        look(dict(happy, reader={"read": [found(CUR), found(CUR), found(OTH)]},
                  restart={"restart": [step(), step()]}), [NOW])
        look(dict(happy, reader={"read": [found(CUR), found(CUR), {"present": None}]}), [NOW])
        look(dict(happy, restart={"restart": [step(False, None)]}), [NOW])
        look(dict(happy, busy={"busy": [[], [], ["queued"]]}), [NOW])
        look(happy, [NOW], spec=dict(base, intent={"from": 1, "to": 0}))
        look(dict(happy, reader={"read": [found(OTH)] * 4}), [NOW, NOW + 60],
             spec=dict(base, intent={"from": 1, "to": 0, "step": "back"}))
        look(happy, [NOW], spec=dict(base, raw={"switch.times": {"hex": (b"SEALED:" + (
            '{"times": [%s]}' % ", ".join(str(int(NOW) - 100 * index) for index in range(10))).encode()).hex()}}))
        look(happy, [NOW], spec=dict(base, raw={"switch.times": {"hex": b"SEALED:{bad".hex()}}))
        look(happy, [NOW], spec=dict(base, raw={"switch.times": {"hex": b"SEALED:{\"times\": 5}".hex()}}))
        look(happy, [NOW], seeds=[["stamp", ["account_auto_switch", "auto_switch_count", 10], {}],
                                  ["stamp", ["account_auto_switch", "auto_switch_day", int(NOW // 86400) + 1], {}]])
        look(happy, [NOW], spec=dict(base, lock=["held"]))
        look(happy, [["manual", NOW, {"saved": 0}]])
        look(dict(happy, idle={"idle": [5]}), [["put_in", NOW, {"saved": 0}], ["manual", NOW + 1, {"saved": 0}]])
        look(happy, [["settle", NOW]], spec=dict(base, intent={"from": 1, "to": 0}))
        look(happy, [["settle", NOW]])
        record = {"category": "usage_limit", "state": "waiting_for_usage"}
        look(happy, [NOW, ["schedule", NOW + 10, record, NOW + 100], ["schedule", NOW + 10, record, NOW],
                     ["schedule", NOW + 10, dict(record, state="submitting"), NOW + 100],
                     ["schedule", NOW + 10, dict(record, category="network"), NOW + 100],
                     ["schedule", NOW + 10, dict(record, state=["x"]), NOW + 100],
                     ["schedule", NOW + 950, record, NOW + 1000], ["schedule", NOW + 10, 5, NOW + 100],
                     ["schedule", NOW + 10, record, "x"]])
        look(happy, [["schedule", NOW, {"category": "usage_limit", "state": "waiting_for_usage"}, NOW + 5]],
             seeds=[["stamp", ["account_auto_switch", "auto_switched_at", int(NOW) - 100], {}]])
        RECORD.append("autoswitch: %d cases" % len(cases))

        def setup(root):
            codex_home()(root)
        self.same("autoswitch", cases, setup=setup, one_by_one=True)

    def test_a_home_that_cannot_be_switched(self):
        waiting = [dict(each, detected_at=NOW - 400) for each in WAITING]
        view = {"settings": [{"enabled": True, "observe_only": False}], "records": [waiting]}
        case = ["ec.look", "st", [], {"home": "st", "codex": "codex", "saved": saved(TGT, CUR)},
                {"reader": {"read": [found(CUR)]}, "world": {"inventory": [[]]}}, view, [NOW], AUTO_WANTED]
        self.same("autoswitch-keyring", [case], setup=codex_home(config="cli_auth_credentials_store = \"keyring\"\n"),
                  one_by_one=True)


def _unused():
    return time

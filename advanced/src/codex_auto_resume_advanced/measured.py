# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What each measurement found, as this build ships it: its verdict and the Codex it was made on.

The owner measures on a real machine (measure.py), and each run writes one content-free record
to the source tree's docs/evidence/live/ (evidence.py). An installed copy has no such directory,
so what a release knows of the measurements is this table, and
advanced/tests/test_advanced_measured.py keeps it equal to the records beside it: a record
re-measured without this table following fails the tests.

A measurement is here only when it settled - a pass or a fail, the person's completion counting
for a blocked probe (evidence.outcome). One that is not here was never measured, as far as this
build knows. A capability whose route rests on a measurement that failed, or that has no pass
for the Codex in force, says so as a warning in its statement (arming.warnings_for); it is
never withheld for it (the owner's rule of 2026-09-26, which replaced decision C7).

Pure: a table, and nothing read.
"""
from __future__ import annotations

from .vocabulary import Measurement, Verdict

# The Codex the 2026-10-10 measurements were made on, as `codex --version` names it - the same
# words the Compatibility Registry's view carries as the engine version. Every earlier reading
# (codex-cli 0.158.0-alpha.2.1, 2026-09-26 and 09-28) was made again on it.
CLI_0162_ALPHA_17_2 = "codex-cli 0.162.0-alpha.17.2"
# The Codex of 2026-10-17 (app 26.1013.3656.0): the readings the beta.4 capabilities rest on were made
# again on it - MW, M1, M2b, M5, M6, M7, MP1-MP3, MIPC, and stage 4's MO, M6B, MX, MF and M3B. The rest
# stay on the engine they were made on, and a statement on 0.163 calls them unmeasured.
CLI_0163_ALPHA_10_2 = "codex-cli 0.163.0-alpha.10.2"
# The Codex of 2026-10-26: M2b made again on it (PR #53 asked; the goal on a held thread rests on it).
CLI_0164_ALPHA_11_1 = "codex-cli 0.164.0-alpha.11.1"
# The Codex of 2026-10-29: issue #50's MIMG, MSTEER, MOPEN and MSTEER2 made on it.
CLI_0165_ALPHA_1_2 = "codex-cli 0.165.0-alpha.1.2"

MEASURED = {
    Measurement.M1: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.M2: (Verdict.FAIL, CLI_0162_ALPHA_17_2),
    Measurement.M2B: (Verdict.PASS, CLI_0164_ALPHA_11_1),
    Measurement.M3: (Verdict.FAIL, CLI_0162_ALPHA_17_2),
    Measurement.M4: (Verdict.FAIL, CLI_0162_ALPHA_17_2),
    Measurement.M5: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.M6: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.M7: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.MW: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.MA: (Verdict.PASS, CLI_0162_ALPHA_17_2),
    Measurement.MH: (Verdict.PASS, CLI_0162_ALPHA_17_2),
    Measurement.MP1: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.MP2: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.MP3: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    # 2026-10-11, at the owner's word that one reset credit may be spent.
    Measurement.MR: (Verdict.PASS, CLI_0162_ALPHA_17_2),
    # 2026-10-11, once that credit was spent and the account had none left.
    Measurement.MN: (Verdict.PASS, CLI_0162_ALPHA_17_2),
    # 2026-10-13, after a 5-hour reset that passed with no Codex use.
    Measurement.MU: (Verdict.PASS, CLI_0162_ALPHA_17_2),
    # 2026-10-16 (records 22f19fb7, da367839, f0f1f1fd): the Desktop's IPC pipe starts, adds to and interrupts a turn of
    # a conversation the app holds; Codex documents no supported shared app-server the app uses; `codex cloud` reads a
    # cloud task's state but nothing continues one - partial, which is not a pass.
    Measurement.MIPC: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.MAWS: (Verdict.FAIL, CLI_0162_ALPHA_17_2),
    Measurement.MCLOUD: (Verdict.FAIL, CLI_0162_ALPHA_17_2),
    # 2026-10-15 and 16, stage 4's nine (v0.6.16-beta.4), Codex closed or open as each needs.
    Measurement.MC1: (Verdict.PASS, CLI_0162_ALPHA_17_2),
    Measurement.MXA: (Verdict.PASS, CLI_0162_ALPHA_17_2),
    Measurement.MX: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.MF: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    # A fail narrows a route or is its capability's warning, never its end (the owner's rule).
    Measurement.MB: (Verdict.FAIL, CLI_0162_ALPHA_17_2),
    Measurement.MC2: (Verdict.FAIL, CLI_0162_ALPHA_17_2),
    # 2026-10-17, made again on codex-cli 0.163.0-alpha.10.2: all three passed there (they had failed on 0.162).
    Measurement.MO: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.M3B: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.M6B: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    # 2026-10-20 (v0.6.17, issues #42 and #47), the Desktop not holding the conversations: a continuation queued for
    # opening with no marker ran once on open and was found by its client id; two at once each ran once in its own
    # conversation. MQG, made again the same night with a goal that takes many turns: on open the queued message ran
    # first and once, then the goal carried on, a turn at a time, until it reached its own end.
    Measurement.MQO: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.MQP: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    Measurement.MQG: (Verdict.PASS, CLI_0163_ALPHA_10_2),
    # 2026-10-29 (v0.6.20, issue #50), the measurement session: a queued message with a local image file was shown at once
    # as the person's own with its picture and ran (MIMG); turn/steer from the product's own app-server session was
    # refused (-32600) for a turn the Desktop was running (MSTEER).
    Measurement.MIMG: (Verdict.PASS, CLI_0165_ALPHA_1_2),
    Measurement.MSTEER: (Verdict.FAIL, CLI_0165_ALPHA_1_2),
    # The same evening, the measurement session again: a steer over the Desktop's IPC pipe was accepted and reached the
    # running turn once, but the app never showed the line as the person's message (MSTEER2). MOPEN first failed against
    # ten seconds (the app held a conversation opened through its link after about 13 s); made again that night against
    # the owner's thirty, its load timed by the lock's holder count alone, the window came to the front and the app held
    # the conversation within 2-10 s, so it passed - and open_to_send is offered.
    Measurement.MOPEN: (Verdict.PASS, CLI_0165_ALPHA_1_2),
    Measurement.MSTEER2: (Verdict.FAIL, CLI_0165_ALPHA_1_2),
}

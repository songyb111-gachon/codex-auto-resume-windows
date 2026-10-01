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

# The Codex the 2026-09-26 measurements were made on, as `codex --version` names it - the same
# words the Compatibility Registry's view carries as the engine version.
CLI_0158_ALPHA_2_1 = "codex-cli 0.158.0-alpha.2.1"

MEASURED = {
    Measurement.M1: (Verdict.PASS, CLI_0158_ALPHA_2_1),
    Measurement.M2: (Verdict.FAIL, CLI_0158_ALPHA_2_1),
    Measurement.M3: (Verdict.FAIL, CLI_0158_ALPHA_2_1),
    Measurement.M4: (Verdict.FAIL, CLI_0158_ALPHA_2_1),
    Measurement.M5: (Verdict.FAIL, CLI_0158_ALPHA_2_1),
    Measurement.M6: (Verdict.PASS, CLI_0158_ALPHA_2_1),
    Measurement.M7: (Verdict.PASS, CLI_0158_ALPHA_2_1),
    Measurement.MW: (Verdict.PASS, CLI_0158_ALPHA_2_1),
    # Completed by the owner at the app on 2026-09-28, on the same engine.
    Measurement.MA: (Verdict.PASS, CLI_0158_ALPHA_2_1),
    Measurement.MH: (Verdict.PASS, CLI_0158_ALPHA_2_1),
}

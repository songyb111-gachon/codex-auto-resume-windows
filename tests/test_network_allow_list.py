"""The advanced edition's network allow-list in one place (v0.6.19, plans/v0619-design/D-groundwork.md section 4):
test_privacy_claims' two network tests read one constant, ADVANCED_NETWORK_MODULES - the paths under advanced/src/ that
may reach the network - empty until a capability that does was built, and from the courier (v0.6.20,
plans/v0619-design/D-courier.md) its package alone; and the standard archive's scan (src/, scripts/) can never be
allowed anything through it.

    PYTHONPATH="src;tests" python -m unittest test_network_allow_list
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import test_privacy_claims as claims  # noqa: E402

COURIER = "advanced/src/codex_auto_resume_advanced/courier/"
# One line found in one shipped advanced file alone, standing in for a networking import or verb.
ONLY_HERE = "advanced/src/codex_auto_resume_advanced/report/github.py"
LINE = r"^\s*from \.\.codex\.wmi_escape import _ExtendedLimits\b"
REACHING = "test_exactly_the_bootstrap_and_the_courier_reach_the_network"


def outcome(test_name, **patched) -> bool:
    """Whether test_privacy_claims' CodePropertyTests.`test_name` passes with `patched` in place."""
    result = unittest.TestResult()
    if patched:
        with patch.multiple(claims, **patched):
            claims.CodePropertyTests(test_name).run(result)
    else:
        claims.CodePropertyTests(test_name).run(result)
    return result.wasSuccessful()


class AllowListTests(unittest.TestCase):
    def test_it_names_the_courier_s_package_alone(self):
        """Fails with the constant reverted: there is no one place, and nothing to read. From v0.6.19 it names the one
        capability package that reaches the network, the courier's, and nothing else."""
        self.assertIsInstance(claims.ADVANCED_NETWORK_MODULES, frozenset)
        self.assertEqual(claims.ADVANCED_NETWORK_MODULES, frozenset({COURIER}))

    def test_it_allows_only_what_it_names_and_never_the_standard_archive(self):
        with patch.object(claims, "ADVANCED_NETWORK_MODULES", frozenset({COURIER, ONLY_HERE, "src/", "scripts/"})):
            self.assertTrue(claims.network_allowed(COURIER + "push.py"))
            self.assertTrue(claims.network_allowed(ONLY_HERE))
            self.assertFalse(claims.network_allowed("advanced/src/codex_auto_resume_advanced/courierx.py"))
            self.assertFalse(claims.network_allowed("advanced/src/codex_auto_resume_advanced/report/flow.py"))
            for standard in ("src/codex_auto_resume/notifier.py", "scripts/watcher_launcher.py"):
                with self.subTest(standard):
                    self.assertFalse(claims.network_allowed(standard), "the standard archive is never allowed")

    def test_the_import_test_reads_it(self):
        """A networking import in a file the constant names passes; the same file unnamed fails it."""
        found = re.compile(LINE, re.MULTILINE)
        self.assertFalse(outcome("test_the_recovery_runtime_imports_no_networking_module", NETWORKING=found))
        self.assertTrue(outcome("test_the_recovery_runtime_imports_no_networking_module", NETWORKING=found,
                                ADVANCED_NETWORK_MODULES=frozenset({ONLY_HERE, COURIER})))

    def test_the_reaching_files_test_reads_it(self):
        reaching = re.compile(claims.PS_NETWORK.pattern + "|" + LINE[len(r"^\s*"):], re.IGNORECASE)
        self.assertFalse(outcome(REACHING, PS_NETWORK=reaching))
        self.assertTrue(outcome(REACHING, PS_NETWORK=reaching, ADVANCED_NETWORK_MODULES=frozenset({ONLY_HERE, COURIER})))

    def test_without_the_courier_s_package_its_files_are_offenders(self):
        """The courier's networking imports pass only because the constant names its package."""
        self.assertFalse(outcome("test_the_recovery_runtime_imports_no_networking_module",
                                 ADVANCED_NETWORK_MODULES=frozenset()))

    def test_both_pass_as_they_are(self):
        for name in ("test_the_recovery_runtime_imports_no_networking_module", REACHING):
            with self.subTest(name):
                self.assertTrue(outcome(name))


if __name__ == "__main__":
    unittest.main()

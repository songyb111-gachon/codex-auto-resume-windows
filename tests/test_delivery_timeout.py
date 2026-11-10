"""How long the watcher waits to see a continuation delivered (v0.6.23, the owner's decision of 2026-11-10): 300 seconds.

A bare Engine keeps the 180 that v0.6.10's scenarios step past (tests/neutral.py MODULES, which may not change); what is
held here is that every engine the watcher builds is given the 300.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from codex_auto_resume.engine import Engine
from codex_auto_resume.engine.options import DELIVERY_TIMEOUT, WATCHER_OPTIONS

APP = Path(__file__).resolve().parents[1] / "src" / "codex_auto_resume" / "runtime" / "app.py"


class DeliveryTimeoutTests(unittest.TestCase):
    def test_the_watcher_waits_three_hundred_seconds(self):
        self.assertEqual(DELIVERY_TIMEOUT, 300)
        self.assertEqual(WATCHER_OPTIONS, {"delivery_timeout_seconds": 300})

    def test_it_is_longer_than_the_longest_delivery_measured_by_a_margin(self):
        self.assertGreater(DELIVERY_TIMEOUT, 144.3 * 2)

    def test_an_engine_given_them_waits_that_long_and_a_bare_one_as_the_scenarios_do(self):
        given = Engine(None, None, None, options=WATCHER_OPTIONS)
        self.assertEqual(given.options["delivery_timeout_seconds"], 300)
        self.assertEqual(Engine(None, None, None).options["delivery_timeout_seconds"], 180)

    def test_every_engine_the_watcher_builds_is_given_them(self):
        """Fails with either builder's options taken away: a home's engine or the default one back at 180."""
        calls = [node for node in ast.walk(ast.parse(APP.read_text(encoding="utf-8")))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Engine"]
        self.assertEqual(len(calls), 2)
        for call in calls:
            given = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
            self.assertIsInstance(given.get("options"), ast.Attribute, call.lineno)
            self.assertEqual(given["options"].attr, "WATCHER_OPTIONS", call.lineno)


if __name__ == "__main__":
    unittest.main()

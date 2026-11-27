"""The advanced surfaces (seat S7.3a): every answer of `surfaces.answer` over the scenarios of advsurface.py, the
reference tag's on its own and car-adv's through the advanced proxy, line by line (advsurface.py says how)."""
from __future__ import annotations

import unittest

from rustdiff import advsurface


class AdvSurfaceDiff(unittest.TestCase):
    """Status, tray and diagnostics; every bridge command; the MCP tools - over eight
    homes, on the bundled reference Python."""

    def test_every_answer_is_the_tags(self):
        python, python_error, python_rc = advsurface.run(False)
        rust, rust_error, rust_rc = advsurface.run(True)
        self.assertEqual(python_rc, 0, python_error)
        self.assertEqual(rust_rc, 0, rust_error)
        self.assertGreater(len(python), 150, "the scenarios ran to their end")
        for number, (want, got) in enumerate(zip(python, rust), 1):
            self.assertEqual(want, got, "line %d" % number)
        self.assertEqual(len(python), len(rust))


if __name__ == "__main__":
    unittest.main()

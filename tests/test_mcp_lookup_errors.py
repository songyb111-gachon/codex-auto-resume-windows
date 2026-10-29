"""v0.6.18 (audit M2): only an unknown tool or resource is "invalid params"; a lookup that breaks inside is internal.

The server answered every LookupError as INVALID_PARAMS with the exception's own text. That was meant for an
unknown tool and an unknown resource; it also caught a KeyError or an IndexError raised inside a handler or the
control layer (sqlite3.Row raises IndexError for a missing column), which then went out as the caller's mistake,
in raw text, against D9's static codes. Now only those two are invalid params, and anything else is an internal
error in the server's one static sentence.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import control, mcpserver  # noqa: E402
from test_mcp import McpTestCase  # noqa: E402

SECRET = "a column name only the inside knows"


class LookupErrorTests(McpTestCase):
    def test_a_lookup_that_breaks_inside_is_an_internal_error_in_static_words(self):
        for error in (KeyError(SECRET), IndexError(SECRET)):
            with self.subTest(error=type(error).__name__), \
                    patch.object(control.Control, "get_status", side_effect=error):
                reply = self.call("get_status")
            self.assertEqual(reply["error"]["code"], mcpserver.INTERNAL_ERROR)
            self.assertNotIn(SECRET, str(reply))

    def test_an_unknown_tool_and_resource_are_still_invalid_params(self):
        reply = self.call("no_such_tool")
        self.assertEqual((reply["error"]["code"], reply["error"]["message"]),
                         (mcpserver.INVALID_PARAMS, "unknown tool"))
        reply = self.converse({"jsonrpc": "2.0", "id": 3, "method": "resources/read",
                               "params": {"uri": "ui://elsewhere"}})[0]
        self.assertEqual((reply["error"]["code"], reply["error"]["message"]),
                         (mcpserver.INVALID_PARAMS, "unknown resource"))


if __name__ == "__main__":
    unittest.main()

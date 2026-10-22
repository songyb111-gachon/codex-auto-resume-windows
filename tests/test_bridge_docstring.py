"""v0.6.18 (audit M5): the bridge's own description says who drives the product through it.

controlcli's docstring said the MCP server drives the product through the bridge; it calls the control layer
directly (mcp/server.py builds a Control and never sends a bridge command). A reader who trusted the docstring would
look for MCP's checks in the wrong place.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import controlcli  # noqa: E402

SERVER = Path(controlcli.__file__).resolve().parent / "mcp" / "server.py"


class BridgeDocstringTests(unittest.TestCase):
    def test_the_mcp_server_calls_the_control_layer_and_the_docstring_says_so(self):
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    and (node.module or "").endswith("control") for alias in node.names}
        self.assertIn("Control", imported, "the MCP server builds the control layer itself")
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name) and node.value.id == "controlcli"}
        self.assertNotIn("dispatch", used, "and never sends a bridge command")
        opening = controlcli.__doc__.split("\n\n")[1]
        self.assertNotIn("MCP server both drive", " ".join(opening.split()))
        self.assertIn("calls the same control layer directly", " ".join(opening.split()))


if __name__ == "__main__":
    unittest.main()

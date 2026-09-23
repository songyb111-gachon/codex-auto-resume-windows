"""The MCP server's entry point, which is a path other programs hold.

The plugin's `.mcp.json`, the installer's bootstrap script, the release archive's own check
and the launcher all name `src/codex_auto_resume/mcpserver.py`, so this file stays where it
is whatever the code inside it does. (Spelling the bootstrap's own filename here would put
it in a third place, and `tests/test_compat_surfaces.py` counts the places it appears.) Since v0.6.10-alpha that code is `mcp/`:

    mcp/tools.py    what the server offers Codex - the tools, their schemas, the resource
    mcp/server.py   what it does about them - the JSON-RPC loop and every tool's body
    mcp/assets/     the settings panel's own stylesheet and script

Everything this module gave still reads as `mcpserver.<name>`, so nothing that imports it
changed, and `main` is still `main`.
"""
from __future__ import annotations

from .mcp.server import (INTERNAL_ERROR,
                         INVALID_PARAMS,
                         INVALID_REQUEST,
                         METHOD_NOT_FOUND,
                         PARSE_ERROR,
                         PROTOCOL_VERSION,
                         SERVER_NAME,
                         STARTER_GRACE_SECONDS,
                         SUPPORTED_PROTOCOLS,
                         Server,
                         main)  # noqa: F401
from .mcp.tools import (PANEL_APPEARANCE,
                        RESOURCES,
                        SETTINGS_UI,
                        TOOLS,
                        USER_GROUPS,
                        settings_schema)  # noqa: F401

if __name__ == "__main__":
    import sys

    sys.exit(main())

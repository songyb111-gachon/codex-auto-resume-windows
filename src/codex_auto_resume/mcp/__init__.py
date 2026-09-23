"""The settings panel Codex shows, and the server that hands it over.

    tools.py      what the server offers: seventeen tools, their schemas, the one resource
    server.py     what it does about them: the JSON-RPC loop and every tool's body
    assets/       the panel's own stylesheet and script, as the page carries them

`mcpserver.py` beside this package is the path other programs hold - the plugin's `.mcp.json`,
the installer's bootstrap, the release archive's own check and the launcher all name it - so it
stayed where it is and re-exports what moved. `mcpui.py` is still beside it too; it becomes
`panel.py` here with the renames that end step 13.

`assets/panel.css` and `assets/panel.js` were 2,174 of `mcpui.py`'s 2,332 lines, written as two
raw strings in the middle of it; they are the same bytes, read at import. Each begins with a
blank line, which is the newline that followed the opening quotes and is part of what the page
has always carried - the page Codex receives did not change by one byte.

Being Python was what made those lines shipped, scanned and read for free, so as files each of
those is said instead: `tests/srcscan.py` lists them beside the modules, so every rule about
where a word may live reads them; `tests/test_repo_hygiene.py` reads `.css` and `.js` as text;
`build/make_release.py` refuses to build a payload without them; and every test that held the
panel to something still reads it through `mcpui._STYLE` and `mcpui._SCRIPT`, which have not
moved.
"""

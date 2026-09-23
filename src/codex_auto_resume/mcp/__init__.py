"""The settings panel Codex shows, and the server that hands it over.

Today this package holds the panel's own two files and nothing else. `assets/panel.css` and
`assets/panel.js` were 2,174 of `mcpui.py`'s 2,332 lines, written as two raw strings in the
middle of it; they are the same bytes, read at import. Each begins with a blank line, which
is the newline that followed the opening quotes and is part of what the page has always
carried - the page Codex receives did not change by one byte.

The rest of step 13 brings `mcpserver.py`'s body here as `tools.py` and `server.py`, and
`mcpui.py` itself as `panel.py`, at which point this docstring can say what the package is
rather than what it is becoming.

The two files are code the product ships and a browser runs, so they are covered like code:
`tests/srcscan.py` lists them beside the modules, so every rule about where a word may live
reads them; `tests/test_repo_hygiene.py` reads `.css` and `.js` as text;
`build/make_release.py` refuses to build a payload without them; and every test that held
the panel to something still reads it through `mcpui._STYLE` and `mcpui._SCRIPT`, which have
not moved.
"""

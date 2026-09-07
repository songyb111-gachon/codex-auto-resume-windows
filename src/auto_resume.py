"""Command-line entry point.

The package directory is put on the path explicitly rather than relied upon. Python
normally prepends a script's own directory, but the embeddable distribution this
product ships replaces `sys.path` wholesale from its `._pth` file and turns that
behaviour off - so the documented command worked from a source checkout with a system
Python and failed with the interpreter that actually ships, reporting a missing module
for a package sitting next to it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codex_auto_resume.cli import main       # noqa: E402  (path set up above)

if __name__ == "__main__":
    sys.exit(main())

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
from codex_auto_resume.startup import again_under_chosen_python  # noqa: E402

if __name__ == "__main__":
    # A run from source goes on under the newest Python installed, and remote debugging is off (PEP 768) where whatever
    # started this did not say so - a person, a sign-in or notification-button value; what the product starts itself
    # passes startup.NO_REMOTE_DEBUG from an interpreter already chosen (startup.again_under_chosen_python).
    again = again_under_chosen_python(__file__)
    sys.exit(main() if again is None else again)

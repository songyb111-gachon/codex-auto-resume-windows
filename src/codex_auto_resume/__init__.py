"""Local Windows Codex auto-resume, limited to desktop-owned loaded threads.

`__version__` is read from the plugin manifest rather than written here. There used to be a
literal in this file, and it sat at the first release's number through four more of them
while everything else - the manifest, the settings window, the release archive - moved on.
One number that everything reads cannot go stale the way two numbers do.
"""


def __getattr__(name):
    # Resolved on demand: importing this package should not read a file, and most callers
    # never ask for the version at all.
    if name == "__version__":
        from .config import version
        return version()
    raise AttributeError("module %r has no attribute %r" % (__name__, name))

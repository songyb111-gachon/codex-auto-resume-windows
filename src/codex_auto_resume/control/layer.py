"""The control layer itself, assembled.

`Control` is one class in eight files. It is composed here rather than in the package's
`__init__`, so that the front beside this holds a docstring and re-exports and no code, which
is what `tests/test_reexports.py` reads a front as.

The order the mixins are named in is the order a name is looked up in, so it is written down
rather than chanced; `tests/test_control_shape.py` holds it, and holds that no two of them
define the same method.

The layer holds the edition's plug too (domain/plug.py), which is how every surface that calls
it - the bridge, the MCP server, the icon, a card's button - reaches the plug: a watcher hands
over the one it runs with, and anything else is given this home's the first time it asks.
"""
from __future__ import annotations

from .. import config, edition
from ..domain.plug import guard
from .actions import ActionsMixin
from .codexstart import CodexStartMixin
from .policy import SettingsMixin
from .preview import PreviewMixin
from .records import RecordsMixin
from .seen import SeenMixin
from .state import StateMixin
from .watcher import WatcherMixin


class Control(StateMixin, SeenMixin, SettingsMixin, RecordsMixin, PreviewMixin,
              ActionsMixin, CodexStartMixin, WatcherMixin):
    """Bound to one runtime home. Cheap to construct; opens the store per call."""

    def __init__(self, home=None, *, plug=None):
        self.paths = home if isinstance(home, config.Paths) else config.Paths(home)
        self._seen = None              # (the file's (mtime_ns, size), its time) as last read
        self._plug = None if plug is None else guard(plug)

    @property
    def plug(self):
        """The edition's plug as core holds one: the one this layer was given, or this home's,
        looked for the first time a surface asks rather than every time a layer is made."""
        if self._plug is None:
            self._plug = guard(edition.plug(self.paths))
        return self._plug

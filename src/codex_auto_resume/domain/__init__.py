"""The domain: what the product's values are, with no side effects.

The lowest layer of the package (tests/test_layers.py). A module here imports the standard
library only, and only the parts of it that touch no clock, no file and no process, so what
it says is the same wherever and whenever it is asked - and it is what a port of the core to
another language has to say too.

`ids` is every identifier the product reads or writes, with the one parser for each kind.

Nothing is imported here: a caller names the module it uses.
"""

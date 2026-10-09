"""The edition's plug's own work, claimed and guarded as core's is (v0.6.14).

What a plug answers and core carries out of its own is held to the same write lock as core's claims and
launches: P8's errand makes its one irrevocable write - a request to Codex - inside `errand_guard`, which
a Pause, Observe only or quiet hours that committed first refuse. The standard edition's plug answers
none of it, so none of this runs there.
"""
from __future__ import annotations

from contextlib import contextmanager


class PlugClaimsMixin:
    @contextmanager
    def errand_guard(self, *, held=None):
        """The guard of P8's errand (v0.6.14): the one thing an errand of the edition's plug cannot take
        back - a request it makes of Codex - is made inside this, as the queue launch is made inside
        `submission_guard`. `permitted` is recovery on and not only observed, read under the store's
        write lock, and nothing `held` says: what the engine knows and the store does not - an
        administrator's DisableAutoResume, Observe only as the settings say it, quiet hours
        (engine/options.py, errand_held). A Pause that commits first refuses it; the errand waits for
        its answer outside, as the transport lets the launch guard go before its receipt."""
        with self._transaction() as connection:
            settings = self._read_settings(connection)
            permitted = bool(settings["enabled"] and not settings["observe_only"])
            if permitted and held is not None:
                permitted = not held()
            yield permitted

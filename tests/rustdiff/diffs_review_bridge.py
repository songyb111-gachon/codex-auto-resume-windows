"""Review of the quiet bridge commands (seat review6b, outputs/plans/v0627-rust/REVIEW-bridge.md): inputs and paths
the S5.1a diffs do not feed, each run through the reference tag's `controlcli` and through car-control (`car-harness`,
`bridge.run`) on the same scratch installation and world, as diffs_bridge.BridgeBase runs them. Every test here FAILS
on car-v0627-review6b (3c4434ca3); each names the finding it reproduces.

Run by run.py with diffs.py (`-k diffs_review_bridge`); never by the lanes' discovery.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time

from rustdiff import bridgeworld as bw
from rustdiff.diffs_bridge import BridgeBase, lines, request


def stamp(seconds: float) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(seconds))


def dangling_junction(workspace: Path, relative: str) -> None:
    """A junction at `home/<relative>` whose target is gone (a junction needs no privilege)."""
    import _winapi

    target = workspace / "home" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        target.unlink()
    gone = workspace / "gone"
    gone.mkdir(exist_ok=True)
    _winapi.CreateJunction(str(gone), str(target))
    gone.rmdir()


class ArgumentTextDiff(BridgeBase):
    """R-S1: an argument given as JSON text whose string holds a lone surrogate (an escape of the request line, so a
    real U+D800 inside the inner text's quotes). `json.loads` reads that text and the command answers it (and the
    reference's serve then dies writing the second reply, which echoes the name); car-control's `payload` refuses any
    text that is not UTF-8 before it parses it (bridge.rs:150-153): "argument must be JSON" three times, exit 0."""

    def test_an_argument_text_holding_a_lone_surrogate_in_a_string(self):
        stream = lines(
            r'{"id": 1, "command": "timeline", "argument": "{\"interruption_id\": \"\ud800\"}"}',
            r'{"id": 2, "command": "check-setting", "argument": "{\"name\": \"x\ud800\", \"value\": 1}"}',
            r'{"id": 3, "command": "statistics", "argument": "{\"days\": 3, \"note\": \"\udc00\"}"}',
        )
        self.same("golden", stream, label="argument texts holding a lone surrogate")


class ReplaceDiff(BridgeBase):
    """R-S2: car-control's own writes replace with std::fs::rename (seen.rs:91, oncewords.rs:132, aside.rs:123), which
    on Windows asks MoveFileExW to replace and falls back to a POSIX-semantics rename; the reference's os.replace is
    MoveFileExW alone, and its os.rename never replaces. A name held by a junction (or a file a reader holds open with
    share-delete, REVIEW-int5 S2) is replaced by Rust and refused by the reference."""

    def test_failure_seen_over_a_dangling_junction(self):
        stream = lines(request("failure-seen", ident=1), request("status", ident=2))
        self.same("golden", stream, tune=lambda workspace: dangling_junction(workspace, "config/failure-seen.json"),
                  label="failure-seen over a dangling junction")

    def test_a_dangling_junction_at_the_first_set_aside_name(self):
        def tune(workspace: Path):
            (workspace / "home" / "config" / "settings.json").write_text("{ this is not JSON", encoding="utf-8")
            dangling_junction(workspace, "config/settings.unreadable-%s.json" % stamp(bw.NOW))

        self.same("empty", lines(request("defaults", ident=1)), tune=tune, label="defaults beside a dangling junction")

    def test_settings_saved_over_a_dangling_junction(self):
        # Inherited, not car-control's: car-policy's settings save (REVIEW-int5 S2; fixed on car-v0627-fix4, not in
        # this branch). Here so the integration sees the bridge answer move with it.
        stream = lines(request("update", {"notifications": False}, ident=1), request("defaults", ident=2))
        self.same("golden", stream, tune=lambda workspace: dangling_junction(workspace, "config/settings.json"),
                  label="update and defaults over a settings junction")


class FloatTextDiff(BridgeBase):
    """Inherited (REVIEW-int5 S1, fixed on car-v0627-fix5, not in this branch): a heartbeat time that is one of the 46
    powers of two the JSON writer rounds the wrong way reaches `status` byte for byte. The S5.1a diffs never feed one."""

    def test_a_heartbeat_time_that_is_a_power_of_two(self):
        def tune(workspace: Path):
            connection = sqlite3.connect(workspace / "home" / "config" / "state.sqlite")
            try:
                connection.execute("UPDATE watcher_status SET last_tick_at=?, started_at=?", (2.0 ** 89, 2.0 ** -24))
                connection.commit()
            finally:
                connection.close()

        self.same("golden", lines(request("status", ident=1)), tune=tune, world={"watcher_running": True},
                  label="status with a heartbeat of powers of two")


if __name__ == "__main__":
    import unittest

    unittest.main()

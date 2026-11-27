"""THE table of the advanced proxy (owner Q3 (c)): every module of `codex_auto_resume_advanced` at the v0.6.26 tag, the
seat that ports it (P7-DESIGN 2.2), and what of it runs on Rust when a test imports it under CODEX_AR_CORE=rust.

A row says one of:

* `forwards={name: "runtime.Class"}` - FORWARDED: as the module loads, each name is replaced by the forwarder named
  (a class or function of this package's modules, which reaches car-adv through advserve). A test that builds it builds
  car-adv's.
* THROUGH - reached only through a forwarded object (`Runtime.arming` is car-adv's `Arming`): what a test gets from the
  forwarded object is Rust's; the module's own top-level functions are the reference's until they get a row of names.
* HANDED - its values are handed to car-adv as data (definitions, policies, catalogs); its own rules wait.
* DATA - words and constants only: nothing to decide.
* WAITS (no keyword) - the reference's own module until its seat forwards it.

How a later seat adds its module (rust/GROUNDWORK.md "Seat S7.2a3", the how-to):
1. Serve it: a call in advserve (`advanced/rust/crates/car-adv/examples/advserve/main.rs` `dispatch`) - a new session
   kind for a class (as `open` makes a runtime or a state), or an `op` of an existing probe for pure functions.
2. Forward it: a class or function in a module of this package (yours: `advproxy/<seat>.py`) with the reference's
   signature that calls `pipe.PIPE.request(...)` and answers what car-adv asks back.
3. Name it here: `forwards={"Name": "<seat>.Name"}` on the module's row (one row per module; nothing else to edit).
4. Prove it: `python -X utf8 tests/rustdiff/advproxy/ledger.py --run <files>` moves each file the module unlocks from
   "waits" to "green on Rust" (it runs the file on both lanes and counts its calls to advserve), and a mutation in
   your Rust must fail one of them.
"""
from __future__ import annotations

from typing import NamedTuple

THROUGH, HANDED, DATA = "through", "handed", "data"


class Row(NamedTuple):
    seat: str
    kind: str = "waits"
    forwards: dict = {}
    note: str = ""

    @property
    def status(self) -> str:
        return "forwarded" if self.forwards else self.kind


def _row(seat, kind="waits", forwards=None, note=""):
    return Row(seat, "forwarded" if forwards else kind, dict(forwards or {}), note)


MODULES = {
    '': _row('S7.2a', DATA,
        note='the package itself: nothing but its name'),
    'arming': _row('S7.1b', THROUGH, forwards={'standing': 'pure.standing', 'warnings_for': 'pure.warnings_for'},
        note="`Runtime.arming` is car-adv's `Arming` (ArmingProxy); `standing` and `warnings_for` are car-adv's (proxy2, advserve `op`); the other pure functions wait for their forwarder"),
    'autocheck': _row('S7.2c'),
    'codex': _row('S7.2c'),
    'codex.account': _row('S7.2b'),
    'codex.authfile': _row('S7.2b'),
    'codex.conversation': _row('S7.2c'),
    'codex.credits': _row('S7.2c'),
    'codex.goals': _row('S7.2c'),
    'codex.headless': _row('S7.2c'),
    'codex.inuse': _row('S7.2c'),
    'codex.ipc': _row('S7.2c'),
    'codex.lineage': _row('S7.2c'),
    'codex.protocol': _row('S7.2c'),
    'codex.restart': _row('S7.2b'),
    'codex.sessions': _row('S7.2c'),
    'codex.swap': _row('S7.2b'),
    'codex.threads': _row('S7.2c'),
    'codex.tokens': _row('S7.2c'),
    'codex.turns': _row('S7.2c'),
    'codex.wmi_escape': _row('S7.2c'),
    'compatdata': _row('S7.2c'),
    'control': _row('S7.3a', DATA,
        note='the package itself: nothing but its docstring'),
    'control.account': _row('S7.3a'),
    'control.analytics': _row('S7.3a', forwards={'view': 's73a.analytics_view', 'save_csv': 's73a.analytics_save_csv'},
        note="a card function a test calls by name is asked as its bridge command (s73a.py); one handed a seam of the test's own is the reference's"),
    'control.autoswitch': _row('S7.3a', forwards={'view': 's73a.accounts_view', 'save': 's73a.accounts_save', 'delete': 's73a.accounts_delete'},
        note="a card function a test calls by name is asked as its bridge command (s73a.py); one handed a seam of the test's own is the reference's"),
    'control.chat': _row('S7.3a'),
    'control.codexstart': _row('S7.3a'),
    'control.conversations': _row('S7.3a', forwards={'view': 's73a.conversations_view'},
        note="a card function a test calls by name is asked as its bridge command (s73a.py); one handed a seam of the test's own is the reference's"),
    'control.courier': _row('S7.3b'),
    'control.earlycheck': _row('S7.3a'),
    'control.fleet': _row('S7.3a'),
    'control.follow': _row('S7.3a'),
    'control.hookplugin': _row('S7.3c'),
    'control.keepgoing': _row('S7.3a', forwards={'view': 's73a.keepgoing_view'},
        note="a card function a test calls by name is asked as its bridge command (s73a.py); one handed a seam of the test's own is the reference's"),
    'control.opencodex': _row('S7.3a'),
    'control.powertasks': _row('S7.3a', forwards={'view': 's73a.powertasks_view', 'arm': 's73a.powertasks_arm'},
        note="a card function a test calls by name is asked as its bridge command (s73a.py); one handed a seam of the test's own is the reference's"),
    'control.prompts': _row('S7.3a', forwards={'view': 's73a.prompts_view'},
        note="a card function a test calls by name is asked as its bridge command (s73a.py); one handed a seam of the test's own is the reference's"),
    'control.pythons': _row('retired'),
    'control.remote': _row('S7.3b'),
    'control.resets': _row('S7.3a', forwards={'view': 's73a.resets_view'},
        note="a card function a test calls by name is asked as its bridge command (s73a.py); one handed a seam of the test's own is the reference's"),
    'control.sendnow': _row('S7.3a'),
    'control.steer': _row('S7.3a'),
    'courier': _row('S7.3b'),
    'courier.__main__': _row('S7.3b'),
    'courier.address': _row('S7.3b'),
    'courier.api': _row('S7.3b'),
    'courier.channels': _row('S7.3b'),
    'courier.feed': _row('S7.3b'),
    'courier.http': _row('S7.3b'),
    'courier.keep': _row('S7.3b'),
    'courier.launch': _row('S7.3b'),
    'courier.outbox': _row('S7.3b'),
    'courier.page': _row('S7.3b'),
    'courier.pythonorg': _row('S7.3b'),
    'courier.resident': _row('S7.3b'),
    'courier.telegram': _row('S7.3b'),
    'credentials': _row('S7.2a'),
    'engine': _row('S7.1'),
    'engine.account': _row('S7.2b'),
    'engine.admitted': _row('S7.2e1'),
    'engine.analytics': _row('S7.2e2'),
    'engine.anchor': _row('S7.2e2'),
    'engine.autoswitch': _row('S7.2b'),
    'engine.capacity': _row('S7.2d'),
    'engine.chat': _row('S7.2e1'),
    'engine.compact': _row('S7.2e1'),
    'engine.continued': _row('S7.2d'),
    'engine.credits': _row('S7.2d'),
    'engine.earlyreset': _row('S7.2d'),
    'engine.emptyreply': _row('S7.2e1'),
    'engine.everyconversation': _row('S7.2e1'),
    'engine.fallback': _row('S7.2e1'),
    'engine.feed': _row('S7.3b'),
    'engine.fleet': _row('S7.2e2'),
    'engine.foropen': _row('S7.2e1'),
    'engine.goal': _row('S7.2e1'),
    'engine.headless': _row('S7.2e1'),
    'engine.hookclaims': _row('S7.3c'),
    'engine.keepgoing': _row('S7.2e1'),
    'engine.markerfree': _row('S7.2e1'),
    'engine.oncemore': _row('S7.2e1'),
    'engine.opentarget': _row('S7.2e1'),
    'engine.parallel': _row('S7.2e1'),
    'engine.powertasks': _row('S7.2e2'),
    'engine.promptqueue': _row('S7.2e1'),
    'engine.push': _row('S7.3b'),
    'engine.remote': _row('S7.3b'),
    'engine.resetmessage': _row('S7.2d'),
    'engine.resetwatch': _row('S7.2d'),
    'engine.retries': _row('S7.2e1'),
    'engine.sessions': _row('S7.2e1'),
    'engine.silent': _row('S7.2e1'),
    'engine.steer': _row('S7.2e1'),
    'engine.subagent': _row('S7.2e1'),
    'engine.supervise': _row('S7.2e2'),
    'engine.updatecheck': _row('S7.2e2'),
    'engine.usage': _row('S7.2d'),
    'engine.usagestop': _row('S7.2d'),
    'engine.wake': _row('S7.2e2'),
    'engine.wrapwords': _row('S7.2d'),
    'evidence': _row('S7.4'),
    'hook': _row('S7.3c'),
    'hook.format': _row('S7.3c'),
    'hook.handler': _row('S7.3c'),
    'images': _row('S7.1'),
    'ledger': _row('S7.1a', THROUGH,
        note="`Runtime.ledger` is the reference's ClaimLedger over the forwarded state; P11 (`claim`) runs on core's own connection and is not forwarded"),
    'measure': _row('S7.4'),
    'measured': _row('S7.1b', DATA,
        note='the measurement table, handed as data'),
    'plug': _row('S7.2a', THROUGH,
        note='`AdvancedPlug` makes `runtime.Runtime` (forwarded) and hands every hook to it; `create`, `PLUG_API`, the notice kinds are its own'),
    'policy': _row('S7.1b', HANDED,
        note="`Policy` values handed to car-adv's Arming; `read` (the registry's keys) is asked as the reference's own"),
    'profiles': _row('S7.1'),
    'pythoncheck': _row('retired'),
    'registry': _row('S7.1b', HANDED, forwards={'offered': 'pure.offered'},
        note="definitions and `Registry` are handed to car-adv as data (re-checked by `Registry::new` at open); a shipped `make` is car-adv's table (`capabilities::make`); `offered` is car-adv's (proxy2, advserve `op`); `problems` stays the reference's - it judges definitions car-adv's closed types cannot hold (test_advanced_registry's malformed kinds, options and makes), so a dump loses what it judges; `shown` waits"),
    'report': _row('S7.3c'),
    'report.document': _row('S7.3c'),
    'report.flow': _row('S7.3c'),
    'report.github': _row('S7.3c'),
    'report.records': _row('S7.3c'),
    'runtime': _row('S7.2a', forwards={'Runtime': 'runtime.Runtime'},
        note="car-adv runtime/ over advserve; `state`, `arming` and the codes' hooks through it"),
    'standards': _row('S7.1b', DATA,
        note="the standards' words only"),
    'state': _row('S7.1a', forwards={'AdvancedState': 'runtime.AdvancedState'},
        note="car-adv state/ (`state::calls`); the exception classes stay the reference's, re-raised by name"),
    'state.account': _row('S7.1'),
    'state.analytics': _row('S7.1'),
    'state.arming': _row('S7.1'),
    'state.chat': _row('S7.1'),
    'state.choices': _row('S7.1'),
    'state.continuations': _row('S7.1'),
    'state.journal': _row('S7.1'),
    'state.meter': _row('S7.1'),
    'state.opens': _row('S7.1'),
    'state.prompts': _row('S7.1'),
    'state.records': _row('S7.1'),
    'state.resets': _row('S7.1'),
    'state.restarts': _row('S7.1'),
    'state.runs': _row('S7.1'),
    'state.schema': _row('S7.1'),
    'state.session': _row('S7.1'),
    'state.spend': _row('S7.1'),
    'state.steers': _row('S7.1'),
    'statement': _row('S7.1b', HANDED,
        note="the catalogs' folder handed to car-adv; the module's rendering waits for its forwarder"),
    'surfaces': _row('S7.3a', forwards={
        'answer': 's73a.answer',
        'bridge': 's73a.bridge',
        'mcp': 's73a.mcp',
        'rows': 's73a.rows',
        'badge': 's73a.badge',
        'status': 's73a.status',
        'meter_view': 's73a.meter_view',
        'notice_view': 's73a.notice_view',
        'update_view': 's73a.update_view',
        'account_view': 's73a.account_view',
        'autoswitch_view': 's73a.autoswitch_view',
        'diagnostics': 's73a.diagnostics',
        'feed_view': 's73a.feed_view',
        'fleet_view': 's73a.fleet_view',
        'runs': 's73a.runs',
    }, note="P10 on car-adv (`car_adv::surfaces`, advserve's `surface` call; s73a.py); every bridge command answered (S7.3a2)"),
    'vocabulary': _row('S7.1b', DATA,
        note='closed words only'),
    'watchlog': _row('S7.1'),
    'win': _row('S7.2c'),
    'win.appclose': _row('S7.2b'),
    'win.dpapi': _row('S7.2a'),
    'win.stopflag': _row('S7.2c'),
    'win.waketimer': _row('S7.2c'),}

"""S7.3b's ledger of the advanced tests (P7-DESIGN 3.1, the owner's Q3 (c)): every `advanced/tests` file whose subject is
the courier or the remote reach, the family that holds its rules on Rust now, and what it waits for to run unedited on
Rust through the advanced proxy.

    python -X utf8 tests/rustdiff/advledger_s73b.py [--markdown]

The proxy (an advancedcase serve loop over car-adv, S7.2a's note) is not built yet, so no file is "green through the
proxy": each waits for it, and for the seats its other imports name (advledger_s72a.py has the import table). Until then
the rules each file tests are held by `diffs_advcourier_*` over the same fakes the file uses (a scripted opener, a dict of
secrets, a scripted SMTP server or none, a scripted layer), as the second column says. The table only shrinks.
"""
from __future__ import annotations

import argparse
import sys

PROXY = "the advanced proxy (advancedcase serve loop, S7.2a)"
# file: (what holds it now, what it waits for)
LEDGER = {
    "test_advanced_courier_channels.py": ("diffs_advcourier_state send/drain/pair, _pure address", PROXY),
    "test_advanced_courier_http.py": ("diffs_advcourier_state send (opener seam: status classes, cut reads, expiry)", PROXY),
    "test_advanced_courier_mail_time.py": ("car-adv channels::smtp unit seam; mime.flatten in _pure", PROXY + "; an SMTP wire diff"),
    "test_advanced_courier_mail_tls_time.py": ("car-platform tls unit test (refused handshake)", PROXY + "; an SMTP wire diff"),
    "test_advanced_courier_process.py": ("not yet: courier main_with's round over a World", PROXY + "; S7.3d's World"),
    "test_advanced_courier_start.py": ("car-platform job unit test (suspended child adopted)", PROXY + "; S7.3d's launch wiring"),
    "test_advanced_courier_stream_headers.py": ("retired with http.stream (D8, pythonorg)", "retired D8"),
    "test_advanced_courier_card.py": ("not yet: control::courier over a runtime", PROXY + "; S7.3a's bridge commands"),
    "test_advanced_feed.py": ("diffs_advcourier_pure feed.parse", PROXY + "; S7.3a"),
    "test_advanced_keep_on_default.py": ("diffs_advcourier_state drain (switches, tripwire)", PROXY),
    "test_advanced_local_api.py": ("diffs_advcourier_state loopback API (raw requests), _pure routes/Host/Gate", PROXY + "; S7.3a"),
    "test_advanced_local_api_lan.py": ("diffs_advcourier_pure host_allowed(lan), client_of; serve3 Host on lan", PROXY + "; S7.3a"),
    "test_advanced_network_off.py": ("not yet", PROXY),
    "test_advanced_push_events.py": ("diffs_advcourier_pure push.event/picked/constants", PROXY),
    "test_advanced_remote_reach.py": ("diffs_advcourier_pure remote.pending/resolve/acts", PROXY + "; S7.2e2, S7.3a"),
    "test_advanced_remote_setup_floor.py": ("not yet: engine::remote::starts over setup_time", PROXY),
    "test_advanced_remote_structure.py": ("diffs_advcourier_pure (ROUTES and COMMANDS by their answers)", PROXY + "; S7.3a"),
    "test_advanced_resident.py": ("not yet: resident::Roles over a scripted server and poller", PROXY + "; S7.3a"),
    "test_advanced_resident_state_busy.py": ("not yet", PROXY),
    "test_advanced_resident_unreadable.py": ("not yet", PROXY),
    "test_advanced_telegram.py": ("diffs_advcourier_pure telegram.parse/readable/first_id; Poller.once not yet", PROXY + "; S7.3a"),
    "test_advanced_two_residents.py": ("not yet", PROXY + "; S7.3a"),
    "test_advanced_page_courier.py": ("the C# page (pagecase)", "S6.2a"),
    "test_advanced_page_feed_refresh.py": ("the C# page (pagecase)", "S6.2a"),
    "test_advanced_page_remote.py": ("the C# page (pagecase)", "S6.2a"),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.markdown:
        print("| file | held now by | waits for |\n|---|---|---|")
        for name, (held, waits) in sorted(LEDGER.items()):
            print("| `%s` | %s | %s |" % (name, held, waits))
    else:
        for name, (held, waits) in sorted(LEDGER.items()):
            print("%-45s %s  [waits: %s]" % (name, held, waits))
    return 0


if __name__ == "__main__":
    sys.exit(main())

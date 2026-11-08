"""The remote cards say only what is true, and hand the token out only while the server runs (v0.6.22 final: the
reachability audit's R1, M1-M7 and M14; control/remote.py, courier/resident.py, courier/keep.py, engine/fleet.py).

R1 above all: a port found taken by another program was journalled once, and the card read only the last hour of the
journal - so an hour on it said "running" and Copy address handed the address with its token to whatever page that
program serves. The resident now stamps where its server stands; the card says running, and offers the address or the
token, on the stamp that it bound the port alone. Each test says which fix it fails without.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;advanced/tests" python -m unittest test_advanced_remote_reach
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
import test_advanced_telegram as tt  # noqa: E402
from test_advanced_courier_channels import Secrets as PushSecrets  # noqa: E402
from test_advanced_local_api import BEARER_INK, Secrets  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.control import courier as courier_card, remote  # noqa: E402
from codex_auto_resume_advanced.courier import keep, resident  # noqa: E402
from codex_auto_resume_advanced.engine import fleet, remote as engine_remote  # noqa: E402
from codex_auto_resume_advanced.registry import LOCAL_API, LOCAL_API_ACTIONS, LOCAL_API_LAN  # noqa: E402

HOUR = engine_remote.HOUR


def _taken(runtime, port, lan):
    raise OSError("in use")


class _Server:
    def close(self):
        pass


class ApiCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="engine_present")
        self.catalogs = statement.CATALOGS
        self.rt = self.runtime(LOCAL_API, LOCAL_API_ACTIONS, LOCAL_API_LAN)
        self.rt.arming.catalogs = statement.CATALOGS
        self.secrets = Secrets(BEARER_INK)
        self.assertTrue(self.arm(self.rt, "local_api")["done"])

    def view(self, alive=True, watcher=True, **asked):
        return remote.api_view(self.rt, secrets=self.secrets, running=lambda runtime: alive,
                               watcher=lambda runtime: watcher, **asked)

    def copied(self, view):
        return {key for key in ("copy_url", "copy_token") if key in view}


class PortTakenTests(ApiCase):
    def test_a_port_taken_an_hour_ago_and_still_taken_is_never_running_nor_copied(self):
        """R1: fails with the card reading only the last hour of the journal - after an hour it said running and Copy
        address answered the address with the token."""
        roles = resident.Roles(self.rt, server=_taken)
        self.assertTrue(roles.follow())
        self.assertEqual(self.view()["state"], "port_taken")
        for hours in (1, 2, 30):
            self.now += HOUR
            self.assertTrue(roles.follow(), "it keeps trying")
            found = self.view(copy=True, copy_token=True)
            self.assertEqual(found["state"], "port_taken", "%d hours on" % hours)
            self.assertEqual(self.copied(found), set(), "%d hours on" % hours)
        said = [line["code"] for line in self.rt.state.journal(capability="local_api")]
        self.assertEqual(said.count("api.port_taken"), 1, "still journalled once")
        self.assertNotIn("copy_url", remote.api_token_new(self.rt, secrets=self.secrets, running=lambda runtime: True,
                                                          watcher=lambda runtime: True))

    def test_once_the_port_is_free_and_bound_it_runs_and_copies(self):
        roles = resident.Roles(self.rt, server=_taken)
        roles.follow()
        self.now += 2 * HOUR
        roles._server_factory = lambda runtime, port, lan: _Server()
        roles.follow()
        found = self.view(copy=True, copy_token=True)
        self.assertEqual(found["state"], "running")
        self.assertEqual(found["copy_url"], "http://127.0.0.1:47615/#" + BEARER_INK)
        roles.close()
        self.assertEqual(self.view()["state"], "starting", "closed, it is bound no more")


class RunningTests(ApiCase):
    def test_a_resident_that_has_not_bound_yet_is_starting_and_copies_nothing(self):
        """M1 and M2: fail with "running" read from the resident's mutex alone, and Copy offered while starting."""
        found = self.view(copy=True, copy_token=True)
        self.assertEqual(found["state"], "starting")
        self.assertEqual(self.copied(found), set())

    def test_a_bound_stamp_from_before_the_newest_resident_is_not_this_one_s(self):
        """M2: a resident that died bound left its stamp; the one started after it has not bound yet."""
        self.rt.state.stamp("local_api", resident.BOUND, int(self.now))
        self.now += 60
        self.assertTrue(self.rt.state.counted("local_api", engine_remote.START_WORD))
        self.assertEqual(self.view()["state"], "starting")
        self.now += 5
        self.rt.state.stamp("local_api", resident.BOUND, int(self.now))
        self.assertEqual(self.view()["state"], "running")

    def test_a_new_resident_forgets_what_the_last_one_said(self):
        self.rt.state.stamp("local_api", resident.BOUND, int(self.now))
        resident.Roles(self.rt, server=lambda runtime, port, lan: _Server())
        self.assertIsNone(self.rt.state.stamped("local_api", resident.BOUND))


class WatcherTests(ApiCase):
    def test_with_no_watcher_it_says_it_starts_with_the_watcher(self):
        """M3: fails with "starting" said for ever while the watcher is not running."""
        self.assertEqual(self.view(alive=False, watcher=False)["state"], "no_watcher")
        self.assertEqual(self.view(alive=False, watcher=True)["state"], "starting")


class TokenTests(ApiCase):
    def bound(self):
        self.rt.state.stamp("local_api", resident.BOUND, int(self.now))

    def test_copy_token_answers_the_token_alone_and_only_while_running(self):
        """M4: fails with no Copy token - a script cut the token out of the address after '#'."""
        self.assertNotIn("copy_token", self.view(copy_token=True))
        self.bound()
        found = self.view(copy_token=True)
        self.assertEqual(found["copy_token"], BEARER_INK)
        self.assertNotIn("copy_url", found, "each is asked for alone")
        self.assertNotIn(BEARER_INK, json.dumps(self.view()), "never in the card's own read")

    def test_the_bridge_takes_the_new_arguments(self):
        from codex_auto_resume_advanced import surfaces
        from codex_auto_resume_advanced.vocabulary import BridgeCommand
        self.assertEqual(surfaces.ARGUMENTS[BridgeCommand.ADVANCED_API], frozenset({"copy", "host", "copy_token"}))


class LanTests(ApiCase):
    def bound(self):
        self.rt.state.stamp("local_api", resident.BOUND, int(self.now))

    def setUp(self):
        super().setUp()
        self.assertTrue(self.arm(self.rt, "local_api_lan")["done"])
        self.bound()

    def lan(self, **asked):
        return self.view(addresses=lambda: ["192.168.1.20", "10.0.0.5"], **asked)

    def test_open_to_the_network_it_lists_this_pc_s_addresses(self):
        """M5: fails with only 127.0.0.1 shown and copied while the local network may reach it."""
        found = self.lan()
        self.assertEqual(found["url"], "http://127.0.0.1:47615/")
        self.assertEqual(found["lan_urls"], ["http://192.168.1.20:47615/", "http://10.0.0.5:47615/"])
        self.assertEqual(self.lan(copy=True, host="10.0.0.5")["copy_url"], "http://10.0.0.5:47615/#" + BEARER_INK)
        self.assertEqual(self.lan(copy=True)["copy_url"], "http://127.0.0.1:47615/#" + BEARER_INK)

    def test_a_host_that_is_not_one_of_this_pc_s_addresses_is_never_carried(self):
        for host in ("evil.example", "192.168.1.21", "", ["192.168.1.20"]):
            self.assertNotIn("copy_url", self.lan(copy=True, host=host), host)

    def test_off_the_network_no_address_is_looked_up(self):
        self.rt.arming.disarm("local_api_lan", actor="dashboard")
        found = remote.api_view(self.rt, secrets=self.secrets, running=lambda runtime: True,
                                addresses=lambda: self.fail("not asked"))
        self.assertNotIn("lan_urls", found)
        self.assertNotIn("copy_url", self.view(copy=True, host="192.168.1.20"))

    def test_this_pc_s_addresses_leave_out_loopback_and_link_local(self):
        from unittest.mock import patch
        infos = [(2, 1, 6, "", (address, 0)) for address in
                 ("127.0.0.1", "169.254.3.4", "192.168.1.20", "192.168.1.20", "10.0.0.5", "0.0.0.0")]
        with patch("socket.getaddrinfo", lambda *unused: infos):
            self.assertEqual(remote.lan_addresses(), ["192.168.1.20", "10.0.0.5"])
        with patch("socket.getaddrinfo", side_effect=OSError("no name")):
            self.assertEqual(remote.lan_addresses(), [])


class TelegramWords(tt.TelegramCase):
    def state(self, **kept):
        self.secrets = PushSecrets(**kept)
        return remote.pair_state(self.rt, secrets=self.secrets, running=lambda runtime: True,
                                 watcher=lambda runtime: True)

    def test_states(self):
        """M7: fails with "running" ("The bot is being read.") said while the poll idles with no token or no chat."""
        self.on("push_notices", "telegram_remote")
        self.assertEqual(self.state()["state"], "no_token")
        self.assertEqual(self.state(telegram_token=tt.BOT_INK)["state"], "no_chat")
        keep.begin_pairing(self.rt.state, "123456", self.now)
        self.assertEqual(self.state(telegram_token=tt.BOT_INK)["state"], "pairing")
        self.now += keep.PAIR_SECONDS + 1
        self.assertEqual(self.state(telegram_token=tt.BOT_INK, telegram_chat=str(tt.CHAT))["state"], "running")

    def test_with_no_watcher_it_says_reading_starts_with_the_watcher(self):
        """M3: fails with "starting" said for ever while the watcher is not running."""
        self.on("push_notices", "telegram_remote")
        said = remote.pair_state(self.rt, secrets=self.secrets, running=lambda runtime: False,
                                 watcher=lambda runtime: False)
        self.assertEqual(said["state"], "no_watcher")

    def test_the_paired_chat_is_named_as_telegram_gave_it(self):
        """M6: fails with only "A chat is paired" said."""
        self.on("push_notices", "telegram_remote")
        said = self.state(telegram_token=tt.BOT_INK, telegram_chat=str(tt.CHAT), telegram_chat_name="Night shift")
        self.assertEqual(said["chat"], "Night shift")
        self.assertNotIn(str(tt.CHAT), json.dumps(said))
        self.assertNotIn("chat", self.state(telegram_token=tt.BOT_INK), "none paired, none named")

    def test_a_pairing_keeps_the_chat_s_title_or_username_and_never_a_message(self):
        self.on("push_notices", "telegram_remote")
        right = [{"update_id": 5, "message": {"chat": {"id": tt.CHAT, "type": "private", "username": "example_user",
                                                      "first_name": "Example"}, "text": "123456"}}]
        pairing = tt.PairingTests("test_four_do_not")
        pairing.rt, pairing.secrets, pairing.now = self.rt, self.secrets, self.now
        pairing.pairing_run(right)
        self.assertEqual(self.secrets.kept["telegram_chat_name"], "@example_user")
        self.assertNotIn("123456", self.secrets.kept.values())

    def test_the_poll_names_a_chat_paired_before_names_were_kept(self):
        self.on("push_notices", "telegram_remote")
        message = self.message("/status")
        message["message"]["chat"]["title"] = "Ops\nroom\u202e"
        bot = tt.Bot([message])
        self.poller(bot).once()
        self.assertEqual(self.secrets.kept["telegram_chat_name"], "Opsroom")
        writes = len(self.secrets.writes)
        again = self.message("/status")
        again["message"]["chat"]["title"] = "Ops\nroom"
        self.poller(tt.Bot([again])).once()
        self.assertEqual(len(self.secrets.writes), writes, "the same name is not written again")

    def test_a_stranger_s_chat_is_never_named(self):
        self.on("push_notices", "telegram_remote")
        stranger = self.message("/status", chat=tt.OTHER)
        stranger["message"]["chat"]["title"] = "Someone else"
        self.poller(tt.Bot([stranger])).once()
        self.assertNotIn("telegram_chat_name", self.secrets.kept)

    def test_a_new_bot_or_forgetting_the_channel_takes_the_name_away(self):
        self.secrets.kept["telegram_chat_name"] = "Night shift"
        self.assertIn("telegram_chat_name", keep.CHANNEL_SECRETS["telegram"])
        self.secrets.delete = lambda capability, name: self.secrets.kept.pop(name, None) is not None
        courier_card.forget(self.rt, "telegram", secrets=self.secrets)
        self.assertNotIn("telegram_chat_name", self.secrets.kept)


class LabelTests(unittest.TestCase):
    def test_title_then_username_and_nothing_else(self):
        self.assertEqual(keep.chat_label({"id": 1, "title": "Team", "username": "team_bot"}), "Team")
        self.assertEqual(keep.chat_label({"id": 1, "username": "someone"}), "@someone")
        self.assertIsNone(keep.chat_label({"id": 1, "first_name": "Example", "last_name": "User"}))
        self.assertIsNone(keep.chat_label({"id": 1, "title": " \n "}))
        self.assertEqual(len(keep.chat_label({"title": "x" * 500})), keep.MAX_CHAT_NAME)
        self.assertIsNone(keep.chat_label("not a chat"))


class FleetQuietTests(unittest.TestCase):
    def peer(self, age):
        return fleet.shown({"alias": "desk", "watcher": "running", "recovery": "on", "pending": 1,
                            "written_at": ac.NOW - age, "next_check_at": ac.NOW + 60}, ac.NOW)

    def test_a_pc_not_heard_from_says_when_it_was_last_heard(self):
        """M14: fails with every file under a week old shown as what it said - a PC switched off read "running"."""
        self.assertEqual(self.peer(fleet.EVERY)["seen"], "fresh")
        quiet = self.peer(fleet.QUIET + 1)
        self.assertEqual(quiet["seen"], "quiet")
        self.assertEqual(quiet["written_at"], ac.NOW - fleet.QUIET - 1, "when it was last heard")
        self.assertIsNone(quiet["next_check_at"], "a next check it may never make is not shown")
        self.assertEqual(self.peer(fleet.STALE + 1)["seen"], "old")

    def test_a_typed_share_is_checked_as_a_chosen_folder_is(self):
        """M14: the window's box sends what was typed to the same save; the bridge's check is the one the picker's
        choice passes (folder_problem), so a share path is taken and a device path is not."""
        self.assertEqual(fleet.folder_problem("\\\\?\\C:\\x", None), fleet.INVALID)
        self.assertEqual(fleet.folder_problem('"C:\\Sync"', None), fleet.INVALID, "the window strips the quotes")


if __name__ == "__main__":
    unittest.main()

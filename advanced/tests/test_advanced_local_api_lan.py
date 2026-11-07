"""Open the status server to the local network (local_api_lan, v0.6.22, plans/v0619-design/D-remote.md): beyond 127.0.0.1 only
while a person turned it on beside local_api, and nothing else about the server changes.

No test here binds beyond 127.0.0.1: listening on every network would bring Windows' firewall question up on the desktop.
What is bound is read where the address is made, and every request goes to a real server on 127.0.0.1 that was told it
is open to the network.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_local_api import TOKEN, ServerCase  # noqa: E402
from codex_auto_resume_advanced import registry, statement  # noqa: E402
from codex_auto_resume_advanced.control import remote as card  # noqa: E402
from codex_auto_resume_advanced.courier import api, resident  # noqa: E402
from codex_auto_resume_advanced.registry import LOCAL_API, LOCAL_API_ACTIONS, LOCAL_API_LAN  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingState, Refusal  # noqa: E402


class _Server:
    def close(self):
        pass


class WhatIsAskedTests(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="engine_present")
        self.catalogs = statement.CATALOGS
        self.rt = self.runtime(LOCAL_API, LOCAL_API_LAN)
        self.rt.arming.catalogs = statement.CATALOGS
        self.asked = []

    def server(self, runtime, port, lan):
        self.asked.append((port, lan))
        return _Server()

    def also(self):
        return [{"capability": "local_api", "revision": 1, "warnings": [], "engine_version": ac.ENGINE}]

    def test_off_loopback(self):
        """Fails where the resident asks for the network on its own."""
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        resident.Roles(self.rt, server=self.server).follow()
        self.assertEqual(self.asked[-1][1], False)

    def test_watched_it_is_still_loopback(self):
        """Fails where watched reads as on: a person who only watches it would have opened the port."""
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        self.assertTrue(self.arm(self.rt, "local_api_lan", state="shadow")["done"])
        resident.Roles(self.rt, server=self.server).follow()
        self.assertEqual(self.asked[-1][1], False)

    def test_on_it_is_asked_for_and_turned_off_it_is_loopback_again_on_a_new_server(self):
        self.assertTrue(self.arm(self.rt, "local_api_lan", also=self.also())["done"])
        roles = resident.Roles(self.rt, server=self.server)
        roles.follow()
        self.assertEqual(self.asked[-1][1], True)
        self.rt.arming.disarm("local_api_lan", actor="dashboard")
        roles.follow()
        self.assertEqual(self.asked[-1][1], False)
        self.assertEqual(len(self.asked), 2, "the server was started again, not left open")

    def test_it_needs_the_server(self):
        refused = self.arm(self.rt, "local_api_lan")
        self.assertEqual((refused["done"], refused["refusal"]), (False, Refusal.REQUIREMENT_REFUSED))

    def test_the_server_turned_off_takes_it_along(self):
        self.assertTrue(self.arm(self.rt, "local_api_lan", also=self.also())["done"])
        self.rt.arming.disarm("local_api", actor="dashboard")
        self.assertEqual(self.rt.states(fresh=True).get("local_api_lan", ArmingState.OFF), ArmingState.OFF)
        resident.Roles(self.rt, server=self.server).follow()
        self.assertEqual(self.asked, [])

    def test_the_address_is_every_network_only_when_asked(self):
        """Fails where start binds anywhere but what it was told: read at the bind, no socket made."""
        bound = []

        class Stand:
            server_address = ("x", 1)

            def __init__(self, address, service, gate):
                bound.append(address)

        with patch.object(api, "Server", Stand), patch.object(api, "Running", lambda server: server):
            api.start(self.rt, 47615, False, service=object())
            api.start(self.rt, 47615, True, service=object())
        self.assertEqual(bound, [("127.0.0.1", 47615), ("0.0.0.0", 47615)])

    def test_the_card_says_so(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        view = card.api_view(self.rt, secrets=_NoToken(), running=lambda runtime: True)
        self.assertFalse(view["lan"])
        self.assertTrue(self.arm(self.rt, "local_api_lan")["done"])
        view = card.api_view(self.rt, secrets=_NoToken(), running=lambda runtime: True)
        self.assertTrue(view["lan"])
        self.assertEqual(view["url"], "http://127.0.0.1:47615/", "the address the card shows is this PC's own")


class _NoToken:
    def read(self, capability, name):
        return None


class OpenServerTests(ServerCase):
    """A server told it is open to the network: nothing but the Host's rule changes."""
    LAN = True

    def setUp(self):
        super().setUp()
        patcher = patch.object(card, "status_document", lambda layer, now: {"format": "x"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_address_is_taken_as_a_host_and_a_name_still_is_not(self):
        address = "192.168.0.2:%d" % self.port
        self.assertEqual(self.status("/status.json", host=address), 200)
        for host in ("evil.example:%d" % self.port, "my-pc:%d" % self.port, "192.168.0.2:1", "192.168.0.2"):
            self.assertEqual(self.status("/status.json", host=host), 421, host)

    def test_the_token_the_lock_and_the_routes_are_as_they_are_on_loopback(self):
        address = "192.168.0.2:%d" % self.port
        self.assertEqual(self.status("/status.json", host=address, token="wrong"), 401)
        self.assertEqual(self.status("/send", host=address), 404)
        self.assertEqual(self.status("/status.json", "POST", host=address), 405)
        for _ in range(9):
            self.assertEqual(self.status("/status.json", host=address, token="wrong"), 401)
        self.assertEqual(self.status("/status.json", host=address, token=TOKEN), 503)


class ShippedTests(unittest.TestCase):
    def test_it_names_what_it_departs_from(self):
        self.assertEqual(registry.LOCAL_API_LAN.departs_from, ("B14", "F8", "D1"))
        self.assertEqual(registry.LOCAL_API_LAN.requires, ("local_api",))

    def test_every_language_warns_of_no_encryption_in_its_risks(self):
        english = statement.CATALOGS.catalog("en")["statement.local_api_lan.risks"]
        self.assertIn("not encrypted", english)
        self.assertIn(json.loads('"public"'), english)


if __name__ == "__main__":
    unittest.main()

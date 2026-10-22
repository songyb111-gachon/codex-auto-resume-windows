"""One compatibility document with a sequence far ahead cannot lock every later one out (v0.6.18, security M4).

A document's sequence orders the data: a lower one than the cache's is refused as a rollback, and the bundled
baseline of a release supersedes only a cache of a lower sequence. Before v0.6.18 any sequence up to 2^31-1 was
taken in. One imported file (or a mistaken document on main) at 2^31-1 then refused every later document - the
project's own refreshes and every new release's bundled data - and the INCOMPATIBLE entries it carried kept the
gate at "incompatible" for good, with no surface to undo it. Now a document may run at most MAX_SEQUENCE_LEAD
ahead of the bundled baseline: one further ahead is refused, and one already kept from before is not in force.

Scratch homes and pure functions only: no registry, no network, no Codex.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import time
import unittest

from codex_auto_resume import compat, config
from codex_auto_resume.compat import cache, files
from codex_auto_resume.compat.model import MAX_SEQUENCE_LEAD

NOW = time.time()


def stamp(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def bundled_raw():
    return json.loads(Path(files.BUNDLED).read_text(encoding="utf-8"))


def a_document(sequence, *, incompatible=False):
    """The bundled baseline at `sequence`, in force now; with `incompatible`, its newest engine refused."""
    document = copy.deepcopy(bundled_raw())
    document.update(sequence=sequence, published_at=stamp(NOW - 60), expires_at=stamp(NOW + 86400 * 30))
    if incompatible:
        newest = document["engines"][-1]
        for name, entry in newest["capabilities"].items():
            newest["capabilities"][name] = {"state": "INCOMPATIBLE", "reason": "unspecified",
                                            "evidence": entry.get("evidence") or ["docs/evidence/x.json"]}
    return document


class SequenceLeadTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.paths = config.Paths(str(self.root / "home"))
        self.base = bundled_raw()["sequence"]
        self.newest = bundled_raw()["engines"][-1]["version"]

    def write(self, name, document):
        file = self.root / name
        file.write_text(json.dumps(document), encoding="utf-8")
        return file

    def take(self, document, name="data.json"):
        return cache.import_document(self.paths, self.write(name, document), origin="file", now=NOW)

    def test_a_document_far_ahead_is_refused(self):
        result = self.take(a_document(2 ** 31 - 1, incompatible=True))
        self.assertEqual((result["imported"], result["reason"]), (False, "invalid_field"))
        self.assertFalse(self.paths.compat_cache_file.exists(), "nothing was written")

    def test_the_projects_next_document_is_still_taken_after_one(self):
        self.take(a_document(2 ** 31 - 1, incompatible=True), "hostile.json")
        result = self.take(a_document(self.base + 1), "next.json")
        self.assertEqual((result["imported"], result["sequence"]), (True, self.base + 1))

    def test_the_lead_itself_is_allowed(self):
        result = self.take(a_document(self.base + MAX_SEQUENCE_LEAD))
        self.assertTrue(result["imported"], result)
        result = self.take(a_document(self.base + MAX_SEQUENCE_LEAD + 1), "beyond.json")
        self.assertEqual((result["imported"], result["reason"]), (False, "invalid_field"))

    def test_one_kept_from_before_is_not_in_force_and_blocks_nothing(self):
        """A home that took one in before v0.6.18: its restrictions stop applying, and the next refresh is taken."""
        envelope = {"format": compat.CACHE_FORMAT, "fetched_at": NOW - 3600, "origin": "file",
                    "document": a_document(2 ** 31 - 1, incompatible=True)}
        self.paths.ensure()
        self.paths.compat_cache_file.write_text(json.dumps(envelope), encoding="utf-8")
        sources = cache.data_in_force(self.paths, now=NOW + 86400 * 400)
        self.assertIsNone(dict((name, document) for name, document, _ in sources)["cache"])
        self.assertNotEqual(compat.accepted_word(self.newest, sources), "incompatible")
        result = self.take(a_document(self.base + 1), "next.json")
        self.assertEqual((result["imported"], result["sequence"]), (True, self.base + 1))

    def test_a_cache_within_the_lead_still_restricts_after_it_expires(self):
        """The bound changes nothing for the project's own numbering: restrictions still never expire."""
        self.assertTrue(self.take(a_document(self.base + 1, incompatible=True))["imported"])
        sources = cache.data_in_force(self.paths, now=NOW + 86400 * 400)
        self.assertEqual(compat.accepted_word(self.newest, sources), "incompatible")


if __name__ == "__main__":
    unittest.main()

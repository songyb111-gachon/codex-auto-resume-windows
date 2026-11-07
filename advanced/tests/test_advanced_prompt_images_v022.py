"""Pictures in a scheduled message from v0.6.22 (the owner's 2026-11-08): ten to a message and 20 MB each, where four and
5 MB were design-time bounds no measurement stood behind; the total the product keeps for the messages still to go; and
MIMG's probe sending exactly those bounds, so the measurement proves what the product allows.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p "test_advanced_prompt_images_v022.py"
"""
from __future__ import annotations

import base64
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401  (puts src, advanced/src and tests on the path)
from codex_auto_resume_advanced import images, measure  # noqa: E402

PNG = base64.b64decode(measure._MIMG_PNG_BASE64)


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.paths = SimpleNamespace(advanced_dir=str(self.folder))

    def staged(self, count, data=PNG):
        return [images.stage(self.paths, data, "png") for _ in range(count)]


class BoundsTests(Case):
    def test_ten_to_a_message_and_an_eleventh_refused(self):
        """Fails with MOST_IMAGES back at four."""
        self.assertEqual(images.MOST_IMAGES, 10)
        ten = self.staged(10)
        images.place(self.paths, 1, ten)
        self.assertEqual(images.count(self.paths, 1), 10)
        with self.assertRaises(images.ImageRefused) as refused:
            images.place(self.paths, 2, self.staged(11))
        self.assertEqual(str(refused.exception.args[0]), "images_full")

    def test_twenty_megabytes_taken_and_one_byte_over_refused(self):
        """Fails with MOST_BYTES back at 5 MB."""
        self.assertEqual(images.MOST_BYTES, 20 * 1024 * 1024)
        exactly = self.folder / "exactly.png"
        exactly.write_bytes(PNG + b"\0" * (images.MOST_BYTES - len(PNG)))
        images.read(str(exactly))
        over = self.folder / "over.png"
        over.write_bytes(PNG + b"\0" * (images.MOST_BYTES - len(PNG) + 1))
        with self.assertRaises(images.ImageRefused) as refused:
            images.read(str(over))
        self.assertEqual(str(refused.exception.args[0]), "image_too_large")


class KeptTests(Case):
    def test_only_the_copies_of_messages_still_to_go_are_counted(self):
        """A prompt no longer to go and a save's copy in progress are not; each counted copy's bytes are."""
        images.place(self.paths, 1, self.staged(2, PNG + b"\0" * 1000))
        images.place(self.paths, 2, self.staged(3))
        self.staged(1)                                    # a save's copy, before its prompt has an id
        self.assertEqual(images.kept(self.paths, [1]), (2, 2 * (len(PNG) + 1000)))
        self.assertEqual(images.kept(self.paths, [1, 2]), (5, 2 * (len(PNG) + 1000) + 3 * len(PNG)))
        self.assertEqual(images.kept(self.paths, []), (0, 0))


class ProbePicturesTests(Case):
    def test_the_probe_writes_as_many_as_a_message_holds_the_last_just_under_the_most_bytes(self):
        """Each a valid PNG the product would take: the one red pixel, the last padded by an ancillary chunk whose CRC is
        right, to just under MOST_BYTES."""
        pictures = measure._mimg_pictures(self.folder)
        self.assertEqual(len(pictures), images.MOST_IMAGES)
        self.assertTrue(all(path.parent == self.folder for path in pictures))
        self.assertEqual([path.read_bytes() for path in pictures[:-1]], [PNG] * (images.MOST_IMAGES - 1))
        last = pictures[-1].read_bytes()
        self.assertLess(len(last), images.MOST_BYTES)
        self.assertGreater(len(last), images.MOST_BYTES - 4096)
        images.read(str(pictures[-1]))
        kinds, at = [], 8
        while at < len(last):
            size, kind = struct.unpack(">I4s", last[at:at + 8])
            body = last[at + 8:at + 8 + size]
            (crc,) = struct.unpack(">I", last[at + 8 + size:at + 12 + size])
            self.assertEqual(crc, zlib.crc32(kind + body) & 0xFFFFFFFF, kind)
            kinds.append(kind)
            at += 12 + size
        self.assertEqual(kinds, [b"IHDR", b"IDAT", b"caRp", b"IEND"])


if __name__ == "__main__":
    unittest.main()

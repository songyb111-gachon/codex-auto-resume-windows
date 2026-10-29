"""Pictures in a scheduled message (v0.6.20, #50 item 1): the product's own copies, made when the person saves, named by
an opaque id and never by the person's path, checked by their bytes, at most four of 5 MB each, and removed once the
message is delivered, cancelled or deleted - with a sweep for any a save or a crash left behind. Nothing in the status,
diagnostics, the journal or MCP names a copy, a path or a picture.

Held against the shipped definition and core's own engine, store and simulated Codex home (takingcase.py); the
Dashboard's bridge adds them (surfaces.bridge), as the page does.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p "test_advanced_prompt_images*.py"
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_prompt_queue import QueueCase  # noqa: E402
from codex_auto_resume_advanced import images, surfaces  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement, PromptState, Refusal, Verdict  # noqa: E402

# One white pixel as a PNG (the picture MIMG queued), and the first bytes of the other kinds.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 60
GIF = b"GIF89a" + b"\0" * 60
WEBP = b"RIFF\x30\0\0\0WEBPVP8 " + b"\0" * 48
# A name a person's own file might have: never to be seen in a copy's name or anywhere the product writes.
OWN_NAME = "Holiday-PrivateName-7f3a"


class FakeSession:
    """The app server as thread/queue/add meets it: every call kept, and the item added to codexsim's queue under the id
    it was given - never a real Codex."""

    def __init__(self, h, calls):
        self.h, self.calls = h, calls

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def call(self, method, params):
        self.calls.append((method, json.loads(json.dumps(params))))
        text = params["input"][0]["text"]
        queue_id = self.h.home.enqueue(params["threadId"], text, client_id=params.get("clientUserMessageId"))
        return {"queuedSubmissionId": queue_id}


class ImagesCase(QueueCase):
    def setUp(self):
        super().setUp()
        self.mine = Path(tempfile.mkdtemp(prefix="car-v0620-images-mine-"))
        self.addCleanup(shutil.rmtree, self.mine, True)
        self.calls = []

    def armed(self, h=None, state="armed", long=False):
        plug = super().armed(h, state=state, long=long)
        code = plug.runtime._code_of(plug.runtime.registry.get(self.cap))
        code._session = lambda: FakeSession(self.h, self.calls)
        return plug

    def picture(self, data=PNG, name=OWN_NAME + ".png"):
        path = self.mine / name
        path.write_bytes(data)
        return str(path)

    def folder(self, plug):
        return Path(plug.runtime.paths.advanced_dir)

    def copies(self, plug):
        return sorted(path.name for path in self.folder(plug).iterdir() if path.name.startswith("image-"))

    def add_with(self, plug, pictures, **argument):
        argument.setdefault("trigger", "at_time")
        argument.setdefault("at", self.h.now + 7200)
        return self.add(plug, images=[{"path": path} for path in pictures], **argument)

    def edit(self, plug, prompt, pictures, **argument):
        argument.update(prompt=prompt, words=argument.get("words", "the words, changed"), trigger="at_time",
                        at=self.h.now + 7200, generation=plug.runtime.state.meta()["generation"])
        if pictures is not None:
            argument["images"] = pictures
        return surfaces.bridge(plug.runtime, "advanced-prompt-edit", argument)

    def mimg_failed(self, plug):
        """MIMG read as failed on the Codex in force, the way the shipped table would say it."""
        measured = plug.runtime.arming.measured()
        return patch.object(plug.runtime.arming, "measured",
                            lambda: dict(measured, **{Measurement.MIMG: (Verdict.FAIL, "codex-cli 0.0.0")}))

    def queued(self, plug, pictures, words="Look at these screenshots.", **argument):
        argument.setdefault("trigger", "after_turn")
        argument.setdefault("at", None)
        answer = self.add(plug, words=words, images=[{"path": path} for path in pictures], **argument)
        self.assertTrue(answer["done"], answer)
        return answer["prompt"]

    def listed(self, plug, prompt):
        view = surfaces.bridge(plug.runtime, "advanced-prompts", {})
        return next(row for row in view["prompts"] if row["prompt_id"] == prompt)


class CopyTests(ImagesCase):
    def test_a_saved_picture_is_the_products_own_copy_named_opaquely(self):
        """Fails with the copies reverted: the add is refused for its `images`, and nothing is kept."""
        plug = self.on()
        answer = self.add_with(plug, [self.picture(), self.picture(JPEG, "second.jpeg")])
        self.assertTrue(answer["done"], answer)
        prompt = answer["prompt"]
        names = self.copies(plug)
        self.assertEqual(len(names), 2)
        for place, (name, ext) in enumerate(zip(names, ("png", "jpg")), 1):
            self.assertRegex(name, r"^image-%d-%d-2-[0-9a-f]{32}\.%s$" % (prompt, place, ext))
            self.assertNotIn("Holiday", name)
            self.assertNotIn("second", name)
        self.assertEqual((self.folder(plug) / names[0]).read_bytes(), PNG, "a copy, byte for byte")
        self.assertTrue(Path(self.picture()).is_file(), "the person's own file is left as it was")
        shown = self.listed(plug, prompt)["images"]
        self.assertEqual([Path(image["path"]).name for image in shown], names)
        self.assertEqual([image["id"] for image in shown], [name.split("-")[4].split(".")[0] for name in names])

    def test_each_kind_is_known_by_its_bytes_and_never_by_its_name(self):
        for data, ext in ((PNG, "png"), (JPEG, "jpg"), (GIF, "gif"), (WEBP, "webp")):
            with self.subTest(ext=ext):
                self.assertEqual(images.kind(data), ext)
        self.assertIsNone(images.kind(b"just some words, named .png"))
        plug = self.on()
        disguised = self.picture(b"<svg>not a picture we send</svg>", "looks.png")
        answer = self.add_with(plug, [disguised])
        self.assertEqual((answer["done"], answer["refusal"]), (False, Refusal.IMAGE_REFUSED))
        named_wrong = self.picture(PNG, "a-png-called.txt")
        self.assertTrue(self.add_with(plug, [named_wrong])["done"], "its bytes say PNG: taken")

    def test_too_large_too_many_unreadable_and_relative_are_refused_and_nothing_is_kept(self):
        plug = self.on()
        large = self.picture(PNG + b"\0" * images.MOST_BYTES, "large.png")
        cases = (([large], Refusal.IMAGE_TOO_LARGE),
                 ([self.picture()] * 5, Refusal.IMAGES_FULL),
                 ([str(self.mine / "gone.png")], Refusal.IMAGE_REFUSED),
                 ([str(self.mine)], Refusal.IMAGE_REFUSED),
                 (["relative.png"], Refusal.IMAGE_REFUSED),
                 ([self.picture(), large], Refusal.IMAGE_TOO_LARGE))
        for pictures, refusal in cases:
            with self.subTest(refusal=refusal, count=len(pictures)):
                answer = self.add_with(plug, pictures)
                self.assertEqual((answer["done"], answer["refusal"]), (False, refusal))
                self.assertEqual(self.copies(plug), [], "a refused save leaves no copy")
        self.assertEqual(plug.runtime.state.prompts(pending=None), [], "and no message")
        answer = self.add(plug, images=[{"name": "x"}])
        self.assertEqual(answer["refusal"], Refusal.INVALID_REQUEST)

    def test_where_mimg_failed_pictures_are_refused(self):
        plug = self.on()
        with self.mimg_failed(plug):
            answer = self.add_with(plug, [self.picture()])
            self.assertEqual(answer["refusal"], Refusal.IMAGES_UNAVAILABLE)
            self.assertTrue(surfaces.bridge(plug.runtime, "advanced-prompts", {})["images_unavailable"])
            self.assertTrue(self.add(plug, trigger="at_time", at=self.h.now + 7200)["done"], "words alone still go")
        self.assertEqual(self.copies(plug), [])


class RemovalTests(ImagesCase):
    def test_cancelled_its_copies_are_removed(self):
        plug = self.on()
        prompt = self.add_with(plug, [self.picture(), self.picture(GIF, "b.gif")])["prompt"]
        self.assertEqual(len(self.copies(plug)), 2)
        answer = surfaces.bridge(plug.runtime, "advanced-prompt-cancel",
                                 {"prompt": prompt, "generation": plug.runtime.state.meta()["generation"]})
        self.assertEqual(answer["cancelled"], "cancelled")
        self.assertEqual(self.copies(plug), [])

    def test_ended_any_other_way_or_deleted_the_next_tick_sweeps_them(self):
        """Fails with the sweep reverted: a copy outlives its message."""
        plug = self.on()
        ended = self.add_with(plug, [self.picture()])["prompt"]
        deleted = self.add_with(plug, [self.picture()])["prompt"]
        kept = self.add_with(plug, [self.picture()])["prompt"]
        plug.runtime.state.change_prompt(ended, state=PromptState.CANCELLED, finished_at=self.h.now)
        with plug.runtime.state._transaction() as connection:
            connection.execute("DELETE FROM prompts WHERE prompt_id=?", (deleted,))
        self.h.tick(advance=1)
        self.assertEqual([name.split("-")[1] for name in self.copies(plug)], [str(kept)])

    def test_orphans_a_save_or_a_crash_left_are_swept_and_a_save_in_progress_is_not(self):
        plug = self.on()
        self.add(plug, trigger="at_time", at=self.h.now + 7200)          # the state is there, a prompt waits
        folder = self.folder(plug)
        old = folder / ("image-new-%s.png" % ("a" * 32))
        fresh = folder / ("image-new-%s.png" % ("b" * 32))
        stray = folder / ("image-999-1-1-%s.png" % ("c" * 32))
        other = folder / "not-ours.png"
        for path in (old, fresh, stray, other):
            path.write_bytes(PNG)
        os.utime(old, (time.time() - images.STAGED_FOR - 60,) * 2)
        self.h.tick(advance=1)
        self.assertEqual(sorted(path.name for path in folder.iterdir() if path.suffix == ".png"),
                         sorted([fresh.name, other.name]), "only what is ours and finished goes")

    def test_a_recurring_message_keeps_its_pictures_until_its_series_ends(self):
        plug = self.on()
        prompt = self.add_with(plug, [self.picture()], trigger="recurring", every="day", occurrences=2,
                               at=self.h.now + 60)["prompt"]
        plug.runtime.state.change_prompt(prompt, sent_count=1)
        self.h.tick(advance=1)
        self.assertEqual(len(self.copies(plug)), 1, "still to go: kept")


class EditTests(ImagesCase):
    def test_an_edit_keeps_drops_adds_and_orders_them(self):
        plug = self.on()
        prompt = self.add_with(plug, [self.picture(), self.picture(JPEG, "b.jpg")])["prompt"]
        first, second = [image["id"] for image in self.listed(plug, prompt)["images"]]
        answer = self.edit(plug, prompt, [{"path": self.picture(GIF, "c.gif")}, {"id": first}])
        self.assertTrue(answer["done"], answer)
        shown = self.listed(plug, prompt)["images"]
        self.assertEqual(len(shown), 2)
        self.assertEqual(shown[1]["id"], first, "kept, now second")
        self.assertTrue(shown[0]["path"].endswith(".gif"))
        self.assertNotIn(second, [image["id"] for image in shown])
        self.assertEqual(len(self.copies(plug)), 2, "the dropped one is removed")

    def test_an_edit_without_images_leaves_them_and_an_id_of_another_is_refused(self):
        plug = self.on()
        prompt = self.add_with(plug, [self.picture()])["prompt"]
        other = self.add_with(plug, [self.picture()])["prompt"]
        before = self.listed(plug, prompt)["images"]
        self.assertTrue(self.edit(plug, prompt, None)["done"])
        self.assertEqual(self.listed(plug, prompt)["images"], before)
        foreign = self.listed(plug, other)["images"][0]["id"]
        self.assertEqual(self.edit(plug, prompt, [{"id": foreign}])["refusal"], Refusal.INVALID_REQUEST)
        self.assertEqual(self.edit(plug, prompt, [])["done"], True)
        self.assertEqual(self.listed(plug, prompt)["images"], [], "all removed by the person")


class PrivacyTests(ImagesCase):
    def test_nothing_names_a_path_a_copy_or_a_picture_outside_the_dashboards_list(self):
        plug = self.on()
        prompt = self.add_with(plug, [self.picture()], trigger="after_turn", at=None)["prompt"]
        self.h.tick(advance=1)
        folder = str(self.folder(plug))
        shown = [repr(self.h.logs), repr(plug.runtime.state.journal()), json.dumps(surfaces.status(plug.runtime)),
                 json.dumps(surfaces.diagnostics(plug.runtime), default=str),
                 json.dumps(surfaces.mcp(plug.runtime, {}), default=str)]
        for text in shown:
            for needle in (OWN_NAME, str(self.mine), "image-", folder, folder.replace("\\", "\\\\"), "iVBOR"):
                self.assertNotIn(needle, text)
        finished = [row for row in surfaces.bridge(plug.runtime, "advanced-prompts", {})["prompts"]
                    if row["prompt_id"] == prompt and row["state"] not in ("waiting", "ready", "held")]
        for row in finished:
            self.assertNotIn("images", row, "a finished message says nothing of pictures")


if __name__ == "__main__":
    unittest.main()

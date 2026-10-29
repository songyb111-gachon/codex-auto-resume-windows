# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Pictures in the scheduled-message editor (v0.6.20, #50 item 1): Add a picture... adds the files it is handed - never a
file dialog shown here - as a row of thumbnails, each with a Remove; a file that is no picture, or too large, is refused
there with words that say so; a fifth is refused; Remove takes one off; the request names each new picture by its file
and each one a message already had by its copy's id; the real bridge keeps its own copies. Driven through the page's own
hooks, the dialog built and never shown, with the real bridge's answers made in a home of its own.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_images.py
"""
from __future__ import annotations

import base64
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, sent  # noqa: E402
import test_advanced_page_editor as editor_page  # noqa: E402

WORDS = editor_page.WORDS
_EDITOR = editor_page.PageTests.__dict__

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
MINE = Path(tempfile.mkdtemp(prefix="car-v0620-images-page-"))


def tearDownModule():
    shutil.rmtree(MINE, True)


def picture(name, data=PNG):
    path = MINE / name
    path.write_bytes(data)
    return str(path)


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    opened, on, thread, add = _EDITOR["opened"], _EDITOR["on"], _EDITOR["thread"], _EDITOR["add"]

    @staticmethod
    def told(found, **more):
        """A scenario's (locale, scenario, expected) with `more` of what its test needs in `expected`."""
        name, scenario, expected = found
        expected.update(more)
        return name, scenario, expected

    @classmethod
    def scenario_add_and_remove(cls, bridge):
        first, second, third = picture("first.png"), picture("second.png"), picture("third.png")
        made = cls.add(bridge, images=[{"path": first}, {"path": third}])
        return cls.told(cls.opened(bridge, [{"do": "editor", "thread": cls.thread(bridge), "words": WORDS,
                                             "when": "at_time", "hour": "14", "images": [first, second, third],
                                             "remove": 1, "press": "save"}],
                                   {"advanced-prompt-add": [made]}), files=[first, second, third])

    @classmethod
    def scenario_refused_files(cls, bridge):
        cls.on(bridge)
        words = picture("not-a-picture.png", b"plain words, named like a picture")
        large = picture("large.png", PNG + b"\0" * (5 * 1024 * 1024))
        fine = [picture("p%d.png" % n) for n in range(5)]
        return cls.opened(bridge, [{"do": "editor", "thread": cls.thread(bridge), "words": WORDS,
                                    "images": [words], "press": "cancel"},
                                   {"do": "editor", "thread": cls.thread(bridge), "words": WORDS,
                                    "images": [large], "press": "cancel"},
                                   {"do": "editor", "thread": cls.thread(bridge), "words": WORDS,
                                    "images": fine, "press": "cancel"}])

    @classmethod
    def scenario_edit_keeps(cls, bridge):
        made = cls.add(bridge, words="the words as written", while_running="queue",
                       images=[{"path": picture("kept.png")}])["result"]["prompt"]
        listed = bridge("advanced-prompts", {})
        kept = next(row for row in listed["result"]["prompts"] if row["prompt_id"] == made)["images"][0]["id"]
        edited = bridge("advanced-prompt-edit", {"prompt": made, "words": WORDS, "trigger": "at_time",
                                                  "at": ac.NOW + 3600, "while_running": "queue",
                                                  "images": [{"id": kept}],
                                                  "generation": bridge("advanced-list", {})["result"]["generation"]})
        added = picture("added.png")
        return cls.told(cls.opened(bridge, [{"do": "editor", "prompt": made, "words": WORDS, "images": [added],
                                             "press": "save"}],
                                   {"advanced-prompt-edit": [edited], "advanced-prompts": [listed]}),
                        kept=kept, added=added)

    # ---------------------------------------------------------------- tests
    def test_added_pictures_show_as_thumbnails_and_remove_takes_one_off(self):
        """Fails with the editor's pictures reverted: there is no Add a picture... to press."""
        result, expected = self.of("scenario_add_and_remove")
        (editor,) = result["dialogs"]
        words = expected["words"]
        self.assertEqual(editor["add_image"], words["page.editor.images.add"])
        self.assertEqual(editor["images_before"], 0)
        picture_name = words["page.editor.images.picture"]
        self.assertEqual(editor["thumbs_added"], [picture_name.replace("{n}", str(n)) + ":drawn" for n in (1, 2, 3)])
        self.assertEqual(editor["thumbs"], [picture_name.replace("{n}", str(n)) + ":drawn" for n in (1, 2)])
        self.assertTrue(editor["thumbs_shown"])
        self.assertTrue(editor["thumbs_fit"], "the row wraps inside the card: nothing scrolls sideways")
        self.assertEqual(editor["said_on_add"], "")
        self.assertTrue(editor["taken"], editor)

    def test_the_request_names_each_picture_by_its_file_in_order(self):
        result, expected = self.of("scenario_add_and_remove")
        (request,) = sent(result, "advanced-prompt-add")
        files = expected["files"]
        self.assertEqual(request["images"], [{"path": files[0]}, {"path": files[2]}], "the second was removed")

    def test_a_file_that_is_no_picture_too_large_or_a_fifth_is_refused_with_words(self):
        result, expected = self.of("scenario_refused_files")
        words = expected["words"]
        not_one, large, fifth = result["dialogs"]
        self.assertEqual((not_one["thumbs"], not_one["said_on_add"]), ([], words["page.refused.image_refused"]))
        self.assertEqual((large["thumbs"], large["said_on_add"]), ([], words["page.refused.image_too_large"]))
        self.assertEqual(len(fifth["thumbs"]), 4)
        self.assertEqual(fifth["said_on_add"], words["page.refused.images_full"])
        self.assertFalse(fifth["add_enabled"], "four: Add a picture... is not offered")
        self.assertEqual(sent(result, "advanced-prompt-add"), [])

    def test_an_edit_opens_with_its_pictures_and_keeps_them_by_id(self):
        result, expected = self.of("scenario_edit_keeps")
        (editor,) = result["dialogs"]
        self.assertEqual(editor["images_before"], 1)
        (request,) = sent(result, "advanced-prompt-edit")
        self.assertEqual(request["images"], [{"id": expected["kept"]}, {"path": expected["added"]}])
        self.assertTrue(editor["taken"])


if __name__ == "__main__":
    unittest.main()

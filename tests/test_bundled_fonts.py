"""Bundled Persian typefaces retain their upstream bytes and redistribution license."""
import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class BundledFontsTests(unittest.TestCase):
    def test_pinned_font_assets_and_license_ship_in_the_application(self):
        folder=ROOT/'assets/fonts/vazirmatn'
        provenance=json.loads((folder/'source.json').read_text(encoding='utf8'))
        spec=importlib.util.spec_from_file_location('font_release_builder',ROOT/'build/make_release.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        for name,record in provenance['files'].items():
            path=folder/name
            # Git normalizes the license/authors line endings on Windows.
            data = path.read_text(encoding="utf8").encode("utf8") if path.suffix == ".txt" else path.read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),record['sha256'],name)
            self.assertTrue(builder._wanted(path.relative_to(ROOT)))
        for name in ('Vazirmatn-Regular.ttf','Vazirmatn-Bold.ttf'):
            self.assertEqual((folder/name).read_bytes()[:4],b'\x00\x01\x00\x00')
            self.assertIn('assets/fonts/vazirmatn/'+name,builder.REQUIRED_APP_FILES)
        self.assertIn('assets/fonts/vazirmatn/OFL.txt',builder.REQUIRED_APP_FILES)
        self.assertIn('SIL OPEN FONT LICENSE Version 1.1',(folder/'OFL.txt').read_text(encoding='utf8'))

    def test_release_validates_registry_and_requires_bundled_fonts(self):
        spec=importlib.util.spec_from_file_location('font_release_validation',ROOT/'build/make_release.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as temporary:
            stage=Path(temporary)
            for name in builder.REQUIRED_APP_FILES:
                destination=stage/'payload/app'/name
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/name,destination)
            builder.check_app_files(stage)
            (stage/'payload/app/assets/fonts/vazirmatn/Vazirmatn-Bold.ttf').unlink()
            with self.assertRaisesRegex(SystemExit,'missing.*Vazirmatn-Bold'):
                builder.check_app_files(stage)

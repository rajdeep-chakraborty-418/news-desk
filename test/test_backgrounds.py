"""backgrounds.py: image sets per place, read from a config folder and published with a manifest."""
import json

from support import TestCase

import backgrounds

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 2"/>'


class BackgroundsTest(TestCase):
    def setUp(self):
        super().setUp()
        self.src = self.tmp / "bg"
        self.out = self.tmp / "site"

    def add(self, place, name, data=SVG):
        (self.src / place).mkdir(parents=True, exist_ok=True)
        (self.src / place / name).write_bytes(data)

    def test_every_image_in_a_folder_is_in_its_set(self):
        self.add("landing", "a.svg"); self.add("landing", "b.JPG"); self.add("sports", "s one.png")
        self.add("sports", "notes.txt", b"x")
        m = backgrounds.build(self.out, {"sports", "world"}, self.src)
        self.assertEqual(m, {"landing": ["backgrounds/landing/a.svg", "backgrounds/landing/b.JPG"], "sports": ["backgrounds/sports/s%20one.png"]})
        self.assertEqual((self.out / "backgrounds" / "sports" / "s one.png").read_bytes(), SVG)
        self.assertFalse((self.out / "backgrounds" / "sports" / "notes.txt").exists())
        self.assertEqual(json.loads((self.out / "backgrounds.json").read_text()), m)

    def test_removing_an_image_removes_it_from_the_site(self):
        self.add("world", "a.svg"); self.add("world", "b.svg")
        backgrounds.build(self.out, {"world"}, self.src)
        (self.src / "world" / "b.svg").unlink()
        m = backgrounds.build(self.out, {"world"}, self.src)
        self.assertEqual(m, {"world": ["backgrounds/world/a.svg"]})
        self.assertFalse((self.out / "backgrounds" / "world" / "b.svg").exists())

    def test_unknown_folders_and_huge_files_are_skipped(self):
        self.add("nonsense", "a.svg"); self.add("world", "big.png", b"0" * (backgrounds.MAX_BYTES + 1))
        self.assertEqual(backgrounds.build(self.out, {"world"}, self.src), {})
        self.assertFalse((self.out / "backgrounds" / "nonsense").exists())

    def test_no_folder_means_an_empty_manifest(self):
        self.assertEqual(backgrounds.build(self.out, {"world"}, self.tmp / "missing"), {})
        self.assertEqual(json.loads((self.out / "backgrounds.json").read_text()), {})

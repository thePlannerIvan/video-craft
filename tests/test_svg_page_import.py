"""The seam between the static picture page (SVG) and the animation layer.

A page arrives either as the picture package `input/scenes/<page_key>.svg` or as
the picture project's `_internal/02_svg_source/<page_key>.svg`. Two failures this
file exists for:

① **The page must arrive as the page.** The importer rewrites image href
   prefixes (a `../00_project/...` href is rejected by HyperFrames as
   `invalid_parent_traversal_in_asset_path`), and rewriting anything else would
   make the animation layer's coordinates and ids refer to a different page than
   the one that was approved. `test_page_survives_the_import_byte_for_byte`
   compares bytes; `test_only_image_hrefs_move` pins the scope of the rewrite.

② **Addressing must be by `id`.** A page whose only id is on the root `<svg>`
   has nothing the animation can name. DOM order is not a substitute: one more
   `<text>` after a re-render re-binds `slice(-10)` to a different element and
   nothing fails. `test_ids_are_the_only_addressable_hook` and
   `test_data_attributes_are_not_element_ids` are that boundary.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).parents[1]
SCRIPTS = SKILL / "visual" / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"video_craft_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses resolves the class's module through sys.modules
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pages = load("import_svg_page")

PAGE_TEMPLATE = """<svg data-layout-id="content_base"{root_id} width="1920" height="1080" viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<!--
page_key="{page_key}"
screen_id="{page_key}"
design="one real photo, no words"
-->
<rect x="0" y="0" width="1920" height="1080" fill="#101216"/>
<image xlink:href="{href}" href="{href}" x="690" y="312" width="540" height="456" preserveAspectRatio="xMidYMid meet"/>
<use xlink:href="#grain"/>
<text{text_id} x="180" y="330" font-size="72">所有人都穿上</text>
</svg>
"""


class PageImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.ppt = self.root / "ppt"
        self.page_dir = self.ppt / "_internal" / "02_svg_source"
        self.page_dir.mkdir(parents=True)
        self.project = self.root / "video"
        self.project.mkdir()

    def write_page(self, page_key: str = "beat-01",
                   href: str = "../00_project/source/assets/asset_001.jpg",
                   root_id: str = "", text_id: str = "title") -> Path:
        text = PAGE_TEMPLATE.format(
            page_key=page_key, href=href,
            root_id=f' id="{page_key}"' if root_id else "",
            text_id=f' id="{text_id}"' if text_id else "")
        path = self.page_dir / f"{page_key}.svg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_asset(self, rel: str = "00_project/source/assets/asset_001.jpg") -> Path:
        asset = self.ppt / "_internal" / rel
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg")
        return asset

    def import_page(self, page_key: str = "beat-01", **kwargs):
        return pages.import_page(page_key, page_dir=self.page_dir,
                                 asset_root=self.ppt, project=self.project, **kwargs)

    # ① the page arrives as the page -----------------------------------------

    def test_page_survives_the_import_byte_for_byte(self):
        source = self.write_page()
        self.write_asset()
        result = self.import_page()
        self.assertTrue(result.verbatim, "the round trip changed the page")
        self.assertEqual(result.restored_sha256, result.source_sha256)
        self.assertEqual(result.source_sha256,
                         pages.sha256_text(source.read_text(encoding="utf-8")))

    def test_only_image_hrefs_move(self):
        self.write_page()
        self.write_asset()
        result = self.import_page()
        # both href and xlink:href carry the same value, so both move
        self.assertEqual(sorted({s["before"] for s in result.substitutions}),
                         ["../00_project/source/assets/asset_001.jpg"])
        self.assertEqual({s["after"] for s in result.substitutions},
                         {"assets/pages/beat-01/asset_001.jpg"})
        # a <use> reference into the page's own defs is not an image and stays put
        self.assertIn('<use xlink:href="#grain"/>', result.inlined)
        self.assertNotIn("../00_project", result.inlined)
        # and only the href values moved: the element itself is untouched
        self.assertIn('<image xlink:href="assets/pages/beat-01/asset_001.jpg" '
                      'href="assets/pages/beat-01/asset_001.jpg" x="690" y="312" '
                      'width="540" height="456" preserveAspectRatio="xMidYMid meet"/>',
                      result.inlined)

    def test_assets_land_inside_the_composition(self):
        self.write_page()
        self.write_asset()
        self.import_page()
        copied = self.project / "composition" / "assets" / "pages" / "beat-01" / "asset_001.jpg"
        self.assertTrue(copied.is_file())

    def test_missing_asset_is_reported(self):
        self.write_page()
        result = self.import_page()
        self.assertTrue(any("missing file" in p for p in result.problems), result.problems)

    def test_href_outside_the_package_refuses_the_import(self):
        self.write_page(href="../../../../../../etc/hosts")
        with self.assertRaises(pages.PageImportError) as caught:
            self.import_page()
        self.assertIn("outside the picture package", str(caught.exception))

    def test_two_sources_with_one_name_both_survive(self):
        self.write_page(href="../00_project/source/assets/asset_001.jpg")
        self.write_asset("00_project/source/assets/asset_001.jpg")
        other = self.ppt / "_internal" / "other" / "asset_001.jpg"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_bytes(b"second")
        page = self.page_dir / "beat-01.svg"
        page.write_text(page.read_text(encoding="utf-8").replace(
            '<use xlink:href="#grain"/>',
            '<image href="../other/asset_001.jpg" x="0" y="0" width="10" height="10"/>'),
            encoding="utf-8")
        result = self.import_page()
        self.assertTrue(result.verbatim)
        targets = sorted(s["after"] for s in result.substitutions)
        self.assertEqual(len(set(targets)), 2, targets)
        for target in targets:
            self.assertTrue((self.project / "composition" / target).is_file(), target)

    # ② addressing ------------------------------------------------------------

    def test_ids_are_the_only_addressable_hook(self):
        self.write_page(root_id="yes", text_id="title")
        self.write_asset()
        audit = self.import_page().audit
        self.assertEqual(audit["element_ids"], ["title"])
        self.assertEqual(audit["root_ids"], ["beat-01"])
        self.assertTrue(audit["addressable"])
        self.assertEqual(audit["viewBox"], "0 0 1920 1080")

    def test_a_root_id_alone_is_not_addressable(self):
        self.write_page(root_id="yes", text_id="")
        self.write_asset()
        audit = self.import_page().audit
        self.assertEqual(audit["element_ids"], [])
        self.assertFalse(audit["addressable"],
                         "an id on <svg> names the page, not an element")

    def test_data_attributes_are_not_element_ids(self):
        path = self.page_dir / "beat-01.svg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<svg data-layout-id="content_base" viewBox="0 0 1920 1080">\n'
                        '<g data-node-id="n1"/>\n</svg>\n', encoding="utf-8")
        audit = self.import_page().audit
        self.assertEqual(audit["element_ids"], [], "data-*-id must not count as an id")
        self.assertFalse(audit["addressable"])

    def test_live_structure_is_reported(self):
        self.write_page(text_id="title")
        self.write_asset()
        audit = self.import_page().audit
        self.assertEqual(audit["text_nodes"], 1)
        self.assertEqual(audit["flattened_nodes"], 0,
                         "no clipPath/mask/transform should be baked into a page")

    # where the pages come from ----------------------------------------------

    def test_pointer_at_the_picture_project_resolves_to_its_svg_source(self):
        self.assertEqual(pages.resolve_pages(self.project, self.ppt),
                         (self.page_dir.resolve(), self.ppt.resolve()))

    def test_the_documented_page_directory_call_resolves_the_same_way(self):
        """`--pages <project>/_internal/02_svg_source` is in the docstring.

        It used to resolve the href boundary to the page directory, so every
        `../00_project/...` href "escaped" it and the import failed on the very
        pages it shipped — with advice that broke the byte-for-byte promise.
        """
        self.write_page()
        self.write_asset()
        root_pair = pages.resolve_pages(self.project, self.ppt)
        page_dir_pair = pages.resolve_pages(self.project, self.page_dir)
        self.assertEqual(page_dir_pair, root_pair)
        result = pages.import_page("beat-01", page_dir=page_dir_pair[0],
                                   asset_root=page_dir_pair[1], project=self.project)
        self.assertTrue(result.verbatim)
        self.assertEqual(result.substitutions[0]["after"], "assets/pages/beat-01/asset_001.jpg")

    def test_a_directory_that_is_not_under_internal_uses_its_parent(self):
        scenes = self.root / "plain-scenes"
        scenes.mkdir()
        (scenes / "p.svg").write_text('<svg viewBox="0 0 1920 1080"/>', encoding="utf-8")
        self.assertEqual(pages.resolve_pages(self.project, scenes),
                         (scenes.resolve(), self.root.resolve()))

    def test_the_handed_over_package_is_found_without_a_pointer(self):
        scenes = self.project / "input" / "scenes"
        scenes.mkdir(parents=True)
        (scenes / "beat-01.svg").write_text(
            '<svg viewBox="0 0 1920 1080"/>', encoding="utf-8")
        self.assertEqual(pages.resolve_pages(self.project),
                         (scenes.resolve(), (self.project / "input").resolve()))

    def test_every_package_shape_resolves_to_the_same_pair(self):
        scenes = self.project / "input" / "scenes"
        scenes.mkdir(parents=True)
        (scenes / "beat-01.svg").write_text('<svg viewBox="0 0 1920 1080"/>', encoding="utf-8")
        expected = (scenes.resolve(), (self.project / "input").resolve())
        for candidate in (self.project, self.project / "input", scenes):
            self.assertEqual(pages.resolve_pages(self.project, candidate), expected, candidate)

    def test_pages_pointer_resolves_relative_to_the_project(self):
        pointer = self.project / ".pages"
        pointer.write_text("../ppt\n", encoding="utf-8")
        self.assertEqual(pages.resolve_pages(self.project)[0], self.page_dir.resolve())

    def test_no_pages_anywhere_resolves_to_nothing(self):
        self.assertEqual(pages.resolve_pages(self.project), (None, None))

    # ids across pages --------------------------------------------------------

    def test_ids_shared_by_two_pages_are_reported(self):
        self.write_page(page_key="beat-01", text_id="caption-1")
        self.write_page(page_key="beat-02", text_id="caption-1")
        self.write_asset()
        results = [self.import_page("beat-01"), self.import_page("beat-02")]
        audit = pages.audit_pages(results)
        self.assertFalse(audit["clean"])
        self.assertEqual(audit["collisions"], {"caption-1": ["beat-01", "beat-02"]})

    def test_unique_ids_are_not_a_collision(self):
        self.write_page(page_key="beat-01", text_id="beat-01-headline")
        self.write_page(page_key="beat-02", text_id="beat-02-headline")
        self.write_asset()
        results = [self.import_page("beat-01"), self.import_page("beat-02")]
        audit = pages.audit_pages(results)
        self.assertTrue(audit["clean"])
        self.assertEqual(audit["collisions"], {})

    def test_the_same_id_twice_on_one_page_is_left_to_the_picture_side(self):
        """A duplicate inside one page is that page's own defect, not a cross-page one."""
        self.write_page(page_key="beat-01", text_id="caption-1")
        self.write_asset()
        result = self.import_page("beat-01")
        self.assertEqual(pages.audit_pages([result])["clean"], True)

    # the film-wide default ---------------------------------------------------

    def test_design_direction_carries_the_default_composite_facts(self):
        direction = self.ppt / "_internal" / "01_content" / "design_direction.md"
        direction.parent.mkdir(parents=True, exist_ok=True)
        direction.write_text(
            "# 方向\n\n## 合成方式\n\n```json\n"
            '{"composite": "over-person", "captionSafe": {"x": 0, "y": 860, "w": 1920, "h": 220}}\n'
            "```\n", encoding="utf-8")
        default = pages.read_composite_default(self.ppt)
        self.assertEqual(default["composite"], "over-person")
        self.assertEqual(default["captionSafe"]["h"], 220)

    def test_no_design_direction_means_no_default(self):
        self.assertEqual(pages.read_composite_default(self.ppt), {})


class RealPageTests(unittest.TestCase):
    """Against a project made by the picture side, when one is on this machine."""

    PROJECT = SKILL.parents[2] / "05-VideoProject" / "06-测试-Vans-20260926"
    PPT = PROJECT / "08_ppt-hell"

    @unittest.skipUnless((PPT / "_internal" / "02_svg_source").is_dir(),
                         "no picture project on this machine")
    def test_every_real_page_survives_the_import(self):
        page_dir, asset_root = pages.resolve_pages(self.PROJECT, self.PPT)
        keys = pages.list_pages(page_dir)
        self.assertTrue(keys, "no pages found")
        with tempfile.TemporaryDirectory() as tmp:
            for key in keys:
                result = pages.import_page(key, page_dir=page_dir,
                                           asset_root=asset_root, project=Path(tmp))
                self.assertTrue(result.verbatim, f"{key} did not survive the import")
                self.assertEqual(result.audit["viewBox"], "0 0 1920 1080",
                                 f"{key}: page coordinates must equal video pixels")


class ManifestTests(unittest.TestCase):
    def test_manifest_records_the_seam(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page_dir = root / "ppt" / "_internal" / "02_svg_source"
            page_dir.mkdir(parents=True)
            (page_dir / "p1.svg").write_text(
                '<svg viewBox="0 0 1920 1080"><image href="../a/x.jpg"/></svg>\n', encoding="utf-8")
            (root / "ppt" / "_internal" / "a").mkdir(parents=True)
            (root / "ppt" / "_internal" / "a" / "x.jpg").write_bytes(b"x")
            project = root / "video"
            project.mkdir()
            result = pages.import_page("p1", page_dir=page_dir,
                                       asset_root=root / "ppt", project=project)
            out = pages.write_manifest(project, {"composite": "replace"}, [result],
                                       {"step-1": {"composite": "replace"}})
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(data["pages"][0]["verbatim"])
            self.assertEqual(data["default"]["composite"], "replace")
            self.assertEqual(data["perScreen"]["step-1"]["composite"], "replace")
            self.assertIn("ids", data)


class CompositionGuardTests(unittest.TestCase):
    """`generate-composition.py --verify` refuses an asset path that leaves the root.

    The importer rewrites `<image>` hrefs when it inlines a page, so the
    composition should contain only root-relative paths. This gate makes that
    non-optional: a page that reached the HTML without the rewrite (the reported
    hand-inlining route) is caught here instead of by `hyperframes check`
    (`invalid_parent_traversal_asset_path`) or at render time.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)
        (self.project / "timeline").mkdir()
        (self.project / "composition").mkdir()
        (self.project / "timeline" / "timeline.json").write_text(json.dumps({
            "totalDurationMs": 4000,
            "chapters": [{"id": "ch", "title": "ch", "steps": [
                {"id": "step-1", "startMs": 0, "endMs": 4000, "durationMs": 4000,
                 "caption": "一"}]}],
        }), encoding="utf-8")

    def load_generator(self):
        spec = importlib.util.spec_from_file_location(
            "video_craft_generate", SCRIPTS / "generate-composition.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def write_html(self, asset_path: str) -> None:
        (self.project / "composition" / "index.html").write_text(
            '<!doctype html><html><body><div id="root" data-composition-id="main" '
            'data-start="0" data-duration="4.000" data-width="1920" data-height="1080">'
            f'<section class="clip scene" id="step-step-1" data-start="0.000" '
            f'data-duration="4.000" data-track-index="0"><image href="{asset_path}"/></section>'
            '</div></body></html>', encoding="utf-8")

    def test_a_root_relative_asset_path_passes(self):
        self.write_html("assets/pages/beat-01/pic.jpg")
        self.assertEqual(self.load_generator().verify(self.project), 0)

    def test_a_parent_traversal_path_fails_verification(self):
        self.write_html("../00_project/source/assets/pic.jpg")
        self.assertEqual(self.load_generator().verify(self.project), 1)


if __name__ == "__main__":
    unittest.main()

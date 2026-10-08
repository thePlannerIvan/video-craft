from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / 'visual/scripts'
sys.path.insert(0, str(SCRIPTS))
from snapshot_input import SnapshotError, resolve_snapshot, sha256, asset_records
import import_svg_page as pages
import auto_choreography as choreography


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


generator = load(SCRIPTS / 'generate-composition.py', 'snapshot_generator')
review = load(SKILL / 'helpers/build_review.py', 'snapshot_review')
store = load(SKILL.parent / 'planners-ppt-hell/scripts/workbench_store.py', 'adapter_fixture_store')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.project = self.root / 'video'
        (self.project / 'timeline').mkdir(parents=True)
        timeline = {'fps': 30, 'totalDurationMs': 8000, 'chapters': [{'id': 'ch', 'steps': [
            {'id': key, 'sourcePageKey': key, 'startMs': start, 'durationMs': 4000, 'caption': 'original'}
            for key, start in [('beat-01', 0), ('beat-02', 4000)]]}]}
        self.timeline = self.project / 'timeline/timeline.json'
        self.timeline.write_text(json.dumps(timeline))
        self.timeline_bytes = self.timeline.read_bytes()

    def snapshot(self, identity='snap_first', changed=False, new_step=False, embedded=False):
        root = self.root / '_internal/06_workbench/snapshots' / identity
        (root / 'scenes/assets').mkdir(parents=True)
        (root / 'upstream').mkdir()
        script = b'original script\n'
        plan = {'contract_version': '5.0', 'script_hash': sha256(script),
                'screens': [{'screen_id': key} for key in ['beat-01', 'beat-02']]}
        plan_raw = json.dumps(plan).encode()
        (root / 'upstream/visual-plan.json').write_bytes(plan_raw)
        (root / 'upstream/script.md').write_bytes(script)
        records = []
        for key in ['beat-01', 'beat-02']:
            text = 'edited' if changed and key == 'beat-01' else 'original'
            element = key + ('-new' if new_step and key == 'beat-01' else '-title')
            asset = b'first pinned bytes'
            asset_name = f'scenes/assets/{sha256(asset)}.png'
            (root / asset_name).write_bytes(asset)
            href = 'data:image/png;base64,eA==' if embedded else 'assets/' + Path(asset_name).name
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" data-page-key="{key}" viewBox="0 0 1920 1080">'
                   f'<image data-workbench-id="{key}-image" href="{href}"/>'
                   f'<g id="{element}" data-step="1" data-anim="stamp-in"><text>{text}</text></g></svg>')
            (root / f'scenes/{key}.svg').write_text(svg)
            assets = [{'embedded': True, 'element_id': key + '-image', 'sha256': sha256(href.encode())}] if embedded else [
                {'path': asset_name, 'sha256': sha256(asset)}]
            records.append({'page_key': key, 'revision': 'rev_new' if changed and key == 'beat-01' else 'rev_' + key,
                            'svg': f'scenes/{key}.svg', 'svg_sha256': sha256(svg.encode()),
                            'assets': assets, 'notes': 'notes', 'input': {}, 'human_edits': {},
                            'content_delta': [{'text': text}] if changed and key == 'beat-01' else []})
        data = {'version': 'svg-workbench-snapshot/1', 'snapshot_id': identity,
                'route': 'video', 'order': ['beat-02', 'beat-01'], 'pages': records,
                'content_binding': 'changed_needs_check' if changed else 'baseline',
                'upstream': {'visual_contract': {'path': '/upstream/visual-plan.json', 'sha256': sha256(plan_raw),
                                                'script_hash': sha256(script)},
                             'visual_plan_snapshot': 'upstream/visual-plan.json',
                             'script_snapshot': 'upstream/script.md', 'script_sha256': sha256(script)}}
        self.write_manifest(root, data)
        (self.project / '.pages').write_text(str(root / 'snapshot.json'))
        return root, data

    def write_manifest(self, root, data):
        raw = json.dumps(data).encode()
        (root / 'snapshot.json').write_bytes(raw)
        (root / 'snapshot.sha256').write_text(sha256(raw))

    def consumers(self):
        return [lambda: pages.resolve_pages(self.project),
                lambda: generator.load_picture_pages(self.project),
                lambda: choreography.build_choreography(self.project),
                lambda: review.find_svg_scenes(self.project, self.project / 'edit')]

    def test_all_consumers_read_same_order_and_pinned_assets(self):
        root, _ = self.snapshot()
        directory, boundary = pages.resolve_pages(self.project)
        self.assertEqual(directory, root / 'scenes')
        self.assertEqual(boundary, root)
        self.assertEqual(pages.list_pages(directory), ['beat-02', 'beat-01'])
        imported = pages.import_page('beat-01', page_dir=directory, asset_root=boundary, project=self.project)
        self.assertTrue(imported.verbatim)
        reviewed = review.find_svg_scenes(self.project, self.project / 'edit')
        self.assertEqual(list(reviewed), ['beat-02', 'beat-01'])
        self.assertIn('../composition/assets/pages/beat-01/', reviewed['beat-01'])
        doc = choreography.build_choreography(self.project)
        self.assertEqual(doc['snapshot']['snapshot_id'], 'snap_first')
        generator.generate(self.project, 'midnight-press', None)
        manifest = json.loads((self.project / 'composition/pages/manifest.json').read_text())
        self.assertEqual(manifest['snapshot']['sha256'], resolve_snapshot(self.project).digest)
        self.assertEqual(self.timeline.read_bytes(), self.timeline_bytes)

    def test_all_consumers_reject_mutated_svg_even_with_legacy_fallback(self):
        root, _ = self.snapshot()
        (root / 'scenes/beat-01.svg').write_text('<svg/>')
        (self.project / 'input/scenes').mkdir(parents=True)
        (self.project / 'input/scenes/beat-01.svg').write_text('<svg/>')
        for consumer in self.consumers():
            with self.assertRaises(SnapshotError):
                consumer()

    def test_mutated_asset_rejected(self):
        root, _ = self.snapshot()
        next((root / 'scenes/assets').iterdir()).write_bytes(b'replaced')
        with self.assertRaises(SnapshotError):
            resolve_snapshot(self.project)

    def test_missing_sidecar_and_manifest_mutation_rejected(self):
        root, data = self.snapshot()
        (root / 'snapshot.sha256').unlink()
        with self.assertRaises(SnapshotError):
            resolve_snapshot(self.project)
        self.write_manifest(root, data)
        (root / 'snapshot.json').write_text('{}')
        with self.assertRaises(SnapshotError):
            resolve_snapshot(self.project)

    def test_missing_manifest_never_falls_back_to_legacy_scenes(self):
        root, _ = self.snapshot()
        (root / 'snapshot.json').unlink()
        (self.project / 'input/scenes').mkdir(parents=True)
        (self.project / 'input/scenes/beat-01.svg').write_text('<svg/>')
        for explicit in (root, root / 'scenes', root / 'snapshot.json'):
            with self.subTest(explicit=explicit), self.assertRaisesRegex(SnapshotError, 'Missing snapshot manifest'):
                pages.resolve_pages(self.project, explicit)
        with self.assertRaisesRegex(SnapshotError, 'Missing snapshot manifest'):
            pages.import_page('beat-01', page_dir=root / 'scenes', asset_root=root, project=self.project)
        with self.assertRaisesRegex(SnapshotError, 'Missing snapshot manifest'):
            pages.list_pages(root / 'scenes')
        (self.project / '.pages').write_text(str(root))
        for consumer in self.consumers():
            with self.assertRaisesRegex(SnapshotError, 'Missing snapshot manifest'):
                consumer()
        (root / 'snapshot.sha256').unlink()
        for explicit in (root, root / 'scenes'):
            with self.subTest(no_sidecar=explicit), self.assertRaisesRegex(SnapshotError, 'Missing snapshot manifest'):
                pages.resolve_pages(self.project, explicit)

    def test_remaining_sidecar_marks_external_package_as_snapshot(self):
        root, _ = self.snapshot()
        package = self.root / 'external-package'
        root.rename(package)
        (package / 'snapshot.json').unlink()
        for explicit in (package, package / 'scenes'):
            with self.subTest(explicit=explicit), self.assertRaisesRegex(SnapshotError, 'Missing snapshot manifest'):
                pages.resolve_pages(self.project, explicit)

    def test_consumed_snapshot_cannot_be_resigned_with_same_identity(self):
        root, data = self.snapshot()
        choreography.build_choreography(self.project)
        data['pages'][0]['notes'] = 'mutated notes'
        self.write_manifest(root, data)
        with self.assertRaises(SnapshotError):
            resolve_snapshot(self.project)

    def test_reimport_marks_only_affected_screen_and_preserves_timeline(self):
        self.snapshot()
        original = choreography.build_choreography(self.project)
        original['screens']['beat-02']['custom_camera'] = {'owned_by_craft': True}
        (self.project / 'timeline/choreography.json').write_text(json.dumps(original))
        root, _ = self.snapshot('snap_second', changed=True)
        doc = choreography.build_choreography(self.project)
        self.assertEqual(doc['invalidation']['static_screens'], ['beat-01'])
        self.assertEqual(doc['invalidation']['animation_screens'], [])
        self.assertEqual(doc['screens']['beat-02'], original['screens']['beat-02'])
        self.assertEqual(doc['snapshot']['content_binding'], 'changed_needs_check')
        self.assertFalse(doc['snapshot']['script_semantics_verified'])
        self.assertEqual(doc['invalidation']['content_review_screens'], ['beat-01'])
        self.assertFalse(doc['invalidation']['audio_retimed'])
        self.assertEqual(self.timeline.read_bytes(), self.timeline_bytes)

    def test_notes_only_revision_does_not_invalidate_static_or_animation(self):
        self.snapshot()
        choreography.build_choreography(self.project)
        root, data = self.snapshot('snap_second')
        data['pages'][0]['revision'] = 'rev_notes'
        data['pages'][0]['notes'] = 'Updated notes only'
        self.write_manifest(root, data)
        doc = choreography.build_choreography(self.project)
        self.assertEqual(doc['invalidation']['static_screens'], [])
        self.assertEqual(doc['invalidation']['animation_screens'], [])

    def test_new_step_identity_does_not_inherit_old_animation(self):
        self.snapshot()
        doc = choreography.build_choreography(self.project)
        doc['screens']['beat-01']['steps']['1']['anim'] = 'old-custom-animation'
        (self.project / 'timeline/choreography.json').write_text(json.dumps(doc))
        self.snapshot('snap_second', changed=True, new_step=True)
        rebuilt = choreography.build_choreography(self.project)
        self.assertEqual(rebuilt['invalidation']['animation_screens'], ['beat-01'])
        self.assertEqual(rebuilt['screens']['beat-01']['steps']['1']['anim'], 'stamp-in')

    def test_embedded_asset_and_independent_snapshot_are_valid(self):
        root, _ = self.snapshot(embedded=True)
        self.assertEqual(resolve_snapshot(self.project).root, root)
        external = self.root / 'live-script.md'
        external.write_text('unrelated live change')
        self.assertEqual(resolve_snapshot(self.project).data['content_binding'], 'baseline')

    def test_wrong_order_svg_path_and_upstream_script_rejected(self):
        root, data = self.snapshot()
        data['order'] = ['beat-01', 'beat-01']
        self.write_manifest(root, data)
        with self.assertRaises(SnapshotError):
            resolve_snapshot(self.project)
        data['order'] = ['beat-01', 'beat-02']
        data['pages'][0]['svg'] = 'scenes/beat-02.svg'
        self.write_manifest(root, data)
        with self.assertRaises(SnapshotError):
            resolve_snapshot(self.project)
        data['pages'][0]['svg'] = 'scenes/beat-01.svg'
        self.write_manifest(root, data)
        (root / 'upstream/script.md').write_bytes(b'edited script')
        with self.assertRaises(SnapshotError):
            resolve_snapshot(self.project)

    def test_unknown_timeline_identity_is_rejected(self):
        self.snapshot()
        doc = json.loads(self.timeline.read_bytes())
        doc['chapters'][0]['steps'][0]['sourcePageKey'] = 'renamed-screen'
        self.timeline.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError, 'matching snapshot page'):
            choreography.build_choreography(self.project)

    def test_changed_text_cannot_claim_baseline(self):
        root, data = self.snapshot(changed=True)
        data['content_binding'] = 'baseline'
        self.write_manifest(root, data)
        with self.assertRaisesRegex(SnapshotError, 'claim baseline'):
            resolve_snapshot(self.project)

    def actual_store_project(self, nested=False):
        ppt = self.root / 'ppt'
        scenes = ppt / '_internal/02_svg_source'
        scenes.mkdir(parents=True)
        (ppt / '_internal/01_content').mkdir()
        (ppt / '_internal/00_project').mkdir()
        live_asset = ppt / 'image.png'
        live_asset.write_bytes(b'baseline image')
        if nested:
            (ppt / 'nested-middle.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="image.png"/></svg>')
            (ppt / 'nested.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="nested-middle.svg"/></svg>')
        script = self.root / 'script.md'
        script.write_bytes(b'original script')
        plan = self.root / 'visual-plan.json'
        plan.write_text(json.dumps({'contract_version': '5.0', 'script_hash': sha256(script.read_bytes()),
                                    'screens': [{'screen_id': key} for key in ['beat-01', 'beat-02']]}))
        (ppt / '_internal/00_project/page_manifest.json').write_text(json.dumps({
            'route': 'video', 'visual_plan': {'path': str(plan), 'sha256': sha256(plan.read_bytes()),
                                            'script_hash': sha256(script.read_bytes())}}))
        (ppt / '_internal/01_content/page_content.json').write_text(json.dumps({'pages': [
            {'page_key': key, 'title': key, 'content': 'original', 'notes': 'notes'} for key in ['beat-01', 'beat-02']]}))
        for key in ['beat-01', 'beat-02']:
            (scenes / f'{key}.svg').write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">'
                f'<image href="../../{"nested.svg" if nested else "image.png"}"/><g id="{key}-step" data-step="1">'
                f'<text id="{key}-text">original</text></g></svg>')
        return ppt, live_asset

    def test_actual_store_snapshot_with_text_change_and_byte_pinned_image(self):
        ppt, live_asset = self.actual_store_project()
        first = store.snapshot(ppt, 'video')
        (self.project / '.pages').write_text(first['path'])
        parsed = resolve_snapshot(self.project)
        self.assertEqual(parsed.data['content_binding'], 'baseline')
        choreography.build_choreography(self.project)
        current = store.get_page(ppt, 'beat-01')
        command = {'op': 'save', 'operation_id': 'test-edit-adapter', 'page_key': 'beat-01',
                   'base_revision': current['revision'], 'edits': [{'kind': 'text',
                    'element_id': 'beat-01-text', 'value': 'new words not yet recorded'}]}
        receipt = store.commit(ppt, command, browser=True)
        self.assertTrue(receipt['ok'], receipt)
        live_asset.write_bytes(b'replaced live image')
        second = store.snapshot(ppt, 'video')
        (self.project / '.pages').write_text(second['path'])
        parsed = resolve_snapshot(self.project)
        self.assertEqual(parsed.data['content_binding'], 'changed_needs_check')
        self.assertEqual(Path(parsed.root / parsed.pages['beat-01']['assets'][0]['path']).read_bytes(), b'baseline image')
        doc = choreography.build_choreography(self.project)
        self.assertEqual(doc['invalidation']['static_screens'], ['beat-01'])
        self.assertEqual(doc['invalidation']['content_review_screens'], ['beat-01'])
        self.assertEqual(self.timeline.read_bytes(), self.timeline_bytes)

    def nested_snapshot(self):
        root, data = self.snapshot()
        child = data['pages'][0]['assets'][0]
        image = child['path']
        nested = (f'<svg xmlns="http://www.w3.org/2000/svg"><image href="{Path(image).name}"/></svg>').encode()
        nested_path = f'scenes/assets/{sha256(nested)}.svg'
        (root / nested_path).write_bytes(nested)
        record = {'path': nested_path, 'sha256': sha256(nested), 'dependencies': [child.copy()]}
        data['pages'][0]['assets'] = [record]
        scene = root / data['pages'][0]['svg']
        scene.write_text(scene.read_text().replace(Path(image).name, Path(nested_path).name))
        data['pages'][0]['svg_sha256'] = sha256(scene.read_bytes())
        self.write_manifest(root, data)
        return root, data, record

    def test_nested_svg_dependencies_copy_byte_identically(self):
        root, data, parent = self.nested_snapshot()
        page_dir, boundary = pages.resolve_pages(self.project)
        result = pages.import_page('beat-01', page_dir=page_dir, asset_root=boundary, project=self.project)
        self.assertTrue(result.verbatim)
        for asset in asset_records([parent]):
            source = root / asset['path']
            output = self.project / 'composition/assets/pages/beat-01' / source.name
            self.assertEqual(output.read_bytes(), source.read_bytes())
        review.find_svg_scenes(self.project, self.project / 'edit')
        generator.generate(self.project, 'midnight-press', None)

    def test_nested_svg_missing_or_mutated_child_is_rejected_by_all_consumers(self):
        root, data, parent = self.nested_snapshot()
        child = root / parent['dependencies'][0]['path']
        child.write_bytes(b'mutated child')
        for consumer in self.consumers():
            with self.assertRaises(SnapshotError):
                consumer()

    def test_unregistered_nested_href_is_rejected(self):
        root, data, parent = self.nested_snapshot()
        parent['dependencies'] = []
        self.write_manifest(root, data)
        with self.assertRaisesRegex(SnapshotError, 'not in pinned'):
            resolve_snapshot(self.project)

    def test_actual_store_nested_asset_pack_is_consumable(self):
        ppt, _ = self.actual_store_project(nested=True)
        snapshot = store.snapshot(ppt, 'video')
        (self.project / '.pages').write_text(snapshot['path'])
        parsed = resolve_snapshot(self.project)
        imported = pages.import_page('beat-01', page_dir=parsed.root / 'scenes',
                                     asset_root=parsed.root, project=self.project)
        self.assertTrue(imported.verbatim)
        for asset in asset_records(parsed.pages['beat-01']['assets']):
            source = parsed.root / asset['path']
            copied = self.project / 'composition/assets/pages/beat-01' / source.name
            self.assertEqual(copied.read_bytes(), source.read_bytes())


if __name__ == '__main__':
    unittest.main()

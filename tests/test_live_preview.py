"""Transport regressions: opaque-origin preview must carry real local assets."""
import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
from live_preview import compile_preview

URL = 'http://127.0.0.1:4317/api/projects/composition/preview/comp/index.html'

class LivePreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'composition/assets').mkdir(parents=True)
        (self.root/'composition/assets/gsap.js').write_text('window.gsap={};')
        (self.root/'composition/assets/voice.wav').write_bytes(b'RIFFtest')
        self.source = '''<!DOCTYPE html><head><base href="/api/projects/composition/preview/">
        <script src="assets/gsap.js"></script><script data-hyperframes-preview-runtime="1" src="/api/runtime.js"></script></head>
        <body><div data-composition-id="main"><audio src="assets/voice.wav"></audio><svg><use href="#x"/></svg></div></body>'''
    def fetch(self, url):
        if url == URL: return self.source
        if url.endswith('/api/runtime.js'): return 'window.runtime=true;'
        self.fail('Unexpected fetch: '+url)
    def test_scripts_local_assets_and_fragment_survive(self):
        out=compile_preview(self.root,URL,self.fetch)
        self.assertIn('window.gsap={};',out['html'])
        self.assertIn('window.runtime=true;',out['html'])
        self.assertNotIn('<base',out['html'])
        self.assertNotIn('src="assets/',out['html'])
        self.assertIn('href="#x"',out['html'])
        self.assertEqual(list(out['assets'].values()),['composition/assets/voice.wav'])
    def test_media_changes_invalidate_snapshot(self):
        first=compile_preview(self.root,URL,self.fetch)
        (self.root/'composition/assets/voice.wav').write_bytes(b'RIFFdifferent')
        self.assertNotEqual(first['sourceHash'],compile_preview(self.root,URL,self.fetch)['sourceHash'])
    def test_external_asset_rejected(self):
        self.source=self.source.replace('assets/voice.wav','https://example.org/voice.wav')
        with self.assertRaisesRegex(ValueError,'External asset'):compile_preview(self.root,URL,self.fetch)
    def test_escape_rejected(self):
        (self.root/'secret.wav').write_bytes(b'private')
        self.source=self.source.replace('assets/voice.wav','../secret.wav')
        with self.assertRaisesRegex(ValueError,'escaping'):compile_preview(self.root,URL,self.fetch)
    def test_spa_response_rejected(self):
        self.source='<html>studio</html>'
        with self.assertRaisesRegex(ValueError,'compiled composition'):compile_preview(self.root,URL,self.fetch)
    def test_external_script_rejected(self):
        self.source=self.source.replace('assets/gsap.js','https://example.org/x.js')
        with self.assertRaisesRegex(ValueError,'External script'):compile_preview(self.root,URL,self.fetch)
    def test_old_embed_bridge_is_not_a_second_clock(self):
        self.source=self.source.replace('</head>','<script src="assets/composition-embed-bridge.js"></script></head>')
        out=compile_preview(self.root,URL,self.fetch)
        self.assertNotIn('composition-embed-bridge',out['html'])
    def test_html_masquerading_as_runtime_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'returned HTML'):
            compile_preview(self.root,URL,lambda u:self.source if u==URL else '<!doctype html><html>SPA</html>')

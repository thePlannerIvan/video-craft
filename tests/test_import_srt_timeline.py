import importlib.util
import tempfile
import unittest
import hashlib
import json
import sys
import subprocess
import shutil
from unittest.mock import patch
from pathlib import Path


HELPER = Path(__file__).parents[1] / 'helpers' / 'import_srt_timeline.py'
SPEC = importlib.util.spec_from_file_location('import_srt_timeline_under_test', HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.path.insert(0, str(HELPER.parent))
SPEC.loader.exec_module(MODULE)


class SourceEvidenceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires real media probes')
    def test_real_external_delivery_and_legacy_audio_reselection(self):
        edit = self.root / 'edit'; edit.mkdir()
        video = edit / 'final.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=1.2', str(self.media)], check=True)
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=320x180:r=30:d=1.2',
                        '-i',str(self.media),'-c:v','libx264','-c:a','aac',str(video)], check=True)
        command = [sys.executable, str(HELPER), str(self.root), '--srt', str(self.srt), '--alignment', str(self.alignment)]
        verifier = [sys.executable, str(HELPER.parent / 'verify_delivery.py'), str(edit), '--video',str(video), '--json']
        def execute(cmd): return subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(execute(command).returncode, 0)
        legacy = execute(verifier); self.assertNotEqual(legacy.returncode, 0); self.assertIn('--media', legacy.stdout)
        migrated = execute(command + ['--media',str(self.media)])
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        normal = execute(verifier); self.assertEqual(normal.returncode, 0, normal.stdout + normal.stderr)
        silent = edit / 'visuals.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(video),'-an','-c:v','copy',str(silent)], check=True)
        silent_command = [*verifier]; silent_command[silent_command.index('--video')+1] = str(silent)
        self.assertNotEqual(execute(silent_command).returncode, 0)
        declared = execute(silent_command + ['--no-audio'])
        self.assertEqual(declared.returncode, 0, declared.stdout + declared.stderr)
        out = self.root / 'delivery'; out.mkdir(); shutil.copyfile(video, out / 'renamed.mp4'); shutil.copyfile(self.srt, out / 'renamed.srt')
        good = execute(verifier + ['--deliver-dir',str(out)]); self.assertEqual(good.returncode, 0, good.stdout)
        (out / 'renamed.srt').write_text('old subtitles')
        stale = execute(verifier + ['--deliver-dir',str(out)]); self.assertNotEqual(stale.returncode, 0, stale.stdout)
        self.assertIn('旧版本', stale.stdout)
        wrong = self.root / 'wrong.wav'; wrong.write_bytes(b'not the selected audio')
        mismatch = execute(verifier + ['--media',str(wrong)]); self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn('版本不同', mismatch.stdout)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.srt = self.root / 'captions.srt'
        self.srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nhello\n')
        script = self.root / 'script.md'; script.write_text('hello')
        plan = self.root / 'visual-plan.json'
        plan.write_text(json.dumps({'script_hash': hashlib.sha256(script.read_bytes()).hexdigest()}))
        self.alignment = self.root / 'alignment.json'
        self.alignment.write_text(json.dumps({
            'sourcePlan': str(plan), 'sourceScript': str(script), 'timelineSource': 'srt-import',
            'entriesHash': hashlib.sha256(json.dumps(MODULE.aligner.parse_srt(self.srt), sort_keys=True).encode()).hexdigest(),
            'beatAlignments': [{'beatId':'b1', 'srtRange':[0,0]}]}))
        self.media = self.root / 'edited.wav'; self.media.write_bytes(b'current audio')
        self.info = {'duration': 1.2, 'streams':[{'codec_type':'audio'}]}

    def imported(self):
        with patch('import_srt_timeline.probe_media', return_value=self.info):
            import import_srt_timeline as imp
            return imp.import_timeline(self.root, self.srt, self.alignment, self.media)

    def test_audio_tail_is_preserved_without_faking_edl_measurement(self):
        data = self.imported()
        self.assertEqual(data['totalDurationMs'], 1200)
        self.assertEqual(data['timeSource'], 'srt-import')
        self.assertIsNone(data['measuredTotalMs'])
        self.assertEqual(data['sourceEvidence']['media']['sha256'], hashlib.sha256(self.media.read_bytes()).hexdigest())

    def test_changed_media_alignment_srt_or_binding_is_rejected(self):
        import import_srt_timeline as imp
        for kind in ('media', 'alignment', 'srt', 'timeline'):
            with self.subTest(kind=kind):
                originals = {p: p.read_bytes() for p in (self.media, self.alignment, self.srt)}
                data = self.imported()
                if kind == 'timeline': data['chapters'][0]['steps'][0]['endMs'] = 900
                else: {'media':self.media, 'alignment':self.alignment, 'srt':self.srt}[kind].write_bytes(b'changed')
                with patch.object(imp, 'probe_media', return_value=self.info):
                    self.assertTrue(imp.source_problems(self.root, data, media=self.media))
                for p, content in originals.items(): p.write_bytes(content)

    def test_legacy_import_can_open_but_needs_audio_once_for_delivery(self):
        import import_srt_timeline as imp
        data = imp.import_timeline(self.root, self.srt, self.alignment)
        self.assertEqual(data['source'], 'srt-import')
        self.assertIn('--media', ' '.join(imp.source_problems(self.root, data)))

    def test_subtitle_beyond_measured_audio_is_rejected(self):
        self.info['duration'] = .5
        with self.assertRaisesRegex(ValueError, '超出'):
            self.imported()

    def test_selected_different_audio_even_same_length_is_rejected(self):
        import import_srt_timeline as imp
        data = self.imported(); other = self.root / 'other.wav'; other.write_bytes(b'wrong audio')
        with patch.object(imp, 'probe_media', return_value=self.info):
            self.assertTrue(imp.source_problems(self.root, data, media=other))


class AlignmentPathTests(unittest.TestCase):
    def test_relative_sources_resolve_from_alignment_or_project_root(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = root / 'project'
            alignment_dir = project / 'timeline'
            alignment_dir.mkdir(parents=True)
            plan = project / 'visual-plan.json'
            script = project / 'script.md'
            plan.write_text('{}', encoding='utf-8')
            script.write_text('script', encoding='utf-8')

            self.assertEqual(
                MODULE.resolve_alignment_path(
                    'visual-plan.json', alignment_dir=alignment_dir, project_root=project
                ),
                plan.resolve(),
            )
            self.assertEqual(
                MODULE.resolve_alignment_path(
                    '../script.md', alignment_dir=alignment_dir, project_root=project
                ),
                script.resolve(),
            )


if __name__ == '__main__':
    unittest.main()

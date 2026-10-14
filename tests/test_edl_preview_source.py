import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BUILDER = Path(__file__).resolve().parents[1] / 'helpers/edl_preview_build.py'

class SourcePreviewTest(unittest.TestCase):
    def test_stale_render_is_only_used_when_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            (edit/'source.mp4').touch()
            (edit/'final.mp4').touch()
            (edit/'edl.json').write_text(json.dumps({'sources':{'a':'source.mp4'},'ranges':[{'source':'a','start':12,'end':18,'speed':2}]}))
            for flags, expected in [([], ('a',12,2)),(['--rendered-preview','final.mp4'],('__PREVIEW__',0,1))]:
                result=subprocess.run([sys.executable,str(BUILDER),str(edit),*flags],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                html=(edit/'edl_preview.html').read_text()
                seg=json.loads(re.search(r'const SEGS = (.*);',html)[1])[0]
                self.assertEqual((seg['src'],seg['start'],seg['speed']),expected)
                self.assertEqual(seg['o1'],3)
            result=subprocess.run([sys.executable,str(BUILDER),str(edit),'--rendered-preview','../outside.mp4'],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)

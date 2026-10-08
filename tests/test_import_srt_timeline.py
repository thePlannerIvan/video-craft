import importlib.util
import tempfile
import unittest
from pathlib import Path


HELPER = Path(__file__).parents[1] / 'helpers' / 'import_srt_timeline.py'
SPEC = importlib.util.spec_from_file_location('import_srt_timeline_under_test', HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


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

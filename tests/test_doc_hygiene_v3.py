#!/usr/bin/env python3
"""Black-box v3 documentation hygiene & single-source-of-truth guardrails for `video-craft`."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _active_docs() -> dict[str, str]:
    """Return relative-path -> text for active `video-craft` workflow docs."""
    paths = [ROOT / "SKILL.md", ROOT / "README.md"]
    for p in sorted((ROOT / "references").glob("*.md")):
        if p.name == "gotchas-index.md":
            continue
        paths.append(p)
    return {str(p.relative_to(ROOT)): p.read_text(encoding="utf-8") for p in paths if p.is_file()}


class DocHygieneV3Tests(unittest.TestCase):
    def test_no_retired_upstream_or_obsolete_handoff_script(self) -> None:
        docs = _active_docs()
        hits: list[str] = []
        for rel, text in docs.items():
            for token in ("video-idea-system", "check-handoff-artifacts.mjs"):
                if token in text:
                    hits.append(f"{rel}: contains retired `{token}`")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_zombie_density_panel_instructions(self) -> None:
        docs = _active_docs()
        patterns = (
            'phase: "density"',
            "density.jsonl",
            "五档密度",
            "5档密度",
            "5 档密度",
            "五档画面密度",
        )
        hits: list[str] = []
        for rel, text in docs.items():
            for pat in patterns:
                if pat in text:
                    hits.append(f"{rel}: contains zombie density UI instruction `{pat}`")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_retired_three_mode_routing_in_active_docs(self) -> None:
        docs = _active_docs()
        retired_tokens = (
            "pure-talking",
            "footage-montage",
            "keyframe-svg",
            "生产模式",
            "三选一",
        )
        hits: list[str] = []
        for rel, text in docs.items():
            for tok in retired_tokens:
                if tok in text:
                    hits.append(f"{rel}: contains retired mode token `{tok}`")
        # Entry SKILL.md and README.md must not route on legacy `production_mode` field either.
        for entry in ("SKILL.md", "README.md"):
            if "production_mode" in docs[entry]:
                hits.append(f"{entry}: contains legacy `production_mode`")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_authoritative_composable_capabilities_matrix_and_no_duplication(self) -> None:
        docs = _active_docs()
        skill_md = docs["SKILL.md"]
        for required in (
            "剪口播",
            "footage",
            "motion",
            "screen-demo",
            "frame.py",
            "Look-Dev",
            "Voice Polish",
            "Visual Soundscape",
            "storyboard.json",
        ):
            self.assertIn(required, skill_md, f"SKILL.md missing v3 core concept `{required}`")

        # Sub-references should not duplicate the full capabilities selection matrix table.
        row_re = re.compile(r"(?m)^\|.*\|$")
        duplicated: list[str] = []
        for rel, text in docs.items():
            if not rel.startswith("references/"):
                continue
            cap_rows = [
                row for row in row_re.findall(text)
                if sum(1 for cap in ("`footage`", "`motion`", "`screen-demo`") if cap in row) == 1
            ]
            has_footage_row = any("`footage`" in r for r in cap_rows)
            has_motion_row = any("`motion`" in r for r in cap_rows)
            has_demo_row = any("`screen-demo`" in r for r in cap_rows)
            if has_footage_row and has_motion_row and has_demo_row:
                duplicated.append(rel)
        self.assertEqual(
            duplicated,
            [],
            f"Capability matrix table duplicated in references (use single-hop pointer to SKILL.md): {duplicated}",
        )

    def test_no_landscape_pixel_hardcodes_and_frame_single_source(self) -> None:
        docs = _active_docs()
        banned_hardcodes = (
            "1920×1080",
            "1920x1080",
            "0,0,620,1080",
            "0,885,1920,195",
            "620px",
            "0..620",
            "500/620/880",
            'data-speaker-width="608"',
            'data-width="1920"',
            'data-height="1080"',
        )
        hits: list[str] = []
        for rel, text in docs.items():
            for pat in banned_hardcodes:
                if pat in text:
                    hits.append(f"{rel}: contains landscape hardcode `{pat}`")
        self.assertEqual(hits, [], "\n".join(hits))

        for rel in (
            "references/intake-and-frames.md",
            "references/visual-grammar.md",
            "references/visual-checks.md",
            "references/montage-route.md",
            "references/review-and-delivery.md",
        ):
            self.assertIn("frame.py", docs[rel], f"{rel} must point to frame.py as single geometry source")

    def test_tools_and_architecture_accurately_reflect_v3_cli_surface(self) -> None:
        docs = _active_docs()
        for rel in ("references/tools.md", "references/architecture.md"):
            text = docs[rel]
            for marker in (
                "audio_mix.py",
                "sound_design.py",
                "film.py",
                "deliver.py",
                "audio_fix.py",
                "storyboard.json",
                "Look-Dev",
                "Voice Polish",
                "Visual Soundscape",
            ):
                self.assertIn(marker, text, f"{rel} missing v3 CLI/capability marker `{marker}`")

        tools_md = docs["references/tools.md"]
        for marker in ("lookdev", "summary", "import-svg", "make-sfx", "--help"):
            self.assertIn(marker, tools_md, f"references/tools.md missing v3 CLI subcommand/marker `{marker}`")
        self.assertRegex(
            tools_md,
            r"兼容[^\n]*audio_fix\.py",
            "references/tools.md must clearly mark audio_fix.py compatibility role",
        )

    def test_preferences_spec_lint_gotchas_and_lint_skill_zero_reviews(self) -> None:
        prefs = (ROOT / "references" / "preferences.md").read_text(encoding="utf-8")
        for stale in ("片型 `graphic` / `montage`", "片型 graphic / montage", "只对 graphic 生效", "第 11 步"):
            self.assertNotIn(stale, prefs, f"preferences.md still contains stale token: {stale}")
        spec_lint_src = (ROOT / "helpers" / "_internal" / "spec_lint.py").read_text(encoding="utf-8")
        self.assertNotIn("graphic / montage", spec_lint_src)
        gotchas = (ROOT / "GOTCHAS.md").read_text(encoding="utf-8")
        self.assertIn("storyboard.json", gotchas)

        lint_script = ROOT.parents[1] / "06-agent-productivity" / "planning-before-create-skill" / "scripts" / "lint_skill.py"
        proc = subprocess.run([sys.executable, str(lint_script), str(ROOT)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("REVIEW:", proc.stdout + proc.stderr, proc.stdout + proc.stderr)

    def test_evals_cover_v3_capabilities_debreath_sound_design_and_retire_old_modes(self) -> None:
        evals_path = ROOT / "evals" / "evals.json"
        cases = json.loads(evals_path.read_text(encoding="utf-8"))
        blob = "\n".join(
            "\n".join([c.get("prompt", ""), *(c.get("must_do") or [])])
            for c in cases
        )
        for marker in ("storyboard.json", "Look-Dev", "podcast-warm", "--debreath", "sound_design.py", "-14.2..-13.4 LUFS"):
            self.assertIn(marker, blob, f"evals.json missing v3 marker `{marker}`")
        for retired in ("pure-talking", "footage-montage", "keyframe-svg", "生产模式", "三选一"):
            self.assertNotIn(retired, blob, f"evals.json active prompt/must_do contains retired `{retired}`")
        run_evals = ROOT / "evals" / "run_evals.py"
        proc = subprocess.run([sys.executable, str(run_evals)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_style_card_v3_terminology_and_no_bare_leading_words(self) -> None:
        docs = _active_docs()
        bare_re = re.compile(r"(?<!Style\s)Leading\s+Words", re.IGNORECASE)
        hits: list[str] = []
        for rel, text in docs.items():
            if bare_re.search(text):
                hits.append(f"{rel}: contains bare `Leading Words` without `Style Leading Words`")
            for legacy_vault_file in ("craft.md", "page.md", "craft_rules_path", "page_rules_path"):
                if legacy_vault_file in text:
                    hits.append(f"{rel}: contains retired Style Vault token `{legacy_vault_file}`")
        self.assertEqual(hits, [], "\n".join(hits))

        for rel in ("SKILL.md", "references/style-spec.md", "references/preferences.md"):
            self.assertIn("风格领词（Style Leading Words）", docs[rel], f"{rel} missing full term `风格领词（Style Leading Words）`")
        self.assertIn("Single High-Contrast Accent", docs["references/style-spec.md"])


if __name__ == "__main__":
    unittest.main()

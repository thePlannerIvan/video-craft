#!/usr/bin/env python3
"""The published Skill must not carry anyone's credentials or environment.

2026-10-27: a real speech-console App ID had been sitting in
`helpers/transcribe_seedasr.py` as a usage example, and it had already reached
the public GitHub repo. The docs also described the transcription backends in an
order that contradicted GOTCHAS #1 (Ark is not an ASR) and never told a reader
where the credentials live.

These tests freeze both halves of the fix:

1. No shipped file contains a credential literal or a maintainer home path; the
   local `.env` files are the only place a real value may exist.
2. `.env` is gitignored, and `.env.example` is the bring-your-own template with
   the four key names and no values.
3. `SKILL.md` states the preferred **online** service and where the environment
   lives, so a reader never has to infer it from install.md's footnotes.
4. `.env` / `.env.local` exist at the skill root only. An archived or per-branch
   copy is how four real keys (DOUBAO_APP_ID, DOUBAO_ACCESS_TOKEN, ARK_API_KEY,
   ELEVENLABS_API_KEY) reached the Codex / Claude / Antigravity copies on
   2026-11-08: `publish_skills.py` excludes `.venv` but not `.env`, so
   `archive/video-use/.env` shipped verbatim to every runtime.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SELF = Path(__file__).resolve()

TEXT_SUFFIXES = {
    ".md", ".py", ".js", ".mjs", ".json", ".example", ".toml", ".txt",
    ".yml", ".yaml", ".sh", ".html", ".css", ".svg", ".tokens",
}
SKIP_DIRS = {"node_modules", ".git", ".venv", "__pycache__", "transcripts", "edit"}
SKIP_NAMES = {".env", ".env.local"}

# Values that are allowed to follow a key name: empty, a placeholder, or a dot run.
PLACEHOLDER = re.compile(r"^(?:$|<[^>]*>|\.{2,}|x{3,})$")
# A real credential value: plain identifier-ish run, no shell or regex fragments.
SECRET_SHAPED = re.compile(r"^[A-Za-z0-9_.=\-]{6,}$")

CREDENTIAL_RULES = {
    # [ \t] rather than \s: the value must sit on the same line as the key.
    "DOUBAO_APP_ID": re.compile(r"DOUBAO_APP_ID[ \t]*=[ \t]*(\S*)"),
    "DOUBAO_ACCESS_TOKEN": re.compile(r"DOUBAO_ACCESS_TOKEN[ \t]*=[ \t]*(\S*)"),
    "ARK_API_KEY": re.compile(r"ARK_API_KEY[ \t]*=[ \t]*(\S*)"),
    "ELEVENLABS_API_KEY": re.compile(r"ELEVENLABS_API_KEY[ \t]*=[ \t]*(\S*)"),
    "elevenlabs-style key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "bearer token": re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{32,}"),
}
HOME_PATH = re.compile(r"/Users/[A-Za-z0-9._-]+")


def shipped_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve() == SELF:
            continue
        if path.name in SKIP_NAMES or path.name.startswith(".env."):
            if path.name != ".env.example":
                continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        yield path


def stray_env_files(root=ROOT):
    """`.env` / `.env.local` below the skill root. The root copy is the only allowed one."""
    strays = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name not in SKIP_NAMES:
            continue
        rel = path.relative_to(root)
        if len(rel.parts) == 1:
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        strays.append(str(rel))
    return sorted(strays)


class NoShippedCredentials(unittest.TestCase):
    def test_no_credential_literal_in_any_shipped_file(self):
        hits = []
        for path in shipped_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for label, pat in CREDENTIAL_RULES.items():
                for m in pat.finditer(text):
                    value = (m.group(1) if m.groups() else "").strip().strip("'\"")
                    if PLACEHOLDER.match(value) or not SECRET_SHAPED.match(value):
                        continue
                    hits.append(f"{path.relative_to(ROOT)}: {label}")
        self.assertEqual(hits, [], f"shipped files carry credential values: {hits}")

    def test_no_maintainer_home_path(self):
        hits = [str(p.relative_to(ROOT)) for p in shipped_files()
                if HOME_PATH.search(p.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(hits, [], f"machine-specific home paths in shipped docs: {hits}")

    def test_env_files_exist_only_at_the_skill_root(self):
        """凭据只属于本机技能根。归档副本不需要凭据，也不该被发布出去。"""
        self.assertEqual(
            stray_env_files(),
            [],
            "归档副本不需要凭据：.env / .env.local 只允许出现在技能根，"
            f"以下位置出现了副本：{stray_env_files()}",
        )

    def test_the_env_location_rule_catches_a_nested_copy(self):
        """The check above is only worth having if it fires; prove it on a fake tree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("ARK_API_KEY=root-is-fine\n", encoding="utf-8")
            (root / "archive" / "video-use").mkdir(parents=True)
            (root / "archive" / "video-use" / ".env").write_text("ARK_API_KEY=oops\n", encoding="utf-8")
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "node_modules" / "pkg" / ".env").write_text("deps are not ours\n", encoding="utf-8")
            self.assertEqual(stray_env_files(root), [str(Path("archive") / "video-use" / ".env")])
            (root / "archive" / "video-use" / ".env").unlink()
            self.assertEqual(stray_env_files(root), [])


class BringYourOwnTranscription(unittest.TestCase):
    def test_env_is_gitignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertRegex(ignore, r"(?m)^\.env$")
        self.assertIn("!.env.example", ignore)

    def test_env_example_lists_the_keys_without_values(self):
        template = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in ("DOUBAO_APP_ID", "DOUBAO_ACCESS_TOKEN", "ELEVENLABS_API_KEY", "ARK_API_KEY"):
            m = re.search(rf"(?m)^{key}=(.*)$", template)
            self.assertIsNotNone(m, f".env.example is missing {key}")
            self.assertEqual(m.group(1).strip(), "", f".env.example must ship {key} empty")
        self.assertIn("语音技术", template)
        self.assertIn("NOT the 火山方舟", template)


class SkillMdStatesTheServiceAndTheEnvironment(unittest.TestCase):
    def setUp(self):
        self.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.install = (ROOT / "install.md").read_text(encoding="utf-8")

    def test_skill_md_prefers_the_online_service(self):
        self.assertIn("优先用在线转录服务", self.skill)
        self.assertIn("transcribe_seedasr.py", self.skill)
        self.assertIn("SeedASR", self.skill)

    def test_skill_md_says_where_the_environment_lives(self):
        self.assertIn("仓库根的 `.env`", self.skill)
        for key in ("DOUBAO_APP_ID", "DOUBAO_ACCESS_TOKEN", "ELEVENLABS_API_KEY", "ARK_API_KEY"):
            self.assertIn(key, self.skill)
        self.assertIn("npm install ws", self.skill)

    def test_install_md_orders_seedasr_before_scribe_and_flags_ark(self):
        seedasr = self.install.index("SeedASR 2.0 (online")
        scribe = self.install.index("Scribe (ElevenLabs, `transcribe.py")
        ark = self.install.index("Ark (`--backend ark`")
        self.assertLess(seedasr, scribe)
        self.assertLess(scribe, ark)
        self.assertIn("not an ASR", self.install)


if __name__ == "__main__":
    unittest.main()

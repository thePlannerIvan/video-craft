---
name: video-craft-install
description: Install video-craft into the current agent (Claude Code, Codex, Antigravity, DSH, etc.) and wire up ffmpeg + the transcription keys so the user can start editing immediately.
---

# video-craft install

Use this file only for first-time install or reconnect. For daily editing, read `SKILL.md`. Always read `helpers/` — that's where the scripts live.

## What you're doing

You're setting up a conversation-driven video editor for the user. After install, the user drops raw footage into any folder, runs their agent (`claude`, `codex`, etc.) there, and says "edit these into a launch video." You do the rest by reading `SKILL.md`.

A round ends at a **playable review page in the side panel plus a to-do list — not a rendered film.**
`edit/_engineering/` holds review material (engineering state, re-renderable, not a deliverable);
`成品/` is the deliverable and is written only on the author's explicit "render it" instruction,
after a human submission covers the current review snapshot.

Three things must exist on this machine:

1. The `video-craft` skill directory, at a stable path.
2. `ffmpeg` on `$PATH` (plus optional `yt-dlp` for online sources).
3. A transcription service of the user's own: online preferred — `DOUBAO_APP_ID` + `DOUBAO_ACCESS_TOKEN` for 豆包流式语音识别 2.0 (SeedASR) in `.env`. Optional alternatives: `ELEVENLABS_API_KEY` (Scribe, cross-check) or the local mlx-whisper extra. **The repo ships no credentials**; without any, transcription cannot run — see step 5.

And one thing must be true about the current agent:

4. It can discover `SKILL.md` — either via a global skills directory (`~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/config/skills/`, `~/.dsh/skills/`) or via a `CLAUDE.md` / system-prompt import.

## Install prompt contract

- Do everything yourself. Only ask the user for things you cannot generate — **their own** transcription-service credentials, and confirmation before `brew install`. A credential goes into `<skill>/.env` only: never into a document, an example, a chat reply, a runtime copy checked into git, or a commit.
- Runtime skill directories have exactly one owner, and it depends on who you are. A **standalone user** installs with the Skills CLI; the runtime copy it writes **is** the install, because there is no library checkout to drift from. A **monorepo developer** syncs with `publish_skills.py` and never hand-copies or hand-links the Codex / Claude Code / Antigravity directories. Don't mix the two tracks, and don't create a second copy in either.
- DSH is always a link, not a copy: `~/.dsh/skills/video-craft` points at the source directory you actually edit, so changes take effect immediately.
- The skill references helpers by bare name (`transcribe.py`, `render.py`). That works because SKILL.md and `helpers/` ship together — keep them as siblings when you register the skill.
- After install, verify by running one real command against one real file. Don't declare success on file-existence checks alone.

## Steps

### 1. Put the skill on a stable path (pick your track)

**Track A · standalone (installed from GitHub) — one way only**

```bash
npx skills add https://github.com/thePlannerIvan/video-craft --skill video-craft
```

It prints where it wrote the skill. For a standalone user that runtime directory
(`~/.claude/skills/video-craft` or `~/.codex/skills/video-craft`) **is the install**:
there is no `02-skills-library` checkout here, so nothing can drift from a source.
Re-run the same command to update. Then point `CRAFT_SRC` at that directory:

```bash
CRAFT_SRC="${CRAFT_SRC:-$HOME/.claude/skills/video-craft}"
CATEGORY_PY="${CATEGORY_PY:-python3}"
```

**Track B · monorepo checkout**

```bash
# The canonical source is your skills library; nothing here assumes a machine layout.
CRAFT_SRC="${CRAFT_SRC:-$HOME/skills/02-skills-library/03-design-delivery/video-craft}"
# The interpreter this whole category shares (see step 2).
CATEGORY_PY="${CATEGORY_PY:-$HOME/skills/02-skills-library/.venv/bin/python}"
```

If the repo is already there, `git pull --ff-only` and continue.

Both tracks — fail with the exact fix rather than continuing on a path that is not there:

```bash
[ -d "$CRAFT_SRC" ] || { echo "CRAFT_SRC not found: $CRAFT_SRC" >&2; echo "  fix: CRAFT_SRC=<the video-craft directory>" >&2; exit 1; }
command -v "$CATEGORY_PY" >/dev/null || { echo "CATEGORY_PY not executable: $CATEGORY_PY" >&2; echo "  fix: CATEGORY_PY=<python 3.9+>" >&2; exit 1; }
cd "$CRAFT_SRC"
```

### 2. Python

**Track A (standalone):** use any Python 3.9+ you already have (`python3`). This Skill's
own deps are listed in `pyproject.toml` (`requests`, `librosa`, `matplotlib`, `pillow`,
`numpy`); install them into that interpreter if a helper asks for one:

```bash
"$CATEGORY_PY" -V                     # must be 3.9+
"$CATEGORY_PY" -m pip install -e "$CRAFT_SRC"
```

**Track B (monorepo):** there is nothing to create — the category shares one interpreter:

```bash
"$CATEGORY_PY" -V                     # Python 3.9.6
```

It is a `--system-site-packages` venv built from `/usr/bin/python3`, offline-ready,
and it already carries `pptx` / `lxml` / `PIL` / `playwright` / `numpy`. Run helpers
and tests with it: `"$CATEGORY_PY" helpers/render.py ...`. Install this Skill's deps
into it the same way: `"$CATEGORY_PY" -m pip install -e .`.

### 3. Install ffmpeg (+ optional yt-dlp)

`ffmpeg` and `ffprobe` are hard requirements. `yt-dlp` is only needed if the user wants to pull sources from URLs. Animation engines such as HyperFrames, Remotion, and Manim are installed lazily the first time a project actually needs them.

```bash
# macOS
command -v ffmpeg >/dev/null || brew install ffmpeg
command -v yt-dlp >/dev/null || brew install yt-dlp     # optional

# Debian / Ubuntu
# sudo apt-get update && sudo apt-get install -y ffmpeg
# pip install yt-dlp

# Arch
# sudo pacman -S ffmpeg yt-dlp
```

If `brew` / `apt` / `pacman` requires a sudo prompt, tell the user the exact command and wait. Do not invent a password.

### 4. Register the skill with the current agent

**Track A (standalone):** the Skills CLI already wrote the Claude Code / Codex copies it
detected — that is the registration, and it is legitimate because that copy *is* the
install. Two more platforms are links, not extra copies:

- **Antigravity** — symlink to the Claude copy, the same shape the library publisher uses:

    ```bash
    mkdir -p ~/.gemini/config/skills
    ln -sfn ~/.claude/skills/video-craft ~/.gemini/config/skills/video-craft
    ```

    If you only run Codex, point it at `~/.codex/skills/video-craft` instead.

- **DSH** — link the directory you actually run and edit; changes take effect immediately,
  no runtime copy is published:

    ```bash
    mkdir -p ~/.dsh/skills
    ln -sfn "$CRAFT_SRC" ~/.dsh/skills/video-craft
    ```

**Track B (monorepo):** `publish_skills.py` is the only runtime entry point:

```bash
cd "$(dirname "$(dirname "$CRAFT_SRC")")"   # → 02-skills-library
python3 publish_skills.py --dry-run
python3 publish_skills.py --target all
```

It writes the Codex and Claude Code copies and points Antigravity at the Claude copy.
Do **not** hand-copy or hand-link those three directories here — that is exactly the drift
the publisher exists to prevent. DSH still uses a link to the source you edit:

```bash
mkdir -p ~/.dsh/skills
ln -sfn "$CRAFT_SRC" ~/.dsh/skills/video-craft
```

**Another agent (Hermes / Openclaw / …):** use that agent's own installer if it has one.
Otherwise register the whole directory (`SKILL.md` + `helpers/` as siblings) the way that
agent expects, or add a `CLAUDE.md`-equivalent import pointing at `"$CRAFT_SRC"/SKILL.md`.
In Track B, the three directories the publisher owns (Codex / Claude Code / Antigravity)
still go through `publish_skills.py`; for an agent it doesn't cover, register it once and
treat that as the agent's own install — never copy it into the publisher-owned three.

If you can't tell which agent you're in, ask the user once: "which agent am I running under
— Claude Code, Codex, Antigravity, DSH, or something else?" Then pick the right target.

### 5. Transcription: an online service is the default

Word-level timing is the spine of cutting, captions, and delivery, so the default backend is an **online transcription service**: 豆包流式语音识别 2.0 (SeedASR SAUC, `volc.seedasr.sauc.duration`), driven by `helpers/transcribe_seedasr.py`. It returns per-word millisecond timestamps and does not invent words in silence. Read `GOTCHAS.md` #1 before choosing anything else.

| # | backend | credentials / runtime | role |
|---|---|---|---|
| 1 | **SeedASR 2.0 (online, `transcribe_seedasr.py`)** | `DOUBAO_APP_ID` + `DOUBAO_ACCESS_TOKEN` in `.env` — 火山引擎 **语音技术** console, old-style AppID/token pair — plus Node 22 and `ws` in the copy you run | **preferred**: the word-level source |
| 2 | Scribe (ElevenLabs, `transcribe.py --backend scribe`) | `ELEVENLABS_API_KEY` | optional second engine for cross-checking (its tokens merge — GOTCHAS #2) |
| 3 | mlx-whisper (local, `mlx_transcribe.py`) | `pip install -e '.[mlx]'` | offline last resort |
| — | Ark (`--backend ark`, doubao-seed-2.0-lite) | `ARK_API_KEY` (火山方舟 console) | **not an ASR**: a generic multimodal model that drifts 0.5–2 s, garbles fast Chinese, and hallucinates in silence. Never use it for word-level timing |

`transcribe.py --backend auto` still walks Scribe → Ark → mlx; that order is a legacy implementation detail, **not** a recommendation. Word-level transcription always goes through `transcribe_seedasr.py`. The SeedASR pair and the Ark key are **different accounts** — an Ark key cannot stand in for the speech-console pair.

Check what the user already has before asking for anything:

```bash
# a) already exported?
[ -n "$DOUBAO_APP_ID" ] && echo "seedasr app id env"
[ -n "$DOUBAO_ACCESS_TOKEN" ] && echo "seedasr token env"
# b) .env at the skill root?
grep -qE '^DOUBAO_APP_ID=.+' "$CRAFT_SRC"/.env 2>/dev/null && echo "seedasr app id dotenv"
grep -qE '^DOUBAO_ACCESS_TOKEN=.+' "$CRAFT_SRC"/.env 2>/dev/null && echo "seedasr token dotenv"
# c) the WebSocket bridge resolves from the copy you actually run
(cd "$CRAFT_SRC" && node -e "require.resolve('ws')") 2>/dev/null && echo "ws OK" \
  || echo "ws missing: cd $CRAFT_SRC && npm install ws"
```

If the pair is missing, ask the user once for **their own** speech-console credentials (they must open the 语音技术 console and enable 流式语音识别 themselves — you cannot generate one), and write only the missing keys rather than clobbering the file:

```bash
touch "$CRAFT_SRC"/.env && chmod 600 "$CRAFT_SRC"/.env
grep -q '^DOUBAO_APP_ID=' "$CRAFT_SRC"/.env \
  || printf 'DOUBAO_APP_ID=%s\n' "$DOUBAO_APP_ID" >> "$CRAFT_SRC"/.env
grep -q '^DOUBAO_ACCESS_TOKEN=' "$CRAFT_SRC"/.env \
  || printf 'DOUBAO_ACCESS_TOKEN=%s\n' "$DOUBAO_ACCESS_TOKEN" >> "$CRAFT_SRC"/.env
```

Rules that make this safe to publish:

- Never echo a credential in tool output, a document, an example, or a commit. `.env` is gitignored — keep it that way, and never put a credential in a user's footage directory.
- Each runtime copy reads its **own** `.env` — fill the copy you actually run from (`~/.codex/skills/video-craft`, `~/.claude/skills/video-craft`, or the library source).
- No transcript without a credential: if the user has none, say so and stop. Never substitute a generic model and present its output as word-level timing.
- These docs and `.env.example` carry placeholders only. Publishing this Skill publishes the service choice and the key names — not anyone's account.

Optional second engine (only if the user supplies that key too):

```bash
# ElevenLabs: ask for a model list with the key. 200 = usable.
# (`/v1/user` is NOT a valid probe any more — it returns 401 even for a
#  working key, which sent a previous install down a wrong path.)
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "xi-api-key: $(sed -n 's/^ELEVENLABS_API_KEY=//p' "$CRAFT_SRC"/.env)" \
  https://api.elevenlabs.io/v1/models
```

`200` for ElevenLabs means the key is usable. `401` means wrong/expired key — ask once more and stop. Anything else (network, 5xx), move on and verify during first real transcription.

There is no credit-free handshake probe for SeedASR: the honest check is one 2–5 s clip through `transcribe_seedasr.py`, and it bills a call — run it only when the user asks, not during routine install.

To enable the local mlx fallback (only when the user wants an offline path):

```bash
"$CATEGORY_PY" -m pip install -e "$CRAFT_SRC[mlx]"   # installs mlx-whisper
```

### 6. Verify end-to-end

Run one real thing. Prefer the lightest verification that still proves the pipeline is wired up:

```bash
"$CATEGORY_PY" "$CRAFT_SRC"/helpers/timeline_view.py --help >/dev/null && echo "helpers OK"
ffprobe -version | head -1
```

Full transcription test is optional at install time — SeedASR and Scribe both bill per call. Better to wait until the user hands you their first clip.

### 7. Hand off

Tell the user, in one short message:

- Where the skill is installed (`$CRAFT_SRC`; Track A: the runtime directory the Skills CLI wrote; Track B: the library source plus the publisher's copies/symlinks).
- That they should `cd` into their footage folder and start their agent there (e.g. `claude`).
- That a good first message is: *"edit these into a launch video"* or *"inventory these takes and propose a strategy."*
- That a round ends at a **playable review page in the side panel plus a to-do list**, not a film: outputs land in `<videos_dir>/edit/` (review material, including `edit/_engineering/`), while `成品/` is the deliverable and only gets written on their explicit "render it" instruction after a human submission covers the current snapshot. The skill repo stays clean.

## Keeping the skill current

- **Track A:** re-run the Skills CLI command; if it changed the install path, re-run step 4's links. `pyproject.toml` changes → re-run the pip install from step 2.
- **Track B:** update the library checkout and publish — `python3 publish_skills.py --target all` from `02-skills-library`; the copies and the Antigravity symlink pick it up. DSH links to the source and needs nothing. `pyproject.toml` changes → re-run `"$CATEGORY_PY" -m pip install -e "$CRAFT_SRC"` after pulling.

## Cold-start reminders

- Register the **whole directory**, not just `SKILL.md`. The helpers need to sit next to it. In Track B that means the publisher, not a hand-copied duplicate.
- If `.env` exists but the key is empty, treat it the same as missing — don't assume existence means validity.
- `ffmpeg` from static builds works fine. Any modern (≥ 4.x) build is enough for the cut/render path, **but check for libass before promising burned subtitles**: `ffmpeg -filters | grep -c subtitles` must be ≥ 1. Homebrew's default `ffmpeg` on this machine ships WITHOUT `--enable-libass`, so the `subtitles`/`ass` filters do not exist and `render.py` without `--no-subtitles` fails with "No such filter: 'subtitles'". The independent-SRT delivery path (`--no-subtitles` + `srt_export.py`) is unaffected — and is the recommended Chinese-caption path anyway. If burned subtitles are truly required, install a libass-enabled build (`brew install ffmpeg --with-libass` on older formulae, or a static gpl build that includes libass).
- `yt-dlp` is optional. Don't block install on it; install lazily the first time a user asks to pull from a URL.
- Node.js/npm are needed for HyperFrames/Remotion slots (Node 22+) AND for the preferred transcriber: `transcribe_seedasr.py` bridges to the 豆包 streaming API through `helpers/doubao_asr_file.js` over WebSocket, which needs `ws` installed in the repo (not just "somewhere on the machine"):

  ```bash
  cd "$CRAFT_SRC" && npm install ws   # Node 22+
  ```

  Without it the WebSocket bridge fails immediately. This bit a real install:
  three synced copies of the skill existed, only one had `node_modules/ws`, and
  the run had to borrow it via `NODE_PATH`. Install it in whatever copy you
  actually run from.
- The preferred SeedASR backend needs a speech-console `DOUBAO_APP_ID` + `DOUBAO_ACCESS_TOKEN` pair in `.env` (an Ark LLM key is a different account and will not work; the full check list is step 5).
- HyperFrames, Remotion, and Manim are optional animation engines. Don't install or prefer one globally during setup; pick the engine per animation slot in `SKILL.md`. HyperFrames can run through `npx --yes hyperframes ...` **from inside the composition directory** — it reads `index.html` from the current directory, and `hyperframes init` would replace the generated skeleton rather than fix anything. Remotion can be scaffolded with `npx create-video@latest` or installed inside the slot before rendering.
- **HyperFrames needs a writable font cache.** It downloads fonts under the home directory; in a sandbox or on a read-only home the render dies partway with `EPERM: operation not permitted, mkdir '~/.cache/hyperframes/fonts/...'` and only suggests `--docker`. Point it somewhere writable:

  ```bash
  export HYPERFRAMES_FONT_CACHE_DIR="$PWD/.hyperframes-cache"
  ```

  `HYPERFRAMES_FONT_CACHE_DIR` is not in `--help` and **`hyperframes doctor` does not check it**. Run `python3 helpers/check_render_env.py <project>/composition` **before every render** — it fails early on this and on a Node older than 22. It cannot be an npm `prerender` hook: `package.json` is written by `npx hyperframes init`, not by this Skill.
- Never run transcription as part of install verification unless the user explicitly asks — SeedASR and Scribe both bill per call.
- If the user is on Linux without a package manager Claude recognizes, print the manual `ffmpeg` install URL and wait rather than guessing.

### Note on the venv path

**Track B** uses the category interpreter — `02-skills-library/.venv/bin/python`. It is a
`--system-site-packages` venv (Python 3.9.6) shared by every Skill in
`02-skills-library`, installed offline, so nothing has to be created or synced.

**Track A** has no shared category venv: use your own Python 3.9+ (step 2).

`.venv` inside this skill directory is a leftover symlink into `~/dev-cache/...`
(a uv-built 3.14 environment). It is not the convention any more and it is not
what `SKILL.md` tells you to run; leave it alone rather than installing into it.


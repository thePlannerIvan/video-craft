---
name: video-craft-install
description: Install video-craft into the current agent (Codex, Claude Code, etc.) and wire up ffmpeg + the transcription keys so the user can start editing immediately.
---

# video-craft install

Use this file only for first-time install or reconnect. For daily editing, read `SKILL.md`. Always read `helpers/` — that's where the scripts live.

## What you're doing

You're setting up a conversation-driven video editor for the user. After install, the user drops raw footage into any folder, runs their agent (`claude`, `codex`, etc.) there, and says "edit these into a launch video." You do the rest by reading `SKILL.md`.

Three things must exist on this machine:

1. The `video-craft` skill directory, synced to a stable path.
2. `ffmpeg` on `$PATH` (plus optional `yt-dlp` for online sources).
3. At least one transcription key in `.env` at the repo root — `ELEVENLABS_API_KEY` (Scribe) and/or `ARK_API_KEY` (火山方舟 doubao multimodal); without either, transcription falls back to local mlx-whisper (`pip install -e '.[mlx]'`).

And one thing must be true about the current agent:

4. It can discover `SKILL.md` — either via a global skills directory (`~/.claude/skills/`, `~/.codex/skills/`) or via a `CLAUDE.md` / system-prompt import.

## Install prompt contract

- Do everything yourself. Only ask the user for things you cannot generate — the ElevenLabs API key, and confirmation before `brew install`.
- The skill lives in the skills library. Symlink it into each agent's skills
  directory — do not make a second copy, or the three locations drift and
  `manifest.json` version numbers will agree while the contents do not.
- The skill references helpers by bare name (`transcribe.py`, `render.py`). That works because SKILL.md and `helpers/` ship together — keep them as siblings when you register the skill.
- After install, verify by running one real command against one real file. Don't declare success on file-existence checks alone.

## Steps

### 1. Clone to a stable path

```bash
# video-craft is a local, decoupled skill — it is not cloned from an upstream.
# The canonical source lives wherever *you* keep the skills library; nothing here
# assumes a particular machine layout. Override either variable if yours differ.
CRAFT_SRC="${CRAFT_SRC:-$HOME/skills/02-skills-library/03-design-delivery/video-craft}"
# The interpreter this whole category shares (see step 2).
CATEGORY_PY="${CATEGORY_PY:-$HOME/skills/02-skills-library/.venv/bin/python}"
# Fail with the exact fix rather than continuing on a path that is not there.
[ -d "$CRAFT_SRC" ] || { echo "CRAFT_SRC not found: $CRAFT_SRC" >&2; echo "  fix: CRAFT_SRC=<your video-craft checkout>" >&2; exit 1; }
[ -x "$CATEGORY_PY" ] || { echo "CATEGORY_PY not executable: $CATEGORY_PY" >&2; echo "  fix: CATEGORY_PY=<path to the shared category python>" >&2; exit 1; }
cd "$CRAFT_SRC"
```

If the repo is already there, `git pull --ff-only` and continue.

### 2. Python

There is nothing to create — the category shares one interpreter:

```bash
"$CATEGORY_PY" -V                     # Python 3.9.6
```

It is a `--system-site-packages` venv built from `/usr/bin/python3`, offline-ready,
and it already carries `pptx` / `lxml` / `PIL` / `playwright` / `numpy`. Run helpers
and tests with it: `"$CATEGORY_PY" helpers/render.py ...`.

`pyproject.toml` lists this Skill's own deps (`requests`, `librosa`, `matplotlib`,
`pillow`, `numpy`). Install them into that interpreter if a helper asks for one:

```bash
"$CATEGORY_PY" -m pip install -e .
```

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

Figure out which agent you are running under, and register once. A symlink of the whole repo directory is the right shape — helpers/ needs to sit next to SKILL.md.

- **Claude Code** (`~/.claude/` present):

    ```bash
    mkdir -p ~/.claude/skills
    ln -sfn "$CRAFT_SRC" ~/.claude/skills/video-craft
    ```

- **Codex** (`$CODEX_HOME` set, or `~/.codex/` present):

    ```bash
    mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
    ln -sfn "$CRAFT_SRC" "${CODEX_HOME:-$HOME/.codex}/skills/video-craft"
    ```

- **Hermes / Openclaw / another agent with a skills directory**: symlink `"$CRAFT_SRC"` into that agent's skills directory under the name `video-craft`. If the agent has no skills directory, add a line to its system prompt / config pointing at `"$CRAFT_SRC"/SKILL.md` (e.g. an `@"$CRAFT_SRC"/SKILL.md` import in a `CLAUDE.md`-equivalent).

If you can't tell which agent you're in, ask the user once: "which agent am I running under — Claude Code, Codex, or something else?" Then pick the right target.

### 5. Transcription keys

Transcription backends, in `transcribe.py --backend auto` order:

1. **Scribe (ElevenLabs)** — highest quality (word timestamps, diarization, audio events). Needs `ELEVENLABS_API_KEY`.
2. **Ark (火山方舟 multimodal, doubao-seed-2.0-lite)** — hosted fallback when Scribe quota is exhausted. Needs `ARK_API_KEY` (ark.cn-beijing.volces.com). The audio-capable model must be activated in the Ark console first (ModelNotOpen otherwise).
3. **mlx-whisper (local)** — last resort, zero cost, runs on Apple Silicon. Needs `pip install -e '.[mlx]'` in the shared interpreter to install `mlx-whisper`.

Check existing keys in this order and stop at the first hit:

```bash
# a) env vars already exported
[ -n "$ELEVENLABS_API_KEY" ] && echo "elevenlabs env"
[ -n "$ARK_API_KEY" ] && echo "ark env"
# b) .env at repo root already has them
grep -q '^ELEVENLABS_API_KEY=..' "$CRAFT_SRC"/.env 2>/dev/null && echo "elevenlabs dotenv"
grep -q '^ARK_API_KEY=..' "$CRAFT_SRC"/.env 2>/dev/null && echo "ark dotenv"
```

If neither is set, ask the user exactly once for whichever they have. When the user pastes keys, write them to `"$CRAFT_SRC"/.env`:

```bash
printf 'ELEVENLABS_API_KEY=%s\n' "$KEY" > "$CRAFT_SRC"/.env
printf 'ARK_API_KEY=%s\n' "$ARK_KEY" >> "$CRAFT_SRC"/.env
chmod 600 "$CRAFT_SRC"/.env
```

Never echo a key back in tool output. Never commit `.env`.

To enable the local mlx fallback (needed when both hosted keys are absent or exhausted):

```bash
"$CATEGORY_PY" -m pip install -e "$CRAFT_SRC[mlx]"   # installs mlx-whisper
```

Sanity checks that do not burn credits:

```bash
# ElevenLabs: ask for a model list with the key. 200 = usable.
# (`/v1/user` is NOT a valid probe any more — it returns 401 even for a
#  working key, which sent a previous install down a wrong path.)
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "xi-api-key: $(sed -n 's/^ELEVENLABS_API_KEY=//p' "$CRAFT_SRC"/.env)" \
  https://api.elevenlabs.io/v1/models

# Ark: a JSON model list means the key is accepted (per-model access still
# requires activation in the Ark console):
curl -s -H "Authorization: Bearer $(sed -n 's/^ARK_API_KEY=//p' "$CRAFT_SRC"/.env)" \
  https://ark.cn-beijing.volces.com/api/v3/models | head -c 400
```

`200` for ElevenLabs means the key is usable; a JSON list for Ark means the key
is accepted. `401` means wrong/expired key — ask once more and stop. Anything
else (network, 5xx), move on and verify during first real transcription. A
model list only proves the KEY is accepted, not that the account may CALL a
given model — see GOTCHAS #2.

### 6. Verify end-to-end

Run one real thing. Prefer the lightest verification that still proves the pipeline is wired up:

```bash
"$CATEGORY_PY" "$CRAFT_SRC"/helpers/timeline_view.py --help >/dev/null && echo "helpers OK"
ffprobe -version | head -1
```

Full transcription test is optional at install time — it burns Scribe credits. Better to wait until the user hands you their first clip.

### 7. Hand off

Tell the user, in one short message:

- Where the skill is installed (`$CRAFT_SRC`, symlinked into the agent's skills directory).
- That they should `cd` into their footage folder and start their agent there (e.g. `claude`).
- That a good first message is: *"edit these into a launch video"* or *"inventory these takes and propose a strategy."*
- That all outputs land in `<videos_dir>/edit/` — the repo stays clean.

## Keeping the skill current

- video-craft is decoupled from upstream: update it in the skills library and
  commit there. The symlinks pick the change up on the next run.
- If `pyproject.toml` changed deps, re-run `"$CATEGORY_PY" -m pip install -e "$CRAFT_SRC"` after pulling.

## Cold-start reminders

- Symlink the **whole directory**, not just `SKILL.md`. The helpers need to sit next to it.
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
- The SeedASR path also needs a speech-console `DOUBAO_APP_ID` + `DOUBAO_ACCESS_TOKEN` pair in `.env` (an Ark LLM key is a different account and will not work).
- HyperFrames, Remotion, and Manim are optional animation engines. Don't install or prefer one globally during setup; pick the engine per animation slot in `SKILL.md`. HyperFrames can run through `npx --yes hyperframes ...` **from inside the composition directory** — it reads `index.html` from the current directory, and `hyperframes init` would replace the generated skeleton rather than fix anything. Remotion can be scaffolded with `npx create-video@latest` or installed inside the slot before rendering.
- **HyperFrames needs a writable font cache.** It downloads fonts under the home directory; in a sandbox or on a read-only home the render dies partway with `EPERM: operation not permitted, mkdir '~/.cache/hyperframes/fonts/...'` and only suggests `--docker`. Point it somewhere writable:

  ```bash
  export HYPERFRAMES_FONT_CACHE_DIR="$PWD/.hyperframes-cache"
  ```

  `HYPERFRAMES_FONT_CACHE_DIR` is not in `--help` and **`hyperframes doctor` does not check it**. Run `python3 helpers/check_render_env.py <project>/composition` **before every render** — it fails early on this and on a Node older than 22. It cannot be an npm `prerender` hook: `package.json` is written by `npx hyperframes init`, not by this Skill.
- Never run transcription as part of install verification unless the user explicitly asks — Scribe costs real money.
- If the user is on Linux without a package manager Claude recognizes, print the manual `ffmpeg` install URL and wait rather than guessing.

### Note on the venv path

Use the category interpreter — `02-skills-library/.venv/bin/python`. It is a
`--system-site-packages` venv (Python 3.9.6) shared by every Skill in
`02-skills-library`, installed offline, so nothing has to be created or synced.

`.venv` inside this skill directory is a leftover symlink into `~/dev-cache/...`
(a uv-built 3.14 environment). It is not the convention any more and it is not
what `SKILL.md` tells you to run; leave it alone rather than installing into it.


# Upstream absorption record

**Status: decoupled from both upstreams (2026-09-15).** This file exists so that
"are we missing an upstream fix?" is a question with a cheap answer, not a
standing maintenance obligation. Re-check it by hand when you are curious; do not
build a sync process around it.

## video-use — `github.com/browser-use/video-use`

Absorbed through upstream HEAD `9575612` (2026-08-30, "transcribe: select the
audio track, and refuse to upload a silent one (#134)"). The repository has only
21 commits; upstream `SKILL.md` has not changed since `fbcf29f` (2026-05-04).

Three commits were ported on 2026-09-15 because this fork had diverged around
them. All three are now covered by tests in `tests/`.

| Upstream commit | What it fixes | Where it landed here |
|---|---|---|
| **#134** `9575612` | `extract_audio` ran without `-map`, so ffmpeg's default stream selection picked the track with the most channels — on an OBS capture that is the **application audio**, and the narration was uploaded and dropped without a word. Adds `--audio-track`, a `-60 dBFS` silence refusal, and a transcript cache keyed by track. | `helpers/transcribe.py` (`count_audio_tracks`, `peak_dbfs`, `silence_guard`, `transcript_path`, `--audio-track`), `helpers/transcribe_batch.py`. **Extended here:** the same selection and guard apply to the Ark path too, which upstream does not have. |
| **#137** `b5352cf` | Portrait detection read a plain `rotation` metadata tag, which does not guarantee ffmpeg autorotates. Upstream now reads display-matrix side data only. | `helpers/render.py::is_portrait_source` replaced; upstream's 6 tests copied to `tests/test_render_orientation.py`. |
| **#55** `0c40770` | `--fps` was an unvalidated float; a multi-source EDL could resolve a different rate per segment, which breaks the `-c copy` concat. | `helpers/render.py` (`parse_fps`, `probe_source_fps`, one rate resolved per render); upstream's 10 tests copied to `tests/test_render_fps.py`. |

### Deliberate divergences from upstream

- **Credential redaction inside the frozen archive** (security fix, 2026-09-26).
  Upstream `helpers/doubao_asr_file.js` inlined the Doubao App ID and access
  token as string literals (`const APP_KEY = …` / `const ACCESS_KEY = …`). Both
  the live `helpers/doubao_asr_file.js` and the `archive/video-use/` copy now
  read `DOUBAO_APP_ID` / `DOUBAO_ACCESS_TOKEN` from the environment, falling back
  to `<repo>/.env` and failing loudly when neither is present — semantically the
  same path the Python sibling (`transcribe_seedasr.py`) already documented and
  used. This is the **only** deliberate edit inside the otherwise frozen
  `archive/video-use/` copy: shipping a live credential would put it in git
  history permanently, which is far harder to undo than a two-line change. If you
  diff the archive against upstream and these lines are the only difference, that
  is expected and intentional.
- **`normalize_output_rate`** (local addition, 5 tests). Upstream preserves the
  observed `avg_frame_rate` verbatim, which is right for a genuine `30000/1001`.
  It is wrong for a phone whose clock is 0.025 % off: this fork's own footage
  reports `212265000/7073729` against a declared `30/1`, and rendering at that
  rational makes the delivered file advertise a frame rate no platform expects.
  A rate that is not itself a standard broadcast rational, and that sits within
  0.05 % of one, snaps to it.
- **Transcript backends.** Upstream has Scribe only. This fork adds SeedASR 2.0
  (preferred), Ark, and local mlx, with an explicit fallback chain. See
  `GOTCHAS.md` #1 for why SeedASR is the default.
- **Everything else of substance.** Upstream has no `references/`, no
  `srt_export.py`, no article-first caption chain, no `GOTCHAS.md`, no contract
  tests, and no visual layer. `SKILL.md` here is a rewrite, not a patch.

## web-video-presentation — `github.com/ConardLi/garden-skills`

**No upstream to absorb.** The path `skills/web-video-presentation` contains 22
commits and its `manifest.json` never exceeded **1.2.2**; the last content change
was `fa1eece` (2026-05-23, 1.2.1). Its description is a *different skill*:
click-driven 16:9 React presentations that are screen-recorded. The local `2.4.0`
is a self-authored rewrite around SRT-as-time-source and deterministic
HyperFrames rendering, and it was never committed to any repository.

Two things were carried over from upstream's own history, because they were
already in the local copy:

- the 23 themes in `visual/themes/` (byte-identical to upstream; **retired 2026-10-22** with the page route), and
- upstream's habit of pruning: `6ff69f3` deleted `PATTERNS.md` and
  `PRINCIPLES.md` into a single `CHAPTER-CRAFT.md`, and `fe12ba4` cut
  `OUTLINE-FORMAT.md` by 116 lines.

The TTS pipeline that upstream grew in 1.2.1 lives in `archive/legacy-tts/` and is
deliberately out of the active path.

---
name: video-use
description: Edit any video by conversation. Transcribe, cut, color grade, generate overlay animations, burn subtitles — for talking heads, montages, tutorials, travel, interviews. No presets, no menus. Ask questions, confirm the plan, execute, iterate, persist. Production-correctness rules are hard; everything else is artistic freedom.
---

# Video Use

## Principle

1. **LLM reasons from raw transcript + on-demand visuals.** The editor's primary reading view is a packed phrase-level transcript (`takes_packed.md`). For semantic subtitles, the only additional persisted text is the locked article and its line plan; everything else — filler tagging, retake detection, shot classification, emphasis scoring — you derive at decision time.
2. **Audio is primary, visuals follow.** Cut candidates come from speech boundaries and silence gaps. Drill into visuals only at decision points.
3. **Ask → confirm → execute → iterate → persist.** Never touch the cut until the user has confirmed the strategy in plain English.
4. **Generalize.** Do not assume what kind of video this is. Look at the material, ask the user, then edit.
5. **Artistic freedom is the default.** Every specific value, preset, font, color, duration, pitch structure, and technique in this document is a *worked example* from one proven video — not a mandate. Read them to understand what's possible and why each worked. Then make your own taste calls based on what the material actually is and what the user actually wants. **The only things you MUST do are in the Hard Rules section below.** Everything else is yours.
6. **Invent freely.** If the material calls for a technique not described here — split-screen, picture-in-picture, lower-third identity cards, reaction cuts, speed ramps, freeze frames, crossfades, match cuts, L-cuts, J-cuts, speed ramps over breath, whatever — build it. The helpers are ffmpeg and PIL. They can do anything the format supports. Do not wait for permission.
7. **Verify your own output before showing it to the user.** If you wouldn't ship it, don't present it.

## Hard Rules (production correctness — non-negotiable)

These are the things where deviation produces silent failures or broken output. They are not taste, they are correctness. Memorize them.

1. **Subtitles are applied LAST in the filter chain**, after every overlay. Otherwise overlays hide captions. Silent failure.
2. **Per-segment extract → lossless `-c copy` concat**, not single-pass filtergraph. Otherwise you double-encode every segment when overlays are added.
3. **Short audio fades at every segment boundary** (10ms — tuned down from 30ms after the fade measurably swallowed the last word of a cut; 10–30ms window, tighter when the final syllable matters). Otherwise audible pops at every cut.
4. **Overlays use `setpts=PTS-STARTPTS+T/TB`** to shift the overlay's frame 0 to its window start. Otherwise you see the middle of the animation during the overlay window.
5. **Output-timeline SRT uses segment offsets**: `output_time = word.start - segment_start + segment_offset`. Otherwise captions misalign after segment concat.
6. **Never cut inside a word.** Snap every cut edge to a word boundary from the Scribe transcript.
7. **Pad every cut edge.** Working window: 30–200ms. Scribe timestamps drift 50–100ms — padding absorbs the drift. Tighter for fast-paced, looser for cinematic.
8. **Word-level verbatim ASR only.** Never SRT/phrase mode (loses sub-second gap data). Never normalized fillers (loses editorial signal).
9. **Cache transcripts per source.** Never re-transcribe unless the source file itself changed.
10. **Parallel sub-agents for multiple animations.** Never sequential. Spawn N at once via the `Agent` tool; total wall time ≈ slowest one.
11. **Strategy confirmation before execution.** Never touch the cut until the user has approved the plain-English plan.
12. **Working session outputs stay in `<videos_dir>/edit/`; final deliverables are copied out to `<videos_dir>/成品/`.** Never write inside the `video-use/` project directory.
13. **Multi-camera offsets are measured, not guessed — and the sign is defined.** `measure_offset.py <screen> <face>` prints `offset = face_time − screen_time`; pass that value *verbatim* to `mirror_edl.py --offset` (mirror_edl ADDS it). A sign slip silently misaligns the alternate camera by ~2× the offset — verify with the printed anchors (last-speech alignment + optional `--anchors`) and with `verify_av.py --pair <face> <base>` after rendering. Both must agree within 0.3s.
14. **The render timeline is the only source of truth for caption timing.** `render.py` records each segment's MEASURED duration plus the sha256 of the EDL it rendered in `segment_durations.json`; `srt_export.py` builds cue offsets from those measured durations and refuses a render that no longer matches the EDL. Never assume the rendered timeline equals the EDL's nominal Σ(end−start) — frame-grid rounding added a full second over 38 segments in one delivery, and every caption check still passed. Segment caches are content-keyed (`clips_<tag>/manifest.json`), so an EDL/grade/style change re-extracts automatically; `--no-cache` forces it.
15. **Verify A/V before delivering.** After the final render run `verify_av.py --all <videos>` plus `--pair <face> <base>` for multi-camera: track deltas ≤ 0.05s, tail not silently trimmed, pair lag ≈ 0 with corr ≥ 0.5. Fix → re-render → re-verify rather than handing over drifted audio.
16. **Article-first subtitles are a hard gate for semantic Chinese captions and independent SRT delivery.** Lock the complete article before semantic line splitting; match lines to kept words only once; never patch a generated SRT while its text is changing. Use `srt_export.py --prepare`, `--lock`, `--build`, then `--check`. The implicit transcript-to-SRT path is disabled; legacy grouping requires an explicit legacy switch.
17. **A semantic line break must follow speech meaning, not the character counter.** Break Chinese captions at punctuation, clause boundaries or natural breath points; never leave a stranded function word, split a fixed phrase, or create a line that sounds broken when read aloud. The 20-character ceiling is a safety limit, not the primary grouping rule.
18. **Requested pause control belongs to the cut, not to subtitle timing.** When the user specifies a target pause (for this project, about 0.5s), trim excess silence while preserving the speech boundary and re-render the output timeline; do not shift subtitle cues by hand to make the pause look right. The budget is enforced mechanically by `check_edl.py --max-pause`, which must pass before the render.
19. **There may be multiple valid-looking SRT files in a project.** Treat the article-locked, `--check`-passing `edit/subtitles.srt` as the source for delivery, copy it to `成品/`, then compare the copied file byte-for-byte before presenting it. Never assume an older `成品/subtitles.srt` is current.
20. **A successful render is not a delivery check.** Validate every delivered video with `ffprobe` and `verify_av.py --all`; inspect the first, middle and final frames of the rendered output, not only the source or browser preview. If the animation is a separate handoff, verify its resolution, duration and audio stream independently.

Everything else in this document is a worked example. Deviate whenever the material calls for it.

21. **Every scripted deletion states the text it expects to remove.** Address words by TIME + TEXT (`edl_edit.py --delete "455.88,459.76=期望文本|理由"`), never by index: a filtered word index and the raw transcript index differ by the spacing tokens between them, and mixing them silently deleted 18 wrong words in one session. The helper refuses to write when the text does not match; `apply_selection.py` (the word-review path) is the other sanctioned entry point.
22. **A cut edge belongs on a phrase boundary, not merely on a word boundary.** Deleting a duplicated token INSIDE a phrase leaves an audible seam and forces a caption cue to break mid-phrase. Cut in the EDL only when the token sits at a phrase edge; for a disfluency inside a phrase (a doubled 会/这/但, or an ASR token split like “我想想要”), keep the audio whole and drop the token in the caption layer via an explicit `caption_corrections.json` entry with a reason.
23. **Delivery is verified on the rendered file, not declared.** Before handing anything over run `check_edl.py` (cut/pause/render-agreement), `verify_av.py --all` (A/V tracks and tail) and `verify_delivery.py <edit_dir> --deliver-dir <成品>` (SRT↔render sync, silence budget, first/middle/last frames, byte-identical delivery copies). A green caption check is not a delivery check.

## Directory layout

The skill lives in `video-use/`. User footage lives wherever they put it. All session outputs go into `<videos_dir>/edit/`.

```
<videos_dir>/
├── <source files, untouched>
└── edit/
    ├── project.md               ← memory; appended every session
    ├── takes_packed.md          ← phrase-level transcripts, the LLM's primary reading view
    ├── edl.json                 ← cut decisions
    ├── edl.previous.json        ← one step back (rolling; not a timestamped trail)
    ├── segment_durations.json   ← MEASURED per-segment durations + the EDL hash they belong to
    ├── clips_<tag>/manifest.json ← cache content keys (safe to delete)
    ├── selections.json          ← saved word-review feedback (auto-backed up before every save)
    ├── selections.backup-*.json ← immutable feedback versions
    ├── transcripts/<name>.json  ← cached raw Scribe JSON
    ├── animations/slot_<id>/    ← per-animation source + render + reasoning
    ├── clips_graded/            ← per-segment extracts with grade + fades
    ├── caption_words.json       ← EDL-bound word timeline + input hashes for subtitle matching
    ├── caption_corrections.json ← explicit, reasoned ASR/filler corrections only
    ├── captions_article.txt     ← one complete, reviewed article; sole wording source
    ├── .cleanup-approved        ← Stage 12: this project's cleanup was confirmed once
    ├── semantic_lines.txt       ← one-pass semantic line plan, blank blocks preserve EDL segments
    ├── caption_lock.json         ← article/EDL/transcript hashes proving the text is locked
    ├── captions.json            ← generated cue metadata (not hand-edited)
    ├── subtitles.srt            ← generated output-timeline SRT
    ├── master.srt               ← legacy burned-subtitle timeline, if explicitly requested
    ├── downloads/               ← yt-dlp outputs
    ├── verify/                  ← debug frames / timeline PNGs
    ├── edl_preview.html         ← timeline preview + 逐字审阅 (generated by edl_preview_build.py)
    ├── preview.mp4
    └── final.mp4
```

Final deliverables are copied OUTSIDE `edit/` to `<videos_dir>/成品/` (or the user-specified delivery folder). `edit/` stays a working directory; never hand `edit/` files as the final cut.

## Setup

First-time install lives in `install.md` (clone, deps, ffmpeg, skill registration, API key). Don't re-run it every session; on cold start just verify:

- `ELEVENLABS_API_KEY` resolves — either in the environment or in `.env` at the video-use repo root. If missing, ask the user to paste one and write it to `.env` (never to the user's `<videos_dir>`).
- `ffmpeg` + `ffprobe` on PATH.
- Python ≥ 3.10 with deps installed (`uv sync` or `pip install -e .` inside the repo). Helpers run under the repo venv — macOS system `python3` is often 3.9, below the floor; invoke helpers as `.venv/bin/python helpers/<name>.py` or `uv run helpers/<name>.py`, never bare `python3`.
- Node.js + npm available if the session needs HyperFrames or Remotion slots. HyperFrames currently requires Node.js 22+.
- `yt-dlp`, HyperFrames, Remotion, Manim installed only on first use.
- First-use animation setup happens inside the slot directory, never at the video-use repo root. HyperFrames can be invoked with `npx --yes hyperframes ...`; Remotion can be scaffolded with `npx create-video@latest` or installed as a project-local dependency before using its `remotion render` command.
- This skill vendors `skills/manim-video/`. Read its SKILL.md when building a Manim slot.

Helpers (`helpers/transcribe.py`, `helpers/render.py`, etc.) live alongside this SKILL.md. Resolve their paths relative to the directory containing this file — the skill is typically symlinked at `~/.claude/skills/video-use/` or `~/.codex/skills/video-use/`.

## Helpers

- **`transcribe.py <video>`** — single-file transcription. `--backend auto|scribe|ark|mlx` (auto = Scribe → Ark → local mlx; Ark is the hosted doubao multimodal fallback, needs `ARK_API_KEY` in `.env`, model selectable via `ARK_MODEL` env). `--num-speakers N` optional. Cached per source. Note: the Scribe credit pre-check can silently fail (endpoint quirk), so a quota-exhausted upload surfaces as a 401 AFTER upload — auto mode falls back then; it costs one wasted upload, not a hard failure.
- **`transcribe_seedasr.py <video> [--edit-dir <dir>]`** — **preferred backend for word-level transcription.** 豆包流式语音识别 2.0 (SeedASR SAUC, `volc.seedasr.sauc.duration`) over WebSocket `bigmodel_nostream`: clean per-word millisecond timestamps, no garble, no silent-span hallucination. Needs speech-console APP ID + Access Token in `<repo>/.env` and `npm install ws` + Node 22. Use this instead of `--backend ark` — the Ark backend (doubao-seed-2.0-lite) is a generic LLM that garbles fast speech and drifts word times ±0.5-2s (see GOTCHAS.md → “Word-level timing must use SeedASR 2.0”).
- **`mlx_transcribe.py <video> --edit-dir <dir>`** — local Apple-Silicon fallback backend (mlx-whisper large-v3-turbo). Writes Scribe-compatible word JSON (`type: word|spacing` — downstream helpers filter `spacing`). Word timings drift ±0.3s vs Scribe — pad cut edges generously and cross-check with silence detection.
- **`transcribe_batch.py <videos_dir>`** — 4-worker parallel transcription. Use for multi-take.
- **`pack_transcripts.py --edit-dir <dir>`** — `transcripts/*.json` → `takes_packed.md` (phrase-level, break on silence ≥ 0.5s).
- **`measure_offset.py <screen> <face> [--anchors T1 T2 …]`** — multi-camera only: windowed envelope xcorr between the two recordings → **offset = face_time − screen_time** (print directly into `mirror_edl.py --offset`); prints a last-speech anchor plus optional anchor checks. WARNINGS when the offset isn't flat (clock drift) or anchors disagree — do NOT mirror an EDL then. Single-camera projects skip this entirely.
- **`verify_av.py`** — pre-delivery A/V verification: `--tracks` (V/A stream delta ≤ 0.05s), `--tails` (last-loud window; flags a silently trimmed tail — the loudnorm linear tail-trim symptom), `--pair <face> <base>` (envelope xcorr, expect lag ≈ 0 corr ≥ 0.5 — catches wrong mirror offsets). Exit 1 on failure.
- **`timeline_view.py <video> <start> <end>`** — filmstrip + waveform PNG. On-demand visual drill-down. **Not a scan tool** — use it at decision points, not constantly.
- **`render.py <edl.json> -o <out>`** — per-segment extract → guarded concat → overlays (PTS-shifted) → subtitles LAST. Per-segment audio is PCM padded to the *measured* video track (no per-segment AAC drift), the concat duration is guarded against torn segments, and `segment_durations.json` records measured per-segment durations for SRT alignment. Segments are cached per output dir (`clips_<out.stem>`) under a CONTENT key (source identity + range + grade + quality mode + fps, recorded in `clips_<tag>/manifest.json`); a segment is reused only when its key matches, so an EDL/grade/style change can no longer silently reuse it — `--no-cache` forces a rebuild. Quality ladder: `--preview` = 1080p medium CRF 22 (evaluable for QC), `--draft` = 720p ultrafast CRF 28 (cut-point check only). `--build-subtitles` is an explicit legacy master.srt path; do not use it for semantic Chinese captions. `--fps N` overrides output frame rate (default: first source's frame rate); rotated sources render in their display orientation. `--no-loudnorm` skips normalization (loudnorm linear=true TRIMS ~0.5s of the audio tail — measured eating the final word of a deliverable; avoid it when the last word matters, or verify with `verify_av.py --tails`).
- **`grade.py <in> -o <out>`** — ffmpeg filter chain grade. Presets + `--filter '<raw>'` for custom.
- **`edl_preview_build.py <edit_dir>`** — browser timeline preview of the cut (`edit/edl_preview.html`): plays from the best available source (a rendered `final.mp4`/`preview.mp4` when present, otherwise the source clips), scrub the ruler like an NLE, plus the merged **逐字审阅 panel** (click a word = jump & play only; drag = select/deselect a range for deletion — dragging from an already-selected word undoes it; double-click = fix text; save → `selections.json`). **`edl_preview_serve.py <edit_dir> [port]`** — serve it (page URL printed on build). For content/rhythm iteration; grade/overlay/subtitle look still needs a real render.
- **`apply_selection.py <edit_dir>`** — apply the saved `selections.json` to `edl.json`: deletes exactly the selected word/gap intervals, keeps cut edges on word boundaries, backs up the previous EDL, merges only genuinely adjacent intervals (≤ 0.02 s — a wider tolerance silently re-joined deletions of short duplicated tokens) and drops sub-ranges left without a complete word. Run it after every saved word review, then rebuild the preview page and run `check_edl.py`.
- **`edl_edit.py <edit_dir> --delete "S,E=TEXT[|reason]" --restore "S,E=TEXT" --merge-at T`** — scripted EDL surgery for everything that is not the word-review page: it resolves the words inside each interval, asserts their text matches what you claimed, refuses to write on a mismatch, drops speech-less fragments, pulls boundary pauses inside `--max-pause`, and rolls back if the edit would introduce a NEW hard problem. Use this instead of hand-editing `edl.json` or writing a throwaway index-based script.
- **`check_edl.py <edit_dir> [--max-pause 1.0] [--json]`** — the pre-render gate and the edit-side evaluator. HARD failures: a cut inside a word, a pause or in-range silence over budget, `end <= start`, a missing source, an SRT timed on a timeline the render does not have. Warnings: speech-less fragment ranges, missing labels, a stale render hash, EDL-vs-render duration drift. Exit code 1 on any hard failure, so it can gate a render or be run by an evaluator sub-agent.
- **`verify_delivery.py <edit_dir> [--video …] [--deliver-dir 成品] [--max-pause 1.0]`** — run on the RENDERED file: streams and duration vs the rendered timeline, SRT↔render sync, pure-silence budget, first/middle/last frames written out for a human look, and byte-identity (or sampled identity for large media) of every delivery copy.
- **`clean_edit_dir.py <edit_dir> [--approve|--apply]`** — Stage 12 cleanup. Reports the intermediate files (per-segment encodes, concat base, working render, test artefacts, regenerable previews and ad-hoc EDL backups) with sizes and keeps the REBUILDABLE MINIMUM (EDL, review decisions, transcripts, article/line plan/lock, SRT, project memory). First run reports only; `--approve` records the decision in `edit/.cleanup-approved` so later projects clean up by default and just report what was removed.
- **`mirror_edl.py <canonical_edl> -o <angle_edl> --source <name> --path <video> --offset <sec>`** — multi-camera only: derive an alternate camera EDL from the canonical one (same ranges, same speed/mute, source time shifted by a fixed sync offset). `--offset` is **added** to every range (`start + offset`); the offset from `measure_offset.py` goes here verbatim (offset = angle_time − canonical_time). Single-camera projects skip this entirely.
- **`render_cut.py <edl.json> -o <out> [--quality draft|preview|final] [--loudnorm]`** — per-segment extract + concat with support for the EDL's optional `speed`/`mute` fields (accelerated silent spans). Use this when ranges carry `speed`; plain `render.py` remains fine for ordinary cuts.
- **`srt_export.py <edit_dir> --prepare`** — extract the final kept word sequence from cached transcripts + EDL offsets and write `caption_words.json` plus the complete `captions_article.txt`. If `caption_corrections.json` exists, apply only its explicit `drop`/`replace` entries, each of which must name a transcript word and give a reason. Do this before any caption line work. If an article already exists, add `--force-prepare` only after confirming the EDL/transcript/correction map changed.
- **`srt_export.py <edit_dir> --lock`** — verify that the reviewed article still covers the kept word sequence exactly (ignoring punctuation, spacing and case), then write `caption_lock.json`.
- **`srt_export.py <edit_dir> --build`** — match the locked article's `semantic_lines.txt` to contiguous kept words once and write the delivery `subtitles.srt`; this is speed-aware and output-timeline.
- **`srt_export.py <edit_dir> --check`** — fail on stale inputs, omissions, duplicated text, cross-segment cues, word splits, overlaps, timestamp changes or content longer than 20 characters. Do not hand over `master.srt`.
- **`srt_export.py <edit_dir> --legacy-sentence` / `--cue-len MIN-MAX`** — explicit compatibility path for non-semantic or deliberately fast captions only; never use it as the default for a long Chinese talking-head delivery.
- **`audio_diag.py <in> <out_dir>`** — diagnose spoken-word audio quality (muddy/dark/harsh/quiet) and **`audio_fix.py`** — apply the diagnosed voice fix chain with A/B samples at matched loudness. For when the voice needs corrective treatment before cutting.
- **`screen_detect.py <video>`** — detect screen-recorded/UI footage that needs stillimage-style encoding (render.py runs this automatically for final-quality renders).
- **`export_deliverables.py <edit_dir> --out <deliver_dir> --videos a.mp4 b.mp4 --srt x.srt`** — copy final videos + SRT out of `edit/` into the delivery folder (default `<videos_dir>/成品/`).

For animations, create `<edit>/animations/slot_<id>/` with `Bash` and spawn a sub-agent via the `Agent` tool.

## The process

1. **Inventory.** `ffprobe` every source. **Check frame distribution before anything else** — macOS screen recordings are often VFR with multi-second holes (a 10-minute .mov can carry only ~5fps of real frames, and `-ss` input seeking into a hole yields 0-frame segments); run the fps-gap scan (`ffprobe -show_packets` PTS gaps > 1s) and pre-fill VFR sources with a `-vf fps=30` pass, pointing the EDL at the filled file. `transcribe_batch.py` on the directory. `pack_transcripts.py` to produce `takes_packed.md`. Sample one or two `timeline_view`s for a visual first impression.
2. **Pre-scan for problems — transcript quality + content understanding (hard rule, do both before any EDL).** (a) 质检: read the full packed transcript once and check for garbled zones (repeated chars, shuffled order, semantically-reversed clauses) and hallucinated words (words in what should be silence — cross-check with the script when available). Re-transcribe problem zones with `transcribe_seedasr.py` before cutting; never build an EDL on a garbled transcript. (b) 理解: read it as a narrative and note verbal slips, obvious mis-speaks, retakes, and semantic redundancies in a plain list — feed that into the editor brief. Cutting by word without understanding the content is the failure mode to avoid (see GOTCHAS.md → “Transcript quality and content understanding both precede the EDL”).
3. **Converse.** Describe what you see in plain English. Ask questions *shaped by the material*. Collect: content type, target length/aspect, aesthetic/brand direction, pacing feel, must-preserve moments, must-cut moments, animation and grade preferences, subtitle needs. Do not use a fixed checklist — the right questions are different every time.
4. **Propose strategy.** 4–8 sentences: shape, take choices, cut direction, animation plan, grade direction, subtitle style, length estimate. **Wait for confirmation.**
5. **Execute.** Produce `edl.json` via the editor sub-agent brief. **Before rendering, run `check_edl.py <edit_dir>` and fix every hard failure** — it is the machine half of the review gate (cut-inside-word, pause budget, fragment ranges, render agreement). Drill into `timeline_view` at ambiguous moments. Build animations in parallel sub-agents. Apply grade per-segment. Compose via `render.py` (or `render_cut.py` when ranges carry `speed`/`mute`).
6. **User review gate (mandatory — never skip).** After the cut is built, the
   review page is the user's审核载体: they must see WHAT was cut and decide
   what to restore vs. keep deleted, BEFORE any render happens.
   `edl_preview_build.py <edit_dir>` + `edl_preview_serve.py <edit_dir>` build
   a browser page (`edit/edl_preview.html`) that plays the cut **from the
   source clips — no rendering required**, so it must be delivered fast:
   timeline ruler with per-source segment blocks (the deleted spans are the
   gaps), click/drag to scrub like an NLE, play/pause, prev/next cut, 0.25-3x
   speed — plus the 逐字审阅 panel (click a word = jump & play, drag =
   select/deselect for deletion, double-click = text fix, save to
   `selections.json`). Deliver the page URL and tell the user exactly what
   was deleted and why. **Do not render, do not export, until the user has
   reviewed and approved the cut.**
   - **Apply the review.** After the user saves `selections.json`, run
     `apply_selection.py <edit_dir>` to write the deletions into `edl.json`
     (their restore/deletion decisions), then rebuild `edl_preview.html` and
     re-present it. Every save is auto-backed up before it overwrites the
     previous one. Iterate until the user approves.
   - **Multi-camera (optional).** If and only if the project has synchronized
     angles (e.g., selfie + screen), keep ONE canonical EDL and derive each
     other angle with `mirror_edl.py`. **First measure the offset with
     `measure_offset.py <canonical_src> <angle_src> --anchors <3 mid times>`,
     pass its printed value verbatim to `--offset`, and check the anchors all
     agree (flat offset, no clock drift) before rendering.** Do not
     edit camera angles as separate cuts. Single-camera projects skip this.
7. **Preview (final look).** `render.py --preview` or
   `render_cut.py --quality preview` — once the cut is approved in the
   timeline preview, render a preview to check the ffmpeg-side look the
   browser can't show: grade, overlay animations, burned subtitles.
8. **Article-first subtitle review.** When subtitles are requested for a
   Chinese narrative, long talking-head cut, or independent SRT delivery:
   run `srt_export.py <edit_dir> --prepare`, then read the complete
   `captions_article.txt` once. Correct only clear typos, names and obvious
   ASR errors; resolve uncertain hearing from the audio instead of silently
   polishing the script. When the text is stable, split the article from
   start to finish into `semantic_lines.txt`, using a blank block for each
   EDL segment. Run `--lock`, then `--build`, then `--check`. Never generate
   timestamps before the article is locked, and never patch individual SRT
   cues. A text change means rebuild the lock, line plan and SRT as one chain.
   For an explicit non-semantic caption style, use the legacy switch and say
   why the article-first route does not apply.
9. **Self-eval (before showing the user).** Run `timeline_view` on the **rendered output** (not the sources) at every cut boundary (±1.5s window). Check each image for:
   - Visual discontinuity / flash / jump at the cut
   - Waveform spike at the boundary (audio pop that slipped past the fade)
   - Subtitle hidden behind an overlay (Rule 1 violation)
   - Overlay misaligned or showing wrong frames (Rule 4 violation)

   Also sample: first 2s, last 2s, and 2–3 mid-points — check grade consistency, subtitle readability, overall coherence. Run `ffprobe` on the output to verify duration matches the EDL expectation.

   **Automated A/V checks (mandatory before presenting):** `verify_av.py --all <outputs>` and, for multi-camera, `verify_av.py --pair <angle> <canonical>`. This catches what eyes and ears miss: per-segment AAC drift (track delta), a loudnorm-trimmed tail (silent final word), and a wrong mirror offset (pair lag ≠ 0).

   If anything fails: fix → re-render → re-eval. **Cap at 3 self-eval passes** — if issues remain after 3, flag them to the user rather than looping forever. Only present the preview once the self-eval passes.
10. **Iterate + persist.** Natural-language feedback, re-plan, re-render. Never re-transcribe. Final render on confirmation. Append to `project.md`.
    Note the ordering that keeps captions honest: the SRT is built AFTER the render (`--build` refuses when the render is stale), and re-running `--prepare` after a render re-binds the word timeline to the measured durations while keeping your reviewed `semantic_lines.txt`.
11. **Export.** Only after the user approved the cut (step 6). Copy final videos + delivery SRT with
    `export_deliverables.py` to `<videos_dir>/成品/`. Do not leave the final
    deliverables buried inside `edit/`.
12. **Verify and clean up.** Run `verify_delivery.py <edit_dir> --deliver-dir <成品>` on the delivered files (SRT↔render sync, silence budget, frames for a human look, delivery copies byte-identical) and `verify_av.py --all` for the audio tracks and tail. Then offer the cleanup: `clean_edit_dir.py <edit_dir>` prints what it would delete and what it keeps — a finished talking-head project left 2.5 GB of intermediates against a 723 MB delivery. First project: show the list and ask; after that, `--approve` once per project pattern and later runs apply it by default and simply report. Never delete the source media, the delivery folder, the transcripts or the reviewed cut decisions.

## Cut craft (techniques)

- **Audio-first.** Candidate cuts from word boundaries and silence gaps.
- **Preserve peaks.** Laughs, punchlines, emphasis beats. Extend past punchlines to include reactions — the laugh IS the beat.
- **Speaker handoffs** benefit from air between utterances. Common values: 400–600ms. Less for fast-paced, more for cinematic. Taste call.
- **Audio events as signals.** `(laughs)`, `(sighs)`, `(applause)` mark beats. Extend past them.
- **Silence gaps are cut candidates.** The thresholds are three deliberate values, each owned by one tool — do not treat them as interchangeable: the packed transcript breaks a phrase at a gap ≥ 0.5 s (`pack_transcripts.py --silence-threshold`), `timeline_view.py` marks ≥ 0.4 s gaps in the waveform, and a 0.15–0.4 s boundary is usable for a cut after a visual check. Below ~0.15 s it is mid-phrase and unsafe to cut. The user's pause budget (Hard Rule 18) is a separate, stricter number enforced by `check_edl.py --max-pause`.
- **Example cut padding** (the launch video shipped with this): 50ms before the first kept word, 80ms after the last. Tighter for montage energy, looser for documentary. Stay in the 30–200ms working window (Hard Rule 7).
- **Retakes: keep ONLY the last complete version.** When the speaker stumbles, self-corrects ("不对。"), or restarts mid-thought, cut every incomplete attempt and keep the final full sentence. Repeated sentences (the speaker says the same sentence twice) also keep only the second/final occurrence, unless the repetition is clearly emphatic. Watch for the pattern: broken prefix → restart → complete sentence; the first two go.
- **After cutting, delete the blank.** Removing retake spans leaves leftover silence at segment edges and between kept words. Trim intra-segment word gaps >400ms to a ~0.25s breath beat; keep ~2.5s for meaningful waits (PPT generation, rendering, loading screens — the viewer needs to see the wait happened); delete ranges that contain no real speech at all.
- **Never reason audio and video independently.** Every cut must work on both tracks.

## The packed transcript (primary reading view)

`pack_transcripts.py` reads all `transcripts/*.json` and produces one markdown file where each take is a list of phrase-level lines, each prefixed with its `[start-end]` time range. Phrases break on any silence ≥ 0.5s OR speaker change. This is the artifact the editor sub-agent reads to pick cuts — it gives word-boundary precision from text alone at 1/10 the tokens of raw JSON.

Example line:
```
## C0103  (duration: 43.0s, 8 phrases)
  [002.52-005.36] S0 Ninety percent of what a web agent does is completely wasted.
  [006.08-006.74] S0 We fixed this.
```

## Editor sub-agent brief (for multi-take selection)

When the task is "pick the best take of each beat across many clips," spawn a dedicated sub-agent with a brief shaped like this. The structure is load-bearing; the pitch-shape example is not.

```
You are editing a <type> video. Pick the best take of each beat and 
assemble them chronologically by beat, not by source clip order.

INPUTS:
  - takes_packed.md (time-annotated phrase-level transcripts of all takes)
  - Product/narrative context: <2 sentences from the user>
  - Speaker(s): <name, role, delivery style note>
  - Expected structure: <pick an archetype or invent one>
  - Verbal slips to avoid: <list from the pre-scan pass>
  - Target runtime: <seconds>

Common structural archetypes (pick, adapt, or invent):
  - Tech launch / demo:   HOOK → PROBLEM → SOLUTION → BENEFIT → EXAMPLE → CTA
  - Tutorial:             INTRO → SETUP → STEPS → GOTCHAS → RECAP
  - Interview:            (QUESTION → ANSWER → FOLLOWUP) repeat
  - Travel / event:       ARRIVAL → HIGHLIGHTS → QUIET MOMENTS → DEPARTURE
  - Documentary:          THESIS → EVIDENCE → COUNTERPOINT → CONCLUSION
  - Music / performance:  INTRO → VERSE → CHORUS → BRIDGE → OUTRO
  - Or invent your own.

RULES:
  - Start/end times must fall on word boundaries from the transcript.
  - Pad cut boundaries (working window 30–200ms).
  - Prefer silences ≥ 400ms as cut targets.
  - Unavoidable slips are kept if no better take exists. Note them in "reason".
  - If over budget, revise: drop a beat or trim tails. Report total and self-correct.

OUTPUT (JSON array, no prose):
  [{"source": "C0103", "start": 2.42, "end": 6.85, "beat": "HOOK",
    "quote": "...", "reason": "..."}, ...]

Return the final EDL and a one-line total runtime check.
```

## Color grade (when requested)

Your job is to **reason about the image**, not apply a preset. Look at a frame (via `timeline_view`), decide what's wrong, adjust one thing, look again.

Mental model is ASC CDL. Per channel: `out = (in * slope + offset) ** power`, then global saturation. `slope` → highlights, `offset` → shadows, `power` → midtones.

**Example filter chains** (`grade.py` has `--list-presets`; use them as starting points or mix your own):

- **`warm_cinematic`** — retro/technical, subtle teal/orange split, desaturated. Shipped in a real launch video. Safe for talking heads.
- **`neutral_punch`** — minimal corrective: contrast bump + gentle S-curve. No hue shifts.
- **`none`** — straight copy. Default when the user hasn't asked.

For anything else — portraiture, nature, product, music video, documentary — invent your own chain. `grade.py --filter '<raw ffmpeg>'` accepts any filter string.

Hard rules: apply **per-segment during extraction** (not post-concat, which re-encodes twice). Never go aggressive without testing skin tones.

## Subtitles (when requested)

Subtitles have three dimensions worth reasoning about: **chunking** (1/2/3/sentence per line), **case** (UPPER/Title/Natural), and **placement** (margin from bottom). The right combo depends on content.

For semantic Chinese delivery, follow the article-first reference at
`references/caption-article-first.md`: write the complete transcript smoothly
first, then split it by punctuation and meaning, and only then match each line
to the first and last kept word. Keep most cues in the readable 10-18 content
character range, with the hard ceiling below. The final SRT is generated by
the helper and checked against the locked text; it is never the editing source.
Cue TIMES come from the render's measured per-segment durations
(`segment_durations.json`, written by `render.py`), so build the SRT after the
render — `--build` refuses a stale render rather than emitting cues against a
timeline the video does not have.

The line plan is a spoken-language plan, not a fixed-width text layout. Read
the complete Chinese article aloud once before locking `semantic_lines.txt`;
when a candidate break sounds unnatural, move the boundary to the next natural
clause even if that produces a shorter or longer cue within the hard ceiling.

**Line length and word integrity (Chinese caption rule, non-negotiable):**
cues stay ≤ 20 content characters (punctuation not counted), and a cue must
never split a word or protected phrase in the middle (告诉 → "再告 / 诉它一遍",
相关 → "相 / 关经验" are failures). When a run exceeds the cap with no
punctuation to break on, cut at the last phrase-end particle (的/了/在/就/都/来/出…)
within the cap; a 20-character hard cut with no particle is a last resort and
must be reviewed by hand. The builder rejects any boundary that is not a
contiguous kept-word boundary.

Natural-break review is mandatory for Chinese delivery: review the complete
SRT as a sequence, not only one cue at a time. A technically valid cue can
still be rejected when its line break interrupts a noun phrase, leaves a
conjunction at the start or end, or forces a breath at a place the speaker
would not pause.

**Worked styles** — pick, adapt, or invent:

**`bold-overlay`** — short-form tech launch, fast-paced social. 2-word chunks, UPPERCASE, break on punctuation, Helvetica 18 Bold, white-on-outline, `MarginV=90` (a platform safe-zone value — `render.py` ships this as `SUB_FORCE_STYLE`; on a 1080×1920 vertical frame the bottom ~25–30% is covered by platform UI).

```
FontName=Helvetica,FontSize=18,Bold=1,
PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,
BorderStyle=1,Outline=2,Shadow=0,
Alignment=2,MarginV=90
```

**`natural-sentence`** (if you invent this mode) — narrative, documentary, education. 4–7 word chunks, sentence case, break on natural pauses, `MarginV=60–80`, larger font for readability, slightly wider max-width. No shipped force_style — design one if you need it.

Invent a third style if neither fits. Hard rules: subtitles LAST (Rule 1), output-timeline offsets (Rule 5).

## Animations (when requested)

Animations match the content and the brand. **Get the palette, font, and visual language from the conversation** — never assume a default. If the user hasn't told you, propose a palette in the strategy phase and wait for confirmation before building anything.

**Tool options:**

Pick the engine per animation slot. Do not default to Remotion just because the animation is web-adjacent.

- **HyperFrames** — Browser-native HTML/CSS/GSAP video compositions: product UI motion, website-to-video or mockup-to-video captures, kinetic typography, landing-page/storyboard promos, data-driven UI states, transparent WebM overlays, and clips that need deterministic frame capture plus HyperFrames lint/validate/render checks. Best when the animation should be authored and verified like a web composition instead of a React component tree.
- **Remotion** — React/CSS compositions with component state, reusable React primitives, or an existing Remotion brand system. Best when the user specifically asks for React/Remotion or when React composition is the simpler authoring model.
- **Manim** — formal diagrams, state machines, equation derivations, graph morphs. Read `skills/manim-video/SKILL.md` and its references for depth.
- **PIL + PNG sequence + ffmpeg** — simple overlay cards: counters, typewriter text, single bar reveals, progressive draws. Fast to iterate, any aesthetic you want. The launch video used this.

For HyperFrames slots, scaffold the slot inside `edit/animations/slot_<id>/` with `npx --yes hyperframes init . --example blank --non-interactive --skip-skills`, build the HTML composition there, run the HyperFrames checks that fit the slot (`lint`, `validate`, and a draft render when practical), then produce the final overlay video with `npx --yes hyperframes render . -o render.mp4` or `--format webm -o render.webm` when alpha is required. Point the EDL overlay `file` at the actual rendered path.

For Remotion slots, keep the Remotion project isolated inside the same slot directory, scaffold with `npx create-video@latest` or install Remotion locally there, render the composition to `render.mp4` with the project-local `remotion render` command, and verify duration and dimensions with `ffprobe`.

None is mandatory. Invent hybrids if useful (e.g., PIL background with a HyperFrames or Remotion layer on top).

**Duration rules of thumb, context-dependent:**

- **Sync-to-narration explanations.** A viewer needs to parse the content at 1×. Rough floor 3s, typical 5–7s for simple cards, 8–14s for complex diagrams. The launch video shipped at 5–7s per simple card.
- **Beat-synced accents** (music video, fast montage). 0.5–2s is fine — they're visual accents, not information. The "readable at 1×" rule becomes *"recognizable at 1×"*, not *"fully parseable."*
- **Hold the final frame ≥ 1s** before the cut (universal).
- **Over voiceover:** total duration ≥ `narration_length + 1s` (universal).
- **Never parallel-reveal independent elements** — the eye can't track two new things at once. One thing, pause, next thing.

**Animation payoff timing (rule for sync-to-narration):** get the payoff word's timestamp. Start the overlay `reveal_duration` seconds earlier so the landing frame coincides with the spoken payoff word. Without this sync the animation feels disconnected.

**Easing** (universal — never `linear`, it looks robotic):

```python
def ease_out_cubic(t):    return 1 - (1 - t) ** 3
def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t ** 3
    return 1 - (-2 * t + 2) ** 3 / 2
```

`ease_out_cubic` for single reveals (slow landing). `ease_in_out_cubic` for continuous draws.

**Typing text anchor trick:** center on the FULL string's width, not the partial-string width — otherwise text slides left during reveal.

**Example palette** (the launch video — one aesthetic among infinite):
- Background `(10, 10, 10)` near-black
- Accent `#FF5A00` / `(255, 90, 0)` orange
- Labels `(110, 110, 110)` dim gray
- Font: Menlo Bold at `/System/Library/Fonts/Menlo.ttc` (index 1)
- ≤ 2 accent colors, ~40% empty space, minimal chrome
- Result: terminal / retro tech feel

This is one style. If the brand is warm and serif, use that. If it's colorful and playful, use that. If the user handed you a style guide, follow it. If they didn't, propose one and confirm.

**Parallel sub-agent brief** — each animation is one sub-agent spawned via the `Agent` tool. Each prompt is self-contained (sub-agents have no parent context). Include:

1. One-sentence goal: *"Build ONE animation: [spec]. Nothing else."*
2. Absolute output path (`<edit>/animations/slot_<id>/render.mp4`)
3. Exact technical spec: resolution, fps, codec, pix_fmt, CRF, duration
4. Style palette as concrete values (RGB tuples, hex, or reference to a design system)
5. Font path with index
6. Frame-by-frame timeline (what happens when, with easing)
7. Anti-list ("no chrome, no extras, no titles unless specified")
8. Code pattern reference (copy helpers inline, don't import across slots)
9. Deliverable checklist (script, render, verify duration via ffprobe, report)
10. **"Do not ask questions. If anything is ambiguous, pick the most obvious interpretation and proceed."**

One sub-agent = one file (unique filenames, parallel agents don't overwrite each other).

## Output spec

Match the source unless the user asked for something specific. Common targets: `1920×1080@24` cinematic, `1920×1080@30` screen content, `1080×1920@30` vertical social, `3840×2160@24` 4K cinema, `1080×1080@30` square. `render.py` defaults the scale to 1080p from any source; edit the extract command for other targets. Output frame rate follows the first source by default (pass `--fps N` to override; rotation metadata is honored, so rotated phone footage renders vertical, not blown-up landscape). Worth asking the user which delivery format matters.

Final videos and SRT go to `<videos_dir>/成品/` (a sibling of `edit/`), never
only inside `edit/`. Use `export_deliverables.py` to keep working files and
deliverables separated.

## EDL format

```json
{
  "version": 1,
  "sources": {"C0103": "/abs/path/C0103.MP4", "C0108": "/abs/path/C0108.MP4"},
  "ranges": [
    {"source": "C0103", "start": 2.42, "end": 6.85,
     "beat": "HOOK", "quote": "...", "reason": "Cleanest delivery, stops before slip at 38.46."},
    {"source": "C0108", "start": 14.30, "end": 28.90,
     "beat": "SOLUTION", "quote": "...", "reason": "Only take without the false start."}
  ],
  "grade": "warm_cinematic",
  "overlays": [
    {"file": "edit/animations/slot_1/render.mp4", "start_in_output": 0.0, "duration": 5.0}
  ],
  "subtitles": "edit/master.srt",
  "total_duration_s": 87.4
}
```

`grade` is a preset name or raw ffmpeg filter. `overlays` are rendered animation clips. `subtitles` is optional and applied LAST. For an external SRT delivery, omit `subtitles` and render with `--no-subtitles`; export `subtitles.srt` separately.

Ranges may carry optional `speed` (e.g., `12` for accelerated waiting/silence)
and `mute` (true when the accelerated span must be silent). In multi-camera
projects, one canonical EDL drives the cut and alternate angles are derived
with `mirror_edl.py`; single-camera projects do not need this.

## Memory — `project.md`

Append one section per session at `<edit>/project.md`:

```markdown
## Session N — YYYY-MM-DD

**Strategy:** one paragraph describing the approach
**Decisions:** take choices, cuts, grades, animations + why
**Reasoning log:** one-line rationale for non-obvious decisions
**Outstanding:** deferred items
```

On startup, read `project.md` if it exists and summarize the last session in one sentence before asking whether to continue. Read `GOTCHAS.md` at the repo root too — it accumulates session-learned pitfalls (e.g. stale preview server on a fixed port).

## Anti-patterns

Things that consistently fail regardless of style:

- **Hierarchical pre-computed codec formats** with USABILITY / tone tags / shot layers. Over-engineering. Derive from the transcript at decision time.
- **Hand-tuned moment-scoring functions.** The LLM picks better than any heuristic you'll write.
- **Whisper SRT / phrase-level output.** Loses sub-second gap data. Always word-level verbatim.
- **Treating the mlx fallback as first-class.** Local mlx-whisper is the last-resort backend (runs fine on Apple Silicon, keeps fillers verbatim) but its word timings drift ±0.3s and it drops punctuation — usable for cutting, risky for subtitle timing without the manual review pass. Prefer hosted backends (Scribe / Ark) when available.
- **Burning subtitles into base before compositing overlays.** Overlays hide them. (Hard Rule 1.)
- **Single-pass filtergraph when you have overlays.** Double re-encodes. Use per-segment extract → concat.
- **Linear animation easing.** Looks robotic. Always cubic.
- **Hard audio cuts at segment boundaries.** Audible pops. (Hard Rule 3.)
- **Typing text centered on the partial string.** Text slides left as it grows.
- **Sequential sub-agents for multiple animations.** Always parallel.
- **Editing before confirming the strategy.** Never.
- **Re-transcribing cached sources.** Immutable outputs of immutable inputs.
- **Assuming what kind of video it is.** Look first, ask second, edit last.
- **Generating semantic SRT directly from the transcript.** That path loses the reviewed article and lets timing work drive wording. Use the article-first contract; change the EDL or explicit correction map when the text cannot match the kept words.

## This project's Gotchas

- “删掉重复和口误”不等于把所有停顿都剪掉。先按语义判断重复、重启和口误，再把多余静音压到用户要求的目标；保留能帮助理解的短呼吸和句间节奏。
- 字幕自然断句必须在文章锁定后一次完成。不要先生成机械字幕、再逐条手改；任何文字变更都要回到 article → line plan → lock → build → check 的链条。
- `edit/` 是工作区，`成品/` 是交付区。完成剪辑、字幕、动画后，要把用户要求的每一项交付物明确复制到交付区，并在交付区再次核验，而不是只报告工作区文件存在。
- 成片核验要看最终编码后的画面。源视频、review 页面或未封装的 `video-only.mp4` 不能代替最终 MP4 的首帧、中段、尾帧和音画检查。

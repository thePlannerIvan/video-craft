# GOTCHAS

Evidence-backed pitfalls that change future behavior. Read this before starting a
session.

**Policy — solved means deleted.** A gotcha whose failure is now guaranteed
against by a script, a Hard Rule, a stage or a verification step is REMOVED from
this file: the mechanism is the memory, and a second copy in prose only rots.
What stays here is what cannot be internalized — external tool behaviour,
account/API facts, and judgement about how to verify a claim. Add an entry when a
real run produces one, and delete the entry the day the mechanism lands.

## Runtime and transcription

### 1. A stale preview server can serve the wrong project

`edl_preview_serve.py` uses a fixed port by default. A process left over from a
previous session can keep serving its old edit directory while a new server
fails with `Address already in use`. Before serving, inspect and stop the
listener on 8737, then verify the served HTML contains the current video name.
An HTTP 200 alone is not proof that the current project is being served.

### 2. A models-list response does not prove model access

Volcengine's models endpoint can list models that the account cannot call.
Probe the actual endpoint with real audio before wiring a backend. Ark LLM keys
are not speech-console APP keys.

### 3. Word-level timing must come from SeedASR 2.0

The Ark `doubao-seed-2.0-lite` path is a generic multimodal LLM, not a reliable
ASR: it can drift 0.5–2 s, garble fast Chinese and hallucinate words in silence.
Long chunked requests degrade additionally around chunk edges (roughly the first
3 s and the last 5–7 s of each chunk), and no chunk-size tuning removes that.
Use `transcribe_seedasr.py`. Local `mlx_transcribe.py` is the last resort — it
keeps fillers verbatim but drifts ±0.3 s and drops punctuation, so raise the
amount of timing review when you fall back to it.

Two engines disagreeing is a signal, not noise: re-run the window you are about
to cut with a second backend before deleting a token or trusting a proper name.
That is how `关线`→`关键`, `经典`→`经验`, `Chatbox`→`Chatbot` and a doubled
`想` were resolved in one session — and how three "duplicated" tokens turned out
to be a single spoken word that the ASR had split in two.

### 4. Scribe quota pre-checks are advisory

The quota endpoint can report a usable account even when a Scribe upload later
returns 401. Treat the real upload response as authoritative and use an explicit
fallback when Scribe is known to be exhausted.

## Filesystem

### 5. Cloud-synced video folders make ffmpeg fail intermittently

When the footage and `edit/` live on a synced folder (OneDrive/iCloud/Dropbox),
writing a large mp4 in place can stall the muxer: ffmpeg dies with

    Error submitting a packet to the muxer: Operation timed out
    Task finished with error code: -60 (Operation timed out)

exit 196. It is intermittent and it is NOT a code bug — it hit 1 of 7 short demo
clips in one run and none of the 16 full-render segments in another, so "it
worked last time" proves nothing. It also does not reproduce when the same
command is run by hand.

Build in a local temp dir (`tempfile.mkdtemp()`) and copy only the finished
artefact into the project. `clean_edit_dir.py` already keeps the delivery copy
outside `edit/`, so the deliverable is never the file being stalled.

## Verification

### 6. A claim must match the evidence behind it

Say what was directly verified, and by which command; never let a passing check
stand in for a different property. Three gates exist and none implies another:

- `check_edl.py` — the cut is legal (no edge inside a word, pauses inside
  budget, the render agrees with the EDL it came from);
- `verify_av.py` — the rendered file's audio/video tracks and its tail;
- `verify_delivery.py` — the DELIVERED artefacts (SRT↔render sync, silence
  budget, delivery copies identical to the working files).

A green caption contract (`srt_export.py --check`) proves the text, not the
timing. When something could not be checked directly — a two-engine
disagreement, a frame nobody looked at, a colour nobody saw — record that it was
not verified instead of implying it was.

## Removed entries, and where the guarantee lives now

Kept as a subtraction audit trail, so a future session can tell a deliberate
deletion from an accidental loss.

| Removed gotcha | Now guaranteed by |
|---|---|
| Chunked doubao degradation at chunk edges | merged into #3 |
| Transcript quality + content understanding precede the EDL | SKILL.md process step 2 (hard rule) |
| A transcript change invalidates every old EDL boundary | `check_edl.py` cut-inside-word failure |
| Repeated versions are resolved before the EDL | SKILL.md Cut craft + the user review gate |
| Semantic subtitles use one article-first chain | Hard Rule 16 + `references/caption-article-first.md` |
| Segment caches are content-blind | content-keyed cache (`clips_<tag>/manifest.json`) |
| EDL word gaps do not prove rendered pauses are within target | `check_edl.py --max-pause` + `verify_delivery.py` silence scan |
| Transparent overlays / alpha / snapshot pitfalls (6 entries) | moved to the `hyperframes-cli` skill, where that behaviour happens |

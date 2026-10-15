# GOTCHAS

有证据的坑：会稳定导致错误的具体行为。每次开工前读它。

**两条约定。**

1. **每条都写清 `module` 与状态。** 一条 gotcha 一定属于某个 module——优化时按 module 聚类，
   不按发生次数堆规则。状态只有四个：**候选**（有怀疑、还没在真实运行里观察到）·
   **已复现**（真实运行里出现过，且没有机制能兜住它）· **已升级**（后果已有机制兜住，
   剩下的判断住在这里）· **已失效**（不再成立）。加一条之前，先有一次真实运行产生它。

2. **解决了就删。** 一条候选被机制完全接管后，在末尾「已移除的条目」表里留一行指向那个机制，
   然后从正文删掉——机制才是记忆，正文里的第二份 prose 只会烂掉。**`已升级` 的条目留在正文**：
   机制兜住的是后果，兜不住的是「看到这个症状时该怎么判断」，那正是这张表存在的理由。

末尾还有一节**「这个文件不收什么」**：几类看起来像 gotcha、但不该收进来的东西，以及理由。

## Runtime and transcription

### 1. Word-level timing must come from SeedASR 2.0

**module**：helpers/transcribe_seedasr.py（转写后端这条缝）　｜　**状态**：已复现

The Ark `doubao-seed-2.0-lite` path is a generic multimodal LLM, not a reliable
ASR: it drifts 0.5–2 s, garbles fast Chinese, and hallucinates words in silence.
Long chunked requests degrade additionally near chunk edges (roughly the first
3 s and the last 5–7 s of each chunk), and no chunk-size tuning removes that.
Use `transcribe_seedasr.py`. Local `mlx_transcribe.py` is the last resort — it
keeps fillers verbatim but drifts ±0.3 s and drops punctuation.

### 2. Two engines disagreeing is a signal, not noise

**module**：helpers/transcribe.py（转写后端这条缝）　｜　**状态**：已复现

Re-run the window you are about to cut with a second backend before deleting a
token or trusting a proper name. That is how `关线`→`关键`, `经典`→`经验`,
`Chatbox`→`Chatbot` and a doubled `想` were resolved in one session — and how
three "duplicated" tokens turned out to be a single spoken word the ASR had split
in two. It is also how a suspected ASR error turned out to be the speaker's own
slip, which is a different decision.

### 3. Signed-in-but-unusable accounts

**module**：helpers/transcribe.py（账号与配额这条缝）　｜　**状态**：已复现

- Volcengine's models endpoint can list models the account cannot call. Probe the
  actual endpoint with real audio before wiring a backend. Ark LLM keys are not
  speech-console APP keys.
- Scribe quota pre-checks are advisory: the endpoint can report a usable account
  even when the upload later returns 401. Treat the real upload response as
  authoritative and keep an explicit fallback.

## Fonts

### 4. Hiragino Sans GB has no ✓/✗

**module**：helpers/ 的 PIL 卡片那条路 + references/frame-animation-pipeline.md　｜　**状态**：已复现

`U+2713 ✓`, `U+2714 ✔`, `U+2717 ✗`, `U+2718 ✘`, `U+2715 ✕` and `U+2611 ☑` all
render as the same notdef tofu box — a rounded square with a crossed rectangle,
which reads as a *rejection* mark. `U+221A √` and `U+00D7 ×` are real glyphs.
Check any symbol by comparing its mask against notdef before shipping it in a
PIL card.

## Filesystem

### 5. Cloud-synced video folders make ffmpeg fail intermittently

**module**：helpers/render.py（写大媒体那一步）　｜　**状态**：已复现

When footage and `edit/` live on a synced folder (OneDrive/iCloud/Dropbox),
writing a large mp4 in place can stall the muxer:

    Error submitting a packet to the muxer: Operation timed out
    Task finished with error code: -60 (Operation timed out)

exit 196. It is intermittent and it is NOT a code bug — it hit 1 of 7 short demo
clips in one run, none of the 16 full-render segments in another, then hit a
13-segment re-render on 2026-09-15. Build in a local temp dir and copy only the
finished artefact into the project: symlink `edit/clips_<tag>` at a local dir and
point `-o` at local disk, then copy `final.mp4` back. `/tmp` does not survive a
reboot, so delete the dangling symlink before the next render.

**2026-09-22, same failure, cheaper fix.** It hit a `render.py` segment extraction
(exit 196) and later a per-shot frame/clip ffmpeg call; the identical command run
by hand succeeded both times. **Wrap the project's own per-frame / per-clip ffmpeg
calls in an exponential-backoff retry** (4 tries, 1.5 s × n) instead of hand-fixing
afterwards — a 24-clip batch then finished with one silent retry. Retry is the
cheap default; local temp dirs remain the fix for whole-render stalls.

## Verification

### 6. A claim must match the evidence behind it

**module**：SKILL.md 的判断类规则（跨 module）　｜　**状态**：已复现

Say what was directly verified, and by which command; never let a passing check
stand in for a different property. The gates do not imply one another:

- `check_edl.py` — the cut is legal and the SRT sits on the render's timeline;
- `check_overlay.py` — every overlay can actually be composited;
- `verify_av.py` — the rendered file's tracks and its tail;
- `verify_delivery.py` — the DELIVERED artefacts, byte-identical to the working
  files;
- `import_svg_page.py --prove` — the page survived the import byte for byte.
  It says **nothing** about whether the composition renders: inlined paths, the
  theme, the timing and the DOM belong to `generate-composition.py` and to
  `npx hyperframes check`. Both commands are right; they measure different
  properties (the first real instance of this entry: `--prove` reported 8/8
  byte-identical on the very pages `hyperframes check` rejected with
  `invalid_parent_traversal_in_asset_path`).

An exception is not evidence of a diagnosis: "it worked last time" proves
nothing about an intermittent failure.

### 7. A tail pad longer than the delivery tolerance reads as a caption bug

**module**：helpers/check_edl.py　｜　**状态**：已复现

`check_edl.py` compares the last cue's end against the rendered duration with a
0.15 s tolerance. A tail pad of 0.20 s plus frame-grid rounding (~0.03 s) exceeds
it, and the failure is reported as `subtitles.srt 末条 … 与成片 … 不同步` — which
sounds like the captions are wrong when the real cause is a long tail pad. Keep
the tail pad at ≤0.10 s.

### 8. A leftover review server serves the wrong project

**module**：helpers/edl_review_surface.py + helpers/review_surface.py　｜　**状态**：已升级（剪接线那台自带服务器 `edl_preview_serve.py` 已退役，宿主归公共缝）

The cut review page uses a fixed port (8737) and the visual review page once used
more (5176 + 8899). A process left over from a previous session keeps serving its
old edit directory while a new server either fails with `Address already in use`
or, worse, succeeds and shows the old project. Before serving, find and stop the
listeners, then verify **which project** is being served. An HTTP 200 is not proof.

**视觉审阅那一半换了判据（2026-09-26，接入公共缝时）**：新宿主用 `--port 0` 自动选端口，
端口冲突根本不会发生 —— **端口不再有判断力，能证明身份的只剩内容**。`host_alive()` 现在要求
pid 还在 + 页面回 200 且注入过桥 + **`watch` 声明的项目文件逐字节等于磁盘**（本项目是
`timeline/timeline.json`）。最后一条是关键：页面是几个 Skill 共用的模板，**本来也分不出项目**；
timeline 才分得出。实测反例：把本项目的 host_state 指向别人的宿主 → 页面 200、桥也在，
但 timeline 的字节对不上 → 判为不是我们的。

## HyperFrames authoring

### 9. Register the timeline after the DOM, in the same script

**module**：references/composition-craft.md（组成品写作顺序）　｜　**状态**：已升级

A composition whose timeline never registers still renders: exit code 0, a valid
mp4, and a **still image** inside it. On 2026-09-21 five "animations" shipped this
way because the composition script (which used `tl`) ran *before*
`const tl = gsap.timeline({paused:true})`. Build the timeline first, register it in
`window.__timelines["<id>"]`, then append the tweens. `check_motion.py` catches the
result; the authoring order is what prevents it.

### 10. `onStart` callbacks do not replay under a seek-driven render

**module**：references/composition-craft.md（组成品写作顺序）　｜　**状态**：已复现

Changing DOM text from a timeline callback (`tl.to(el, {duration:.01, onStart(){…}})`)
looks right in preview and never fires in a render, because the producer seeks the
paused timeline instead of playing it. Counters froze at `01 / 21`. Anything that
must change over time is a pre-built element switched by `opacity`/`zIndex` sets.

### 11. Multi-round loops must be flattened into one step sequence

**module**：references/composition-craft.md（组成品写作顺序）　｜　**状态**：已复现

A two-round page flip written as nested loops left round 1's last card on top —
the animation looked stuck on one page (2026-09-21, found by the author). Compute
one flat step index `s`, show `s % N`, and explicitly push down `(s-1) % N`. Never
let a second round rely on the previous round having cleaned up.

### 12. Composition assets must be enumerated from the real files

**module**：references/composition-craft.md（资产清点）　｜　**状态**：已复现

Thumbnail paths were generated as `%02d_cover.png` when only the first page was
named `cover`; 20 of 21 tiles rendered empty and the encode still succeeded. Build
asset lists from `glob()` on the actual directory and eyeball a `snapshot` frame —
a green render is not a picture with content in it.

## Sources

### 13. Probe the display matrix before choosing a canvas

**module**：helpers/render.py（画布决策）　｜　**状态**：已复现

`ffprobe` reported `1920x1080` for a phone take that carried `rotation=90` and
displays as `1080x1920`. A whole film was nearly planned landscape off that number.
Read `stream_side_data=rotation` (or just extract a frame and look) before fixing
the canvas.

### 14. Screen recordings are VFR — force CFR before compositing

**module**：helpers/render.py + helpers/check_overlay.py　｜　**状态**：已升级

A macOS screen recording probed as `r_frame_rate=60/1` and delivered 5.14 fps and
29.36 fps streams. `check_overlay.py` refuses a rate mismatch, which is the gate;
the habit that avoids the round-trip is `-vf fps=30` on every screen-recording
source. Do not read the gate's catch as permission to try it raw.

### 15. `-t` between two inputs belongs to the second input

**module**：references/frame-animation-pipeline.md（ffmpeg 调用写法）　｜　**状态**：已复现

`ffmpeg -i a.mp4 -t 40 -i b.png -filter_complex …` makes `-t` an option of `b`, so
an infinite filter source (a `color=` canvas) ran unbounded: one run wrote 36,498
frames / 9.9 GB before it was stopped. Output duration is an **output** option —
put it after `-map`, and check the frame count when a batch finishes.

## What reaches the screen

### 16. The picture carries content, never method

**module**：helpers/check_screen_text.py + references/visual-direction.md　｜　**状态**：已升级

Two review rounds were spent deleting text that described production instead of
the subject: `10× 加速 · 中段停一下`, a `同一句标题：…` note-to-self, and a line that
repeated the author's own conclusion in the corner. `check_screen_text.py` bans the
method vocabulary; the judgement part is that a line which only makes sense to the
person editing is method, even when it contains no such word.

### 17. One cue per natural clause — the ceiling is not a grouping rule

**module**：helpers/check_caption_breaks.py + references/caption-article-first.md　｜　**状态**：已升级

A line plan built by packing clauses up to 20 characters and cutting at the limit
passed `srt_export.py --check` and read as `Adidas 有 7,618` / `条`, `分` / `析`.
`check_caption_breaks.py` catches the signature (a number without its unit, a
mid-sentence cut, an orphan cue). The rule it cannot check: long clauses are split
by a **human-chosen** break point, recorded as an override, never by an algorithm's
best guess.

## Review pages

### 18. A review copy needs sound, a visible save state, and per-round archiving

**module**：references/review-ui.md（审阅页的硬约定）　｜　**状态**：已复现

Three separate complaints in one session, all about the review artefact rather
than the film: the visual slices were `<video muted>` so the author could not judge
sync; auto-save worked but its indicator was a line in the corner, so the author
reported the feedback as lost; and the page reloaded the previous round's notes and
re-saved them with the new ones, making six old comments look like six new ones.
Mux the voiceover into the review copy (the delivery copy stays silent), keep a
sticky saved-at indicator plus a manual save, and archive the feedback file as
`<name>.round-N.json` before opening a fresh round.

## Delivery, audio and render entry points

### 19. Loudness and true peak are measured on the DELIVERED file, in stereo, whole-program

**module**：helpers/verify_av.py + helpers/audio_diag.py　｜　**状态**：已复现

`audio_diag.py` **downmixes to mono and keeps only speech-active regions**
(`voice_gate`). That is a diagnosis tool, not the delivery standard: the same
recording read -21.9 LUFS there and -18.9 LUFS under stereo whole-program
ebur128 — exactly 3 dB apart. **Accept on the delivered file's stereo
whole-program ebur128.**

Three traps compound so that "the source was fine" still ships clipped:

- **Linear two-pass loudnorm cannot close a loudness↔peak gap.** A source at
  -18.9 LUFS / -1.5 dBTP needs +4.9 dB to reach -14, but only 1.5 dB of peak
  headroom exists. Linear gain either stops at the ceiling (3 dB short) or is
  forced through it: one delivered file measured **+2.3 dBFS true peak while its
  sample peak still read -1.0** — neither meter complains. Fix the dynamics
  first, or use loudnorm's dynamic mode.
- **Lossy encoding adds inter-sample peaks.** Normalised to -1.5 dBTP, the AAC
  encode measured -0.8. To hold -1 dBTP in the delivery, leave roughly 0.6–1.0 dB
  of headroom at the source (‑1.8 dBTP was the value that held).
- **A mid-chain sample-rate change spends the headroom.** loudnorm left the chain
  at 96 kHz while the concat forced `-ar 48000`; the resample cost a further
  step. **Lock one sample rate through the whole chain** (`-ar 48000` at every
  stage).

### 20. `render.py --no-loudnorm` cannot take an `-o` that equals the internal base name

**module**：helpers/render.py（输出路径）　｜　**状态**：已复现

The base path is fixed per mode: `edit/base.mp4`, `base_preview.mp4` (`--preview`),
`base_draft.mp4` (`--draft`). With loudnorm on, the composite goes to
`<out>.prenorm.mp4` first, so no collision. With **`--no-loudnorm` it composites
straight to `-o`** — so `-o edit/base.mp4` becomes
`ffmpeg -i base.mp4 -c copy base.mp4` → `Output same as Input - exiting`.
Name the output something else (`person_leg.mp4`). The failure reads like a broken
render; it is only a name collision.

### 21. A silent visual leg makes `verify_delivery.py` fail, by design

**module**：helpers/verify_delivery.py + SKILL.md 第 11 步　｜　**状态**：已复现

`verify_delivery.py` requires an audio stream. In multi-leg delivery the voiceover
rides the person leg only and **the visual leg is silent on purpose**, so it
always reports FAIL for that file. That is expected, not a defect — but say so in
the delivery note, or the next session will try to fix a working file.

### 22. Never end a render command with a pipe

**module**：SKILL.md 的判断类规则（跑脚本时的习惯）　｜　**状态**：已复现

`render.py … 2>&1 | tail -12` makes the shell's exit status come from `tail`, not
from the renderer: an ffmpeg failure or a raised exception still reports
`exit code 0`, so "the render succeeded" is fiction. **No pipe when the exit code
matters** — redirect to a file and read the tail separately.

## External tools

### 23. `hyperframes render --help` advertises WebM transparency; only the MOV half is true

**module**：helpers/check_alpha.py + helpers/check_overlay.py（外部 CLI 行为）　｜　**状态**：已升级

The tool's own `--help` says "MOV/WebM render with transparency". On this machine
the WebM/VP9 half is false: it silently drops the alpha plane (the consequence is
guaranteed against by `check_overlay.py` + `check_alpha.py` — see the
removed-entries table). This is the first class the header names, **external tool
behaviour**, so no script of ours can hold it. The rule that survives: a CLI help
string is not evidence about a format. Ask the file —
`check_alpha.py overlay.webm`.

### 24. Re-rendering a project rendered before 2026-09-25 changes its bytes

**module**：helpers/render.py + helpers/verify_delivery.py　｜　**状态**：已复现

Two `helpers/render.py` changes landed on 2026-09-25 and both move bytes while the
picture stays the same:

- every ffmpeg invocation now carries `-bitexact`, so the muxer stops writing its
  own `Lavf`/`Lavc` version into the file (that version string was the reason a
  ffmpeg upgrade silently invalidated a "byte-identical" claim);
- the overlay filter string gained `:eof_action=pass:repeatlast=0`.

**Accepted consequence**: an already-delivered project that is re-rendered now
has a different `sha256` than the file that was delivered, so
`verify_delivery.py`'s byte-identity check reports a mismatch until that project
is re-rendered and re-delivered. The delivered files themselves are untouched.
This is judgement about how to read a claim, so it lives here rather than in a
script: do not repair the mismatch by loosening the check — re-render and compare
the picture.

## Render pipeline integrity

### 25. A freshly extracted segment was never read back

**module**：helpers/render.py（抽段循环）　｜　**状态**：已升级

ffmpeg can exit 0 having written a torn segment — one real run produced a **48-byte**
file (`moov atom not found`). The concat then skipped it, the film came out
80.000 s against a nominal 84.000 s, `segment_durations.json` recorded 80.0 as if
it were measured, and **every downstream gate stayed green** (`check_edl`,
`verify_av` — they agreed with the short total). A second run of the same EDL
raised an uncaught `CalledProcessError` instead. Same root cause: the cache-hit
path read each segment back; the just-extracted path did not.

Now: every segment is read back (`check_segment` — readable, audio/video within
one frame, within one frame of the request), a bad one is **re-extracted once**,
and a second failure is a hard stop naming the segment index, its file and the
requested length. `CalledProcessError` is caught into the same sentence.
`segment_durations.json` is not written until the total matches the EDL within
one frame per segment.

**The judgement that survives**: "it rendered" and "the film contains every
segment" are two properties, and the second one has no synonym in the first.

### 26. Delivery gates picked the render record by position

**module**：helpers/_edl.py（`select_render_record`）+ 它的四个读者　｜　**状态**：已升级

`segment_durations.json` accumulates one key per output name (`poc` / `draft` /
`mix-base` / `final`). Both delivery gates iterated the keys and took the first
record-shaped one, so they read the POC's 12.000 s and reported a correct 84.000 s
film as "possibly truncated or replaced" — a **false FAIL on the last gate**,
whose cost is that the next real FAIL gets ignored.

Now: the record is chosen by the current EDL's `edl_sha256`
(`_edl.select_render_record`), history stays in the file for humans and does not
vote, and a genuine hash mismatch is reported as exactly that.

**The judgement that survives**: a file that accumulates history needs one place
that says which entry is current; picking by iteration order is not a policy.

### 27. The page importer's href boundary was the page directory

**module**：visual/scripts/import_svg_page.py（`resolve_pages` / `href_boundary`）　｜　**状态**：已升级

Pointing `--pages` at the picture project's `_internal/02_svg_source` — the string
the docstring itself advertised — resolved the href boundary to that directory,
so every page-relative `../00_project/...` href "escaped" it and the import failed
on the very pages it shipped. Worse, the error advised copying files into the
package (breaks byte-for-byte fidelity) or rewriting the page's href (breaks the
upstream contract that the page keeps its own relative href for its PPT exit).

Now: the boundary is the page directory's parent, or the project above it when
that parent is `_internal`; project root / page directory / package root /
`input/` / `input/scenes/` all resolve to the same pair; the error names the
correct call and offers no contract-violating fix.

**The judgement that survives**: an error message is part of the interface. When
the cheap fixes it suggests are both forbidden, the message is the defect.

### 28. Inlining a page by hand bypasses the href rewrite

**module**：visual/scripts/import_svg_page.py + visual/scripts/generate-composition.py　｜　**状态**：已升级

The importer rewrites `<image>` hrefs to root-relative paths *when it inlines*.
A hand-inlined page (the route taken while P-24 blocked the CLI) kept
`../00_project/...`, and `npx hyperframes check` rejected it with
`invalid_parent_traversal_in_asset_path` — while `--prove` reported 8/8
byte-identical on the same pages. Both commands were right: they prove different
properties.

Now: `generate-composition.py --verify` fails on any `href`/`src` that traverses
above the composition root, and the importer's docstring states what `--prove`
does and does not prove.

**The judgement that survives**: a green light certifies the property it measured,
not the one you care about. `--prove` measures the page's round trip.

## Visual layer handoff

### 29. The same id in two pages makes `#name` ambiguous

**module**：visual/scripts/import_svg_page.py（`audit_pages`）+ 画面侧的 id 规则　｜　**状态**：已升级

Inline pages land in ONE DOM. `hyperframes check` reported
`#caption-1 2.5:1 (need 3:1, t=11.556s)` — a timestamp inside **another**
screen — because four clips each carried a `#caption-1` and the contrast check
resolved the id globally. The animation layer has the same exposure: "animate
`#caption-1`" highlights the first match, which may be another screen's element,
and nothing fails.

Now: `--audit` reports every id shared by more than one page and exits non-zero;
the fix is on the picture side (prefix ids with the `page_key`). Ids are **never**
rewritten here — that would break the byte-for-byte promise.

**The judgement that survives**: addressing by id is only safe when the id is
unique in the DOM it lands in. Uniqueness per page is not uniqueness.

### 30. A criterion that can never fail

**module**：visual/scripts/check_themes.py + references/themes.md　｜　**状态**：已升级

`NOTE_CONTRAST = {"--text-mute": 4.5, "--text-faint": 3.0}` was pushed into
`notes`, and only `failures` drove the exit code — so 23/23 themes reported
`0 failing` while 18 of them sat at 1.86–2.98:1 on `--text-faint` and six at
3.92–4.42:1 on `--text-mute`. `themes.md` meanwhile said `--text-faint` "仍然要
可读". "Nothing passed" was displayed as "0 failing".

Now: `--text`/`--text-2`/`--text-mute` are enforced at 4.5:1 (the six themes were
re-coloured), `--text-faint` carries **no threshold at all** — its measured ratio
is printed with "no minimum — this tier is measured, not enforced" — and
`themes.md` says the same thing in its token table.

**The judgement that survives**: a number that appears in a criteria table must
be able to fail something. Otherwise delete the number, not the check.

### 31. `hyperframes doctor` does not check the font cache

**module**：helpers/check_render_env.py（外部 CLI 行为）　｜　**状态**：已升级

In a restricted sandbox `hyperframes render` dies partway with
`EPERM: operation not permitted, mkdir '~/.cache/hyperframes/fonts/noto-serif-sc'`
and suggests only `--docker`. `HYPERFRAMES_FONT_CACHE_DIR` is the way out; it is
one of 50-odd `HYPERFRAMES_*` variables in the packaged code, appears in no help
text, and **is not one of `doctor`'s nine checks** (version / node / memory /
disk / frames cache / ffmpeg / whisper / TTS / BGM). `doctor` is the only entry
the docs point at for "check system dependencies".

Now: `check_render_env.py` probes the cache by **actually writing a file into it**
(a mode bit is not the question), fails early naming the variable, and is
documented as a required step before the first render.

**The judgement that survives**: "the tool has a doctor command" is not evidence
that it checks your failure. This is external tool behaviour, so no script of
ours can hold it — the preflight holds the *consequence*.

## 接入公共审阅缝（planners-review-core）

### 32. 注入点必须裸着独占一行，而且只许一个

**module**：visual/assets/review-page-template.html　｜　**状态**：已升级

公共缝的宿主是把那个双花括号标记**原地换掉**，换成**一整段**（无插件：一个给 base 的
`<script>` ＋ 一个外链 `<script src>`；插件：内联的桥源码）。所以标记**不能待在属性里、
也不能待在标签内部** —— 整段替换会把那个标签撑破：

| 页面里的写法 | 结果 |
|---|---|
| 放进 `src=""` 里 | 整段塞进属性 → 标签坏掉，桥根本不加载 |
| 塞进 `<script>` 标签里 | 变成嵌套 `<script>` → 同样加载不了 |
| **裸着独占一行** | ✅ 唯一正确写法 |
| 出现两次 | 桥被注入两遍（校验器 `bridge_placeholder_multiple`） |

三种错法都真的出现过。教训不是"记住哪个写法对"，而是**"一个标记"没写清它长什么样时，
每个 Skill 都会各自猜一个**。缝后来把闸门装上了（`bridge_placeholder_not_bare` /
`bridge_placeholder_multiple`），现在写错会在 `validate_surface` 那一步直接红。

**连带教训（判"宿主是不是活着"时）**：别去比"标记被换成了什么字符串"。把那句话写死在自己
这一边，宿主一改注入形态，判据就**静默**永远为假 —— 活着的宿主被判成死的，每次开审阅多起
一个进程，没有任何报错。要比的是「**注入点以外**逐字节相同 ＋ 注入点确实被换掉了」
（`review_surface.py: _page_is_ours` 就是拿磁盘页面在标记处切开比前缀后缀）。
项目身份另用 `watch` 声明的文件比 —— 页面是几个 Skill 共用的模板，本来也分不出项目。

### 33. 一屏画不出来，把整张清单带走了（而页头还写着"23 步"）

**module**：visual/assets/review-page-template.html　｜　**状态**：已复现

拿一个真项目（`05-VideoProject/PPTSkillV2`，2026-07-18 的时间轴）跑审阅页：页头正常显示
"6 章 · 23 步 · 03:59"，**下面一屏都没有**，而且没有任何报错。原因是渲染循环里
`st.cueRange[0]` —— 那个项目的时间轴只有 `srtRange`（字段改名前产的），一个 `TypeError`
抛在 `for` 里，整个清单就没了。

两件事都要修，缺一不可：
1. **认两种字段名**：现在是 `cueRange`（`helpers/timeline_derive.py` 产出），老项目叫
   `srtRange`（本仓库的 `visual/scripts/align-visual-plan.py:175` 就在做这个改名）。
2. **单屏失败不许拖垮整张清单**：每屏的渲染各自 try/catch，坏的那屏自己显示"画不出来 +
   为什么"，并在状态位上说清少了几屏（`drew / failed`）。

第 2 条是更一般的教训：**"页头说有 23 屏、下面一屏都没有"看起来像"这个项目没问题"**。
清单类页面的每一行都要能独立失败并出声。

### 34. `os.kill(pid, 0)` 对僵尸进程也返回成功

**module**：helpers/review_surface.py　｜　**状态**：已复现

`stop_host` 用 `os.kill(pid, 0)` 判"宿主停了没有"。子进程退出但父进程还没 `wait()` 时它会
变成僵尸 —— **仍然占着 pid，`kill(pid, 0)` 仍然成功**。于是宿主明明已经关了，`stop_host`
报"没停掉"，看起来像漏了进程，实际只是没回收。

自己起过的宿主一律先看句柄：`Popen.poll()` 会顺手 `waitpid` 把僵尸收掉，它给出的才是真的
"还在跑吗"（`_HOST_HANDLES`）。另外 `serve-review.mjs` 的 SIGTERM 处理器要等已有连接关干净
—— 浏览器留着 keep-alive 时可能一直不返回，所以 `stop_host` 超时后**升级到 SIGKILL**，
"收干净"才是真的。

## Removed entries, and where the guarantee lives now

Kept as a subtraction audit trail, so a future session can tell a deliberate
deletion from an accidental loss.

| Removed gotcha | Now guaranteed by |
|---|---|
| Transparent overlays silently composite a black base (WebM/VP9 alpha) | `check_overlay.py` + the guard inside `render.py`, and `helpers/check_alpha.py` — the verdict is the extracted alpha plane's SPAN, never `pix_fmt` (it under-reports HEVC+alpha and cannot prove loss) |
| Chunked doubao degradation at chunk edges | merged into #1 |
| Transcript quality + content understanding precede the EDL | SKILL.md process step 2 |
| A transcript change invalidates every old EDL boundary | `check_edl.py` cut-inside-word failure |
| Segment caches are content-blind | content-keyed cache (`clips_<tag>/manifest.json`) |
| EDL word gaps do not prove rendered pauses are within target | `check_edl.py --max-pause` |
| Multi-track sources upload the wrong audio track | `transcribe.py` cache key + silence guard |
| A multi-source render probes frame rate per segment | `render.py` resolves one rate for the whole render |
| A stale preview server serves the wrong project | still live — see #8 |
| A rendered animation is silently a still image | `check_motion.py`; the authoring order is #9 |
| Process words (加速/静帧/裁切…) drawn on screen | `check_screen_text.py`; the judgement is #16 |
| Captions packed to a character ceiling | `check_caption_breaks.py`; the judgement is #17 |
| A torn segment reaches the film and the render exits 0 | `render.py`'s `check_segment` + `check_total_duration`; the judgement is #25 |
| The gates read the POC's render record | `_edl.select_render_record` by EDL hash; the judgement is #26 |

## 这个文件不收什么（附理由）

下面几类看起来像 gotcha、但**故意不收**。写在这里是为了让下一个人不用重新判一次。

| 不收的类别 | 为什么 | 例子 |
|---|---|---|
| **一次性的规格缺失** | 它是「这个 Skill 还没写清」，不是「会稳定导致错误的具体行为」。修法是补那份规格，补完就没有候选了 | 上游契约要一个新字段而我这边没读；某份 reference 少了一节 |
| **已经修好的环境与脚手架** | 它是一次性事实，不是行为。留着只会让人以为还要处理 | 本机没有 `uv`、`<skill>/.venv` 是空壳、Python 下限被写成 3.10、`install.md` 里的 `uv sync`——统一解释器之后全部失效，见 `maintenance-history.md` |
| **别的 Skill 的问题** | 记在这里会被当成我们的待办；它的 owner 在那边 | `planners-ppt-hell` 的模板库锁层、`init` 的 `--assets` 路径口径、`validate_svg_layout.py` 把出画布降级成 info、两套审阅面不能互操作（作者已裁定不合并） |
| **作者已裁定接受的设计** | 它已经是一个决定，不是待修的缺陷。重复登记等于每轮重新讨论一次 | 两个审阅面不合并；`--assets` 与契约引用必须全等；审阅服务端口被占就报错退出；重渲会改变已交付文件的字节（见 #24 的 accepted consequence） |
| **一次运行的偶发失败** | 没有稳定复现路径的偶发失败只写现象是噪音。要收就先做一次可复现的（见 #5 的两次记录）。**边界：由默认值稳定复现的资源事故不属于这一类**——只要用了那个默认值、在那台机器上就必然发生，它是「会稳定导致错误的具体行为」，收进正文（见 #69） | 「这次 ffmpeg 卡住了」而没有复现步骤 |
| **可以从代码/文档一眼查到的事实** | 缓存不是记忆。文件里写着的，指针就够了 | 某个脚本的 CLI 参数、某个目录的形状、某条判据的阈值 |
| **同一根因的第二张脸** | 根因合并成一条；另一张脸在正文里当实例写，不另立条目 | 坏段「静默少一段」与「未捕获崩溃」是同一条 #25；`--prove` 绿灯与「composition 渲染不出来」不是两件事，是 #6 的一个实例 |

## 35. 出口与内容不许取决于"恰恰会失败的那件事"（R11）

**页面必须能刷新自己，而且入口不许藏在告警里。** 两个真实例子，都是"入口/内容的存在取决于
一个条件，而那个条件在需要它的时候恰好不成立"：

- **刷新入口只做在橙色告警里**（时间轴变了才出现）→ "我改了页面、让他重载拿新版"这个场景
  **恰好没有出口**：数据没变 → 不出现告警 → 没有按钮，而那个按钮本来就在他要拿的新版里。
  先有鸡先有蛋（用户当场报的）。修法：页头一个**无条件存在**的 `⟳ 刷新`，而且写成纯 HTML
  链接（空 `href` ＝重新加载当前地址）—— **不依赖页面自己的 JS**，因为"页面自己的脚本是旧的/
  坏的"那一档才是最需要它的时候。（宿主对页面发 `cache-control: no-store`，刷新拿到的确实是
  磁盘上那一版。）
- **本机草稿只在时间轴读到时才放回输入框**（`if (data) restoreDraft()`）→ "时间轴读不到"这个
  **最想找回自己那段字**的场景里草稿不显示，人一重打就被 `saveDraft` 覆盖。修法：`restoreDraft()`
  无条件先跑（它跟时间轴没关系），而且放在 `loadTimeline()` **之前**，免得"已恢复本机草稿"
  盖掉时间轴的报错。

自查问法：**这个按钮/这段内容，是我在什么条件下才给的？那个条件会不会恰好在我要用它的时候不成立？**

## 36. 测量工具在测量自己

查"还有没有残留进程"时用了 `pgrep -f "serve-review.mjs"` —— 它**匹配到了自己所在的 shell 管道**，
于是报了一个不存在的泄漏。同一族还有：拿 `grep` 找 `grep`、拿进程名过滤时把过滤命令自己算进去。
**修法**：让模式匹配不到自己，例如 `pgrep -f "[s]erve-review"`（字符类把字面量拆开），
或者先取到输出再用代码判断。**报之前先问一句：这个信号有没有可能是测量动作自己产生的。**

## 37. 想要"写沙盒"就**硬链接**，别用软链 —— 宿主会（正确地）拒绝

**场景**：要对一个**真项目**做端到端验收，但不能写坏它（素材 0.5–2 GB）。做法是照原样复制一份
到 `/tmp`、只把大素材**链接**过去。

- **软链接是错的方向**：宿主对静态文件做 `realpathSync` 包含性校验（`real !== ROOT && !real.startsWith(ROOT+sep)` → 404）。
  软链的 realpath 落在根**外面**，于是请求全 404 —— 那条校验是**正确的安全属性**，不该为了测试绕它。
- **硬链接是对的**：`os.link(src, dest)` 之后 dest 的路径就在根里（同一个 inode），
  realpath 校验自然通过、不占额外空间、不用等 1.7 GB 复制。实测拿 2.04 GB 的真项目当 fixture 跑得很好。

**另一条**：改写副本里的 `edl.json` 时，素材路径要按**原来的相对布局**算（`os.path.relpath(src, edit)`），
**不许压平成 `../<文件名>`** —— 真项目会把素材放在子目录里（实测 `../assets/BLACK_talk.mp4`），
压平之后页面里那个 URL 在 serve root 下根本不存在（是我自己第一版测试踩的）。

## 38. 浏览器用例：**一个类共用一个浏览器**，而且失败也要关

一条反面对照在**全量跑**时偶发过一次 ERROR（单独跑、连跑两次都过）。根因是结构性的而不是"运气"：

- 一类里**每个用例各起一次** Chromium，而这个 fixture 还压着 2 GB 硬链接项目 + 一个真宿主；
- **失败路径不关浏览器**（`browser.close()` 写在用例末尾）→ 一旦某条挂了，Chromium 就留着，
  后面的启动更容易抖。**"偶发"就这么攒出来的。**

修法：`setUpClass` 起一次 `sync_playwright().start()` + `chromium.launch()`，`tearDownClass` 里
`try/finally` 收（浏览器 → playwright → 宿主 → 临时目录）；每个用例 `addCleanup(page.close)`。
启动次数 4 → 1，整份 suite 还快了约 7 秒。**加固后：文件级 3 连跑 + 全量（含浏览器）2 连跑全绿。**

## 39. 交付审阅页必须启动 HTTP 审阅宿主，绝不能直接 open 本地 file:// 路径

- **现象**：向作者展示 `edl_preview.html` 粗剪工作台时，若直接使用 `open edl_preview.html`（`file://` 协议），页面顶部的审阅桥占位符 `{{REVIEW_BRIDGE}}` 未被宿主动态注入，且现代浏览器出于跨源与安全限制禁止 `file://` 下的 `<video>` 加载上层目录素材或发起 Byte-Range 视频分段流请求，导致画面黑屏、视频无法加载、审阅桥显示未连接。
- **原因**：`edl_preview.html` 架构设计假定通过 `edl_review_surface.py` 启动本地 HTTP 宿主提供服务（serve root 为素材与剪辑目录的公共根，且在传输 HTML 时由 `serve-review.mjs` 动态将 `{{REVIEW_BRIDGE}}` 替换为审阅桥通信脚本）。如果只执行了 `--surface-only` 或试图绕过服务器直接用浏览器打开本地静态 HTML，破坏了这一架构前提。
- **行为修正**：凡需给作者呈现审阅页面（无论是粗剪工作台还是视觉审阅），绝不直接 `open file://` 静态文件，必须运行 `edl_review_surface.py <edit_dir>`（或对应的审阅启动脚本）启动/复用 HTTP 宿主，并使用返回的 `http://127.0.0.1:<port>/...` 地址在浏览器中打开。
- **证据**：2026-10-02 在《Research与Wayfinder调研》实录剪辑中，误用 `open edit/edl_preview.html`，导致作者端显示 `{{REVIEW_BRIDGE}}` 占位符且视频播放器黑屏无法播放；改为启动 `edl_review_surface.py` 并打开 HTTP URL 后立即恢复全功能播放与剪辑。
- **状态**：已记录，已确立为铁律。

## 40. SVG 空间布局平移 (Layout Transform) 与 WAAPI 动效平移冲突覆盖

- **module**：`visual/assets/review-page-template.html` / `visual/scripts/svg-anim-engine.js` ｜ **状态**：已复现
- **现象**：在多元素/多卡片并排排版的 SVG 场景中，卡片外层通常带有静态坐标定位（如 `<g transform="translate(610, 0)">` 或 CSS `transform`）。若动效脚本直接在该元素上应用 WAAPI 平移动效（如 `el.animate([{ transform: 'translateY(18px)' }, ...])`），动效执行瞬间该元素的静态 `translate(610, 0)` 被完全重置为 `(0, 0)`，导致所有卡片瞬间挤压并重叠在最左侧边距。
- **原因**：CSS/WAAPI 的 `transform` 动画属性在执行时会完全覆盖元素 SVG 属性上声明的静态 `transform`。
- **修正原则**：**静态空间布局与动态入场动效必须物理分层**：外层 `<g transform="...">` 只负责空间栅格与定位；内层子元素（或嵌套 `<g>`）才挂载 `.anim-*` 动效类与 WAAPI 关键帧。动效类绝不可以直接打在带有空间布局位移的外层容器上。
- **证据**：2026-10-02 在《Research与Wayfinder调研》beat-01 三卡片入场动效中，三张卡片直接被赋予 `pop-card` 动效导致全部被拉回 x=0 挤成一团；重构为外层 `<g transform="translate(...)">` + 内层 `<g class="anim-card">` 后恢复正常排列。

## 41. Headless Browser Screencast 在 `<video>` 元素上的 IPC 缓冲区死锁

- **module**：`helpers/export_video.py` ｜ **状态**：已复现
- **现象**：使用 Playwright/Puppeteer `page.startScreencast` 对包含正在播放的 `<video>` 元素的 HTML 页面进行录屏导出时，当视频播放超过数秒（IPC 传输数据量超 512KB）后，Chromium 进程彻底卡死，IPC 通道无响应，CPU 占满。
- **原因**：Headless Chromium 的渲染流水线在将硬解/软解视频帧与 DOM 图层合成并跨进程序列化为 screencast base64/buffer 时存在资源竞争与锁死。
- **修正原则**：**严禁在浏览器录屏中录制正在播放的真实视频文件**。动画舞台走确定性截帧/离线渲染；真实口播视频交由 FFmpeg 在输出层通过 `overlay` 硬件加速混合。
- **证据**：2026-10-02 在《Research与Wayfinder调研》导出全片时，尝试直接用 Playwright 录屏捕获包含播放 `<video>` 的双通道页面，连续 3 次在第 30-40 秒彻底死锁；改用离线截帧+FFmpeg overlay 后秒级导出成功。

## 42. 剪点必须按实测音频判，不能按转写词框判

- **module**：`helpers/_silence.py`、`helpers/check_edl.py` ｜ **状态**：已复现
- **现象**：`check_edl.py` 原先用「剪点是否落在某个词的 `start`-`end` 之间」作硬判据。在《图拉斯创新》2026-10-09 那条录音上，按 SeedASR 词框重建 EDL 时 34 个剪点里有 **11 个被判为「切在词内」**，按 Scribe 词框则报出另一批——两版都判错，因为两版词框都不准。
- **原因**：两个引擎各错一个方向：SeedASR 的**起点早 0.15–0.25s**、词尾伸进后面的静音（实测「包」报 67.87，音频静音实到 68.04）；Scribe 的停顿估计反而准，但 token 跨度会并吞（把「。muji，」并成一个 2.9s token）。词框既非充分也非必要，唯一真相是音频本身。
- **修正原则**：判据换成 10ms RMS 包络（阈值按 5% 分位底噪 +10dB 自适应）。**落在实测语音里 = HARD**（会切到声音）；**落在词框内但实测是静音 = WARN**（词框偏松，剪点没问题）。测量不可用时退回词框判据并在结果里标注 `silence_gate: unavailable`，绝不静默放过。
- **证据**：同一条录音，实测 129.79 处为 −73.8dB 房间底噪（真语音 130.00 起）、210.62 处为 −65dB（真语音 210.80 起），两处都被旧判据误杀。回归测试 `tests/test_edl_silence_gate.py`。

## 43. 渲染器的帧格是 ceil，不是 round

- **module**：`helpers/duration_plan.py` ｜ **状态**：已复现
- **现象**：用 `round(raw × fps) / fps` 解析预测各段时长，14 段里只对 6 段；总长比实测少 0.267s。
- **原因**：编码器把每段**向上**取到帧格（`-t` 的 3 位小数 + 编码器自身的 ceil），不是四舍五入。逐段向上累积，38 段能累出一整秒——这正是当初引入「实测段时长」的原因。
- **修正原则**：预演公式用 `ceil(round(raw × fps, 6)) / fps`（内层 round 只为消浮点噪声，否则 8.8×30 = 264.00000000000006 会被 ceil 成 265）。**改用 ceil 后 14/14 段与真实渲染逐位一致**，回归测试 `tests/test_duration_plan.py::test_the_grid_is_ceil_not_round` 钉住这组实测对。
- **证据**：《图拉斯创新》`segment_durations.json["master_final"]` 的 14 个实测值。

## 44. 审阅页要能合成层，就必须有一份浏览器可合成的载体

- **module**：`visual/scripts/encode_transparent.py`、`helpers/preview_layers.py` ｜ **状态**：已复现
- **现象**：覆盖层按 MOV（PNG-in-MOV / ProRes 4444）编码——那是 ffmpeg 能合成的格式。把它放进 `<video>` 叠在成片上，浏览器给的是不透明黑块，于是「在页面上预览动效」根本不成立，只能把层烘焙进整片再看。
- **原因**：浏览器不支持 MOV/ProRes 的 alpha（Chrome 系完全不支持，Safari 仅限 HEVC-with-alpha）。唯一被广泛支持的载体是 **WebM VP9 + `yuva420p`**。
- **修正原则**：同一份源出两份载体——MOV 交交付合成，**WebM 只作预览**（`encode_transparent.py --codec webm`，`-auto-alt-ref 0` 必须给，否则 alpha 不写入）。`preview_layers.py` 为 EDL 里每个层补 sibling `.webm`；`build_review.py` 据此填 `media.layers[].previewFile`；页面用它叠层。
- **证据**：红底合成验证——WebM 层叠上去后透明处透出底色；`verify_alpha` 报 plane range [0,255] span 255。

## 45. VP9 的 alpha 是带外的：不点明解码器就抽不出来

- **module**：`visual/scripts/encode_transparent.py::_alpha_range` ｜ **状态**：已复现
- **现象**：对带 alpha 的 WebM 调 `alphaextract`，默认解码路径报 `Requested planes not available`，`ffprobe` 也只报 `pix_fmt=yuv420p`——看起来像「编码没写进 alpha」，其实写进去了。
- **原因**：VP9 在 WebM 里把 alpha 存在独立的 BlockAdditional 里，ffmpeg 的默认解码器不暴露这个平面，必须显式 `-c:v libvpx-vp9`。
- **修正原则**：`_alpha_range` 先用默认路径抽，失败后**用显式解码器重试并打印说明**，而不是直接判失败。（原有的判据「pix_fmt 只是参考、以平面为准」是对的，这里补的是取平面的方法。）
- **证据**：同一份 WebM，默认路径 0 字节；`-c:v libvpx-vp9` 得到 1080×1920×96 帧 = 199,065,600 字节完整平面。

## 46. 云同步目录里刚建的目录，下一个进程可能看不见

- **module**：`helpers/review_slices.py` ｜ **状态**：已复现
- **现象**：`out_dir.mkdir(parents=True, exist_ok=True)` 之后立刻调 ffmpeg 写该目录，ffmpeg 报 `Error opening output ... No such file or directory`（exit 254），事后该目录也不存在。
- **原因**：工作区在 OneDrive 上，新建目录的元数据没有立刻对下一个进程可见（与第 5 条同源：云同步目录对 ffmpeg 的间歇性影响）。
- **修正原则**：建完目录**立即验证**，不可见就重试一次，仍不可见则明确报错——而不是「跑了 28 个切片，实际 0 个」。同类写入前都该这样自证。
- **证据**：手工先 `mkdir -p` 再跑则 28 个切片全部成功；不先建目录时同一命令失败。

## 47. 页面实时叠层，不能叠在已经烘焙了层的成片上

- **module**：`helpers/build_review.py`、`visual/assets/review-page-template.html` ｜ **状态**：已复现
- **现象**：审阅页学会了把 EDL 的层叠在视频上之后，如果播放的仍是「已经把层烘焙进去的成片」，同一层就被画两遍——翻页动画叠出一个重影，而且因为两次编码的起点差几帧，重影还会轻微错位。
- **原因**：两种模式是互斥的，但数据契约里没有表达：`compositeVideo` 既可能是「烘焙好的成片」，也可能是「待叠层的底片」。
- **修正原则**：`review/media.json` 声明 `baseVideo`（未烘焙的底片）时，`compositeVideo` 取这份底片并置 `layersBaked: false`，页面才实时叠层；没声明时默认 `layersBaked: true`，页面**不叠**并说明原因。宁可少画一层，也不能画出重影。
- **证据**：2026-10-12《图拉斯创新》——13 个层 + 已烘焙成片同时在场时才暴露；改成「底片 + 实时叠层」后一致。

## 48. composition 里 CSS 初始 transform 与 GSAP 补间会互相抢

- **module**：`hyperframes` 的 lint（`gsap_css_transform_conflict`、`root_composition_missing_data_start`） ｜ **状态**：已确认
- **现象**：给元素写 `style="transform: translateY(20px)"` 再用 GSAP 补间同一属性，lint 直接拒；根元素漏掉 `data-start="0"` 报 `root_composition_missing_data_start`。
- **修正原则**：初始状态写在补间里（`gsap.fromTo(el, {y:20}, {y:0})`），CSS 只负责布局（`left`/`top`/尺寸）；根元素四件套 `data-composition-id` / `data-start` / `data-width` / `data-height` 一个都不能少。翻页这类「有意扫出画布」的动效要显式 `data-layout-allow-overflow`，否则每次 check 都报 info。
- **证据**：《图拉斯创新》翻页 composition，`hyperframes check` 从 8 error + 2 info 到 **0 error / 0 issue**。

## 49. PIL 的 rotate 是逆时针为正，CSS 的 rotate 是顺时针为正

- **module**：任何「逐帧渲染器改写成 HTML/CSS」的移植 ｜ **状态**：已复现
- **现象**：把作者的逐帧动效按同一组数字搬进 GSAP 后，卡的位置、尺寸、alpha 边界全部对上（位移互相关最佳值 dx=dy=0，边界行 1124 vs 1123），**但图案整体不对**——看起来像「同一张图被放大了」。落定帧逐像素差 52.9，而 alpha 只差 0.26。
- **原因**：同一个角度值在两侧方向相反。`Image.rotate(θ)` 逆时针为正；CSS `rotate(θ)` 顺时针为正。旋转后的外接矩形对 ±θ 是对称的，所以**边界与覆盖率都对得上，只有内容反了**——这正是它难查的原因。
- **判据**：拿一张卡单独试两个符号，实测 PIL `rot=-14.245°` 时 CSS 必须写 `+14.245°`（逐像素差 **0.94** vs 不取反的 **26.38**）。移植前先做这个单卡双向对照，别等整帧对比。
- **修正原则**：移植时统一 `cssRot = deg => -deg`，位移、角度、抖动全走它。

## 50. composition 缺 viewport meta 会让浏览器整体缩放页面

- **module**：HyperFrames composition 骨架 ｜ **状态**：已复现
- **现象**：同一份 HTML，正品卡（`<img>` 未设宽高、按自然尺寸渲染）逐像素吻合，而卡片（`width:100%`）看起来被放大约 1.3 倍。
- **原因**：`<head>` 里漏了 `<meta name="viewport" content="width=…, height=…" />`。没有它，浏览器按默认视口（约 980px）布局再把整页缩放去适配，于是「显式像素尺寸」的元素全被比例放大。正品卡因为按图片自然尺寸渲染、又恰好落在一个被缩放的容器里，容易被误判为「没问题」。
- **修正原则**：`data-width` / `data-height` 之外，**viewport meta 必须同步写上同样的尺寸**。这是最小骨架的一部分，不是可选项。

## 51. lint 会把运行期 `if` 当成「补间一定存在」

- **module**：`hyperframes check` 的 `overlapping_gsap_tweens` ｜ **状态**：已复现
- **现象**：写 `if (SPEC.hold > 0) { tl.to(g, …) }` 时，`hold = 0` 的组也被报「autoAlpha 补间在 0.00–0.26s 重叠」；连**根本没有该元素**的组（`genuine: null`）也照报。
- **原因**：lint 静态读时间轴，不求解 `SPEC` 的取值，按最坏情况假设补间存在。
- **修正原则**：这类条件要在**生成期**决定——生成器直接决定写不写这一段（含元素本身的块），而不是留一个运行期分支。修完 `hyperframes check` 从「2 warning」到 **0 error / 0 warning**。

## 52. 编码产物不要直接写进云同步目录

- **module**：`visual/scripts/encode_transparent.py`、`helpers/preview_layers.py` ｜ **状态**：已复现
- **现象**：把 VP9/MOV 直接编码到 OneDrive 上的目标路径，长任务跑到一半报 `Error writing trailer: Operation timed out` / `Error closing file`，**留下 0 字节文件**（五层里坏了两层），而命令看上去只是「慢」。
- **原因**：与第 5、46 条同源：云同步目录对长时间连续写入不稳。
- **修正原则**：**先编码到本地 /tmp，成功后再 move 进目标目录**。`encode_sequence()` 与 `preview_layers.export_one()` 现在都这么做；凡是「跑几十秒以上的写盘」都该按这条自查。

## 53. 审阅页在**不透明源 iframe** 里：宿主 token 不会继承，硬编码会静默胜出

- **module**：`visual/assets/review-page-template.html` ｜ **状态**：已复现
- **现象**：页面「看着能用」，但整片偏暗、反馈卡是深底、跟宿主的明色主题格格不入；一查发现模板里有**两个重复的 `body { --bg-*: var(--dsw-*) }` 块**（映射还不一致：`blue-600` vs `deepseek-500`、`border-l4` vs `border-l3`，后者覆盖前者），另有 49 处硬编码色值绕过 token。
- **原因**：审阅页跑在 `sandbox="allow-scripts"` 的**不透明源 iframe** 里——宿主的 CSS 变量不继承进来，外链样式表也会被信任围栏打回。所以 DSH token 必须**随页面发**（`/*__DSH_TOKENS__*/` 占位符 + `planners-review-core/assets/dsh-tokens.css`）。真正致命的是**组件自己写死颜色**：`.fb-card { background:#1c202d !important; color:#e2e8f0 !important }` 这种带 `!important` 的硬编码，会让 token 桥形同虚设，而且明暗两套主题下都不报错。
- **修正原则**：模板只允许引用 `var(--dsw-*)`（经 `body` 的别名映射）与语义变量；**组件级硬编码一律清掉，尤其带 `!important` 的**。改完 count 从 63 → 32（剩下的是 token 缺失时的兜底调色板）。
- **证据**：同一份数据，改前反馈卡深底近似白字、改后随主题；`#stale-note`、`.fb-card-body`、`.fb-card-badge` 等都是这一类。

## 54. 删掉标记、却没删挂事件的代码 → 页面死在渲染数据之前

- **module**：`visual/assets/review-page-template.html` ｜ **状态**：已复现
- **现象**：去掉「视听动效舞台 / 最终合成预览 / 逐字剪辑」三个切换按钮后，页面变成**「0 屏」**——像是数据没加载，其实是 `document.getElementById("view-svg-btn").addEventListener(...)` 拿到 null 抛了 `TypeError`，整个脚本在渲染列表之前就停了。
- **原因**：这类挂载点不写 null 保护；一旦元素不在（被删、或某个模式不渲染），失败发生在**离症状很远的地方**。
- **修正原则**：删 UI 元素时必须同时删/收口它的挂载点，并且新挂载一律 `if (el)` 保护。另外**不要在顶层调用依赖 `let` 的函数**：`setStageViewMode("composite")` 提前调用会撞上 `isGlobalPlaying` 的 TDZ，报的是 `Cannot access ... before initialization`。初始可见性应当写在标记里，而不是靠初始化脚本补。
- **证据**：《图拉斯创新》审阅页两轮排查：先 `Cannot read properties of null`，修完暴露 `Cannot access 'isGlobalPlaying' before initialization`。

## 55. 「当前屏」只在扬声器轨可见时才被记下 → 上一屏/下一屏看着像坏的

- **module**：`visual/assets/review-page-template.html` ｜ **状态**：已复现
- **现象**：点「上一屏 / 下一屏」完全没反应，且**换屏不跳画面**；「播放」只把按钮文字变成「暂停」，画面纹丝不动。
- **原因**：三处相互叠加。① `state.currentScreenObj = st` 只写在「扬声器视频可见且没有 SVG」那条分支里，而很多项目根本没有扬声器轨 → 变量恒为 null，而按钮处理开头就是 `if (!... || !state.currentScreenObj) return;`。② `startGlobalPlayback()` 只 play 扬声器轨，没 play 成片播放器。③ `switchToScreen()` 更新了选中态却没同步成片播放头。
- **修正原则**：**「当前屏」就是选中的那一屏，无条件赋值**；舞台只有一个播放器时，播放/暂停/换屏都必须驱动它。判定这类问题不要靠肉眼看截图——用 CDP 驱动真实点击，断言 `state.currentScreenObj` 与 `video.currentTime` 的实际变化（实测：`hook-001 → hook-002(t=10.29) → hook-003(t=18.25) → 回 hook-002`，播放后 t 持续推进）。
- **证据**：《图拉斯创新》审阅页，修前 `sel:null` / `paused:true`，修后如上。

## 56. 工程态与交付态的切分只做了一条轴 → 交付过期无人发现

- **module**：`helpers/export_deliverables.py`、`helpers/verify_delivery.py`、项目的 `edit/` 与 `成品/` ｜ **状态**：已复现
- **现象**：交付出去的成片与工程态不一致，**没有任何检查发现** —— 本轮是靠人工抽帧看 181s 才发现"交付的是旧页面"。同批还有：提前渲的 `edit/visual.mp4` 静默躺在 `edit/` 里（随时会被当成当前底片，需手工删）；`beat-06` 的箭头修正被下一次 `ppt_pipeline export` 覆盖回旧版，交付层同样无感。
- **原因**：切分只做了**一条轴** —— `duration_plan.py` 的 `projected` 记录（`references/tools.md`「免渲染的工程态」），`verify_delivery.py` 只认真实渲染、`_edl.render_record` 默认跳过 projected。这条轴是对的，但另外三条没有切：
  1. **介质**：审阅用的「活舞台」与交付用的「渲染成片」（与 #44 同根源）；
  2. **来源版本**：这份交付是从哪一版工程态（composition / 各页 store revision / 导出快照）渲出来的；
  3. **产物归属**：哪些文件属于工程态（可丢、可重算，不得留在 `edit/` 冒充底片）。
- **修正原则**：**交付必须自带来源指纹**。写它的是 `helpers/state_fingerprint.py capture`（默认落 `成品/delivery.json`），记录 composition、`choreography.json`、各页 store revision、音轨、字幕的 sha256 与真实渲染记录；`export_deliverables.py` 只做逐件 `shutil.copy2`，**不写任何指纹文件**，交付不会自动带上指纹。`verify_delivery.py` / `state_fingerprint.py verify` 断言指纹与**当前**工程态一致，不一致即判**交付过期**并拒绝出交付。工程态渲染/预览一律落 `edit/_engineering/`（或显式标注非底片），不进 `edit/` 根。
- **证据**：`05-VideoProject/sparkling-video`：交付后抽帧才发现旧页面；`edit/visual.mp4` 手工删除；beat-06 箭头两次被导出覆盖（一次因为直改 `_internal/02_svg_source` 未入库）。

## 57. 审阅页的护栏是两具尸体 —— 不跑的测试等于没有测试

- **module**：`tests/`、`visual/assets/review-page-template.html` ｜ **状态**：已复现
- **现象**：同一个模板文件连着返工三轮，六类缺陷一起出货，作者一个个手撞出来。而 `tests/` 里**本来就有**两个浏览器测试。
- **原因**：`test_interactive_ui.py` **根本不是 unittest**（没有 `TestCase`），硬编码 `127.0.0.1:8776`，引用的 `#view-player-btn`／`#view-svg-btn` 在模板里已经是 0 次，并且 `playwright` 没装 —— 整个模块导入即失败，`unittest discover` 直接把它算成 ERROR。`test_review_browser.py` 是 opt-in（`VIDEO_CRAFT_BROWSER_TESTS=1`）且同样要 playwright，它自己的 docstring 还写着「**不覆盖**：播放器」。于是舞台这一块零执行护栏。自检常年带着 2 个 ERROR、5 个 skip 在跑，没人看。
- **修正原则**：**默认自检必须全绿，否则护栏等于装饰。** 死测试删掉（它测的元素已经不存在）；跨 Skill 按路径加载的测试要把它自己的 `scripts/` 放上 `sys.path`（否则 `No module named 'canvas_frame'` 让整个模块静默消失）。修完之后默认自检 326(2 ERROR) → 344 全 OK。
- **证据**：`test_interactive_ui` 的 `ModuleNotFoundError: No module named 'playwright'`；`test_snapshot_input` 的 `No module named 'canvas_frame'`。

## 58. 舞台选择函数改写了自己的参数 → 页面永远开在错的舞台上

- **module**：`visual/assets/review-page-template.html::setStageViewMode()` ｜ **状态**：已复现
- **现象**：项目没有合成成片，审阅台打开却是一张「预览 · 合成成片尚未导出」的空占位；唯一写着「返回动效舞台」的按钮点了没反应。**动效舞台永远打不开。**
- **原因**：两个缺陷叠加。① 函数体第一行写死 `mode = "composite";`，把调用方传进来的参数丢掉 —— 连初始化那句 `setStageViewMode("svg")` 也变成切到合成台；而标记里 `#svg-stage-wrap` 带 `hidden`、`#composite-player-wrap` 不带，于是默认就停在空合成台上。② `#btn-back-to-stage` 在模板里出现 1 次，只有标记、没有监听（外加一条已过时的注释声称「初始可见性已在标记里给对」）。
- **修正原则**：**标记给的默认舞台必须是「最不挑数据」的那块**（有分屏就能画的 SVG 舞台），初始化末尾再按项目数据提升到活 composition／合成成片；参数就是参数，不许在函数里改写。删 UI 元素时同时收口它的挂载点（第 54 条的同一条命）。
- **证据**：`check_review_template.py` 的 S1／S2／S3 三条不变量；把缺陷打回去逐条响。

## 59. 字幕退回「整屏字幕」+ 圆角药丸 = 一个圆盖住画面

- **module**：`visual/assets/review-page-template.html::updateStageSubtitle()` ｜ **状态**：已复现
- **现象**：舞台上出现一个巨大的椭圆，里面是整段文字，把画面整个盖住。
- **原因**：游标落在两句之间的空档（或时间轴还在 0 点、没到第一句）时匹配不到 cue，代码退回 `st.caption` —— 那是**整屏所有句子的拼接**。而药丸是 `border-radius: 9999px`，一整段文字塞进去就被撑成一个椭圆。
- **修正原则**：**有字幕契约时不存在这条退路**：匹配不到就什么都不显示。药丸再加一条 `max-width` 封顶，防任何超长串重演。同理，**点一屏只 `seek` 不 `play`**（舞台还停在静态页上）得到的是一张静止帧 —— 用户动作驱动的换屏必须 `play()`，而切舞台、拖进度条的 `seek` 不该自己开始播放。
- **证据**：`check_review_template.py` 的 S5／S6；S6 只查分屏点击处理函数那一段，因为前三处 seek 是正当的。

## 60. `hyperframes preview` 在沙箱下静默不起，而且它的路由只能验内容

- **module**：`helpers/live_stage.py` ｜ **状态**：已复现
- **现象**：`hyperframes preview --background` 退出后 `--status` 说没有后台预览；日志里也没有明显报错。
- **原因**：① 它把状态写在 `~/.local/state/hyperframes`，`workspace-write` 沙箱下这个 mkdir 直接 `EPERM`，预览就没起来。② studio 的地址是 `#/project/<id>` 这种 hash 路由，嵌不了；可嵌入的裸路由是 `/api/projects/<id>/preview/comp/index.html`，而它只出现在 studio 自己的 JS bundle 里。③ 那台服务器对**未知路径一律回 200 + SPA**，所以状态码什么都证明不了。
- **修正原则**：确定性下沉成一个工具：把 `XDG_STATE_HOME` 指到项目内；pin 住裸路由并**验响应体**（stage 过的 composition 会带注入的 `data-hf-gsap-fallback` shim 与 `<base>`）；`--status/--stop/--json` 齐备。这条别在会话里手搓。
- **证据**：`EPERM: operation not permitted, mkdir '~/.local/state/hyperframes/previews'`；裸路由 119263B 带 shim，`/anything` 也回 200。

## 61. composition 用旧时间轴打过补丁 → 过期 3 秒，无人发现

- **module**：`visual/scripts/generate-composition.py`、`timeline/timeline.json` ｜ **状态**：已复现
- **现象**：时间轴从「+3s 平移」改成「与 EDL 对齐」之后，composition 里的 `__CUES__`／`__SPANS__` 还是按旧版打的：`step-open` 的区间停在 14.42s，而时间轴已经说 11.42s。动画锚点整体偏 3 秒。**没有任何检查报错**，`build_review` 还给出一个看起来很一致的页面。
- **原因**：这是第 56 条「工程态/交付态切分只做了一条轴」的第二条轴（**来源版本**）。生成器只管骨架，注入 cue 表是另一步；时间轴一变，注入物就过期，而两者之间没有闸门。
- **修正原则**：**画面轨的唯一源是 `composition/`**，而它的输入是时间轴 —— 时间轴一动就重跑生成＋注入；`generate-composition.py --verify` 的核对要覆盖 `mediaClips` 与逐片时间，别只数 clip 个数。
- **证据**：旧 `__SPANS__.step-open=[0.0,14.42]` vs 新时间轴 `0–11.42`；重跑后逐屏一致。

## 62. 静态检查的两个假阳：对正确代码报红，训练出来的只是忽略

- **module**：`helpers/check_review_template.py` ｜ **状态**：已复现
- **现象**：第一版两条检查对着**正确代码**报红：S2 把工具栏那三个按钮判成死的（它们是 `data-stage-tool` + 一个委托监听，正当写法）；S6 把三处「同步播放头」判成缺陷（切舞台、拖进度条本就不该自动播放）。
- **原因**：判据抓的是「形状」而不是「出问题的那一段」。宽到把正确代码也罩进去的检查，和永远绿的检查一样没用 —— 区别只是它更快地被忽略。
- **修正原则**：每条检查都要能说出**它只对哪一种缺陷响**；S6 因此收窄到只查分屏点击处理函数那一段。并且每条检查必须配一份自证（`--prove`：把历史缺陷从干净基线打回去，检查必须响），否则它可能就是一条永远不会失败的判据（第 30 条）。
- **证据**：收窄前后的两次实跑；`--prove` 七条全响。

## 63. studio 会缓存 composition —— 改了源，你要硬刷新它

- **module**：`hyperframes preview`（studio） ｜ **状态**：已复现
- **现象**：改完 composition（加音频、加钩子、改区间），studio 里还是旧的一版：画面不动、没声音、Lint 计数不变。作者会以为"动画没有"，而实际是**他在看几小时前那份**。
- **原因**：studio 号称"改了自动重载"，但 composition 的响应带 HTTP 缓存。用 CDP 打开时必须 `Network.setCacheDisabled` 才能拿到新的一版；只用 `--status` 看服务活着，完全看不出来。
- **修正原则**：**改了 composition 之后，让作者硬刷新（Cmd+Shift+R）**；判断"服务是不是旧实例"不能只看端口，要看响应内容（`grep` 一下新加的东西在不在）。诊断一律用 CDP 取真实 DOM，不要用截图猜。
- **证据**：同一台服务器、同一个 URL，缓存开时 `__kwStudioHook` 不存在、关掉后 `{"installed":true}`。

## 64. studio 的 player 路由剥掉所有 `src=` 脚本，并把内联脚本拼成一个大脚本

- **module**：`hyperframes preview` 的 player 路由、`visual/scripts/generate-composition.py` ｜ **状态**：已复现
- **现象**：给 composition 加一个 `<script src="assets/xxx.js">` 的钩子，在 studio 里**永远不执行**；同一份文件在 `/preview/comp/index.html` 那条路由上是好的。
- **原因**：两件事叠加。① player 路由只留一个 `src=` 脚本（它自己的 `/api/runtime.js`，GSAP 由它提供），composition 自己声明的 `src=` 脚本全被剥掉 —— 实测 player 文档里的 script 标签只剩 runtime。② runtime 把**内联**脚本拼成一个大脚本执行；我们的钩子虽然内联了，却排在动画那段之后，而它前面一段抛了错，于是永远轮不到它（`hasTimelines: true` 但 `__kwStudioHook: undefined`）。
- **修正原则**：要在 studio 里执行的代码**必须内联**，并且**并进那段已经证明会执行的块**（这里是动画层），不要指望它自己独立跑。反过来，审阅页要用的东西（嵌入桥）走 `src=` 是对的 —— 那条路由不剥。
- **证据**：`grep -o '<script[^>]*src=' player.html` 只有 runtime 一条；钩子文本在文档里（`hasHookText: true`）而全局变量 undefined；并入动画块后 `{"installed":true,"sent":1}`。

## 65. 「第几个脚本」不能当锚点，「第一个内联 script」尤其不能

- **module**：组装 composition 的注入步骤 ｜ **状态**：已复现
- **现象**：往 composition 头部加了一个内联配置脚本之后，那个"把生成器骨架脚本换成 cue 表 + 动画"的步骤**把配置脚本整块替换掉了**：meta 没了、钩子读不到收集器地址，而页面其他地方一切正常。
- **原因**：注入步骤的兜底锚点是"第一个不含 `src` 的 `<script>`"（`SCRIPT_RE`）。这是一个**位置锚点**，任何新增的内联脚本都会把它抢走。位置锚点在多人/多步改动的文件里天生不稳。
- **修正原则**：锚点锚在**内容**上（这里是"那个注册 `window.__timelines` 的脚本"），或者用不会被当成脚本的东西传配置（`<meta>` 而不是内联 `<script>`）。凡是"取第 n 个"的锚点，都要问一句：谁还能往前面插东西？
- **证据**：加配置脚本后 `grep -c kw-studio-notes` 从 1 变 0；改成内容锚点 + meta 后稳定。


## 66. GSAP 握手不证明 HyperFrames 播放正常

旧桥只 seek/play GSAP，runtime 仍拥有 clip 显隐与媒体。真实 keywords 工程在旧路由中多屏同时可见；官方 player 接管后只显示目标屏。审阅用官方 player，不复制动画引擎。验收同时检查画面、声音、录屏和时间，不用 ready 消息替代。

## 67. 不透明源访问 loopback 和跨帧 blob 都可能被拦

浏览器报 `ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS`，脚本没有 pageerror，但嵌入舞台无法加载。用 review-core 传编译工程与资产；player 用 srcdoc。父帧的 `blob:null` 也不能在另一个不透明子帧读取，必须转换为可传递的资产载体。测试不得关闭本机网络访问安全检查来制造通过。

## 68. 编译路由的 base 不是 HTML 路径的父目录

`/preview/comp/index.html` 的 `<base>` 是 `/preview/`。按 HTML 路径拼 `assets/gsap.js` 会拿到 SPA HTML，内联后报 Unexpected token。项目脚本按 composition 本地根读取并核对包含性；runtime 用已验证的同源接口读取，HTML 伪装脚本必须拒绝。

## 69. `hyperframes render --workers auto` 按核数开满 Chrome → 小内存机器被 swap 打崩

- **module**：`references/visual-rendering.md` + `helpers/check_render_env.py` + `SKILL.md` ｜ **状态**：已复现
- **现象**：渲染参数留默认 `--workers auto` 时，`hyperframes render` 按 CPU 核数开满 Chrome 工作进程；核数多于内存预算的机器在渲染中途被拖垮。
- **原因**：`auto` 只看核数，**不看内存**。每个 Chrome 工作进程约占 1.5 GB，6 核就把 8 GB 机器的内存吃穿——这是默认值的稳定后果，不是偶发：换一台同规格机器、用同一条命令必然重演。而文档此前只写「default auto」，全文零资源警告。
- **修正原则**：渲染前先跑 `python3 "<craft>/helpers/check_render_env.py" "<project>/composition"`——它报 RAM、可用内存与 swap，并直接打印这台机器能带得起的 `--workers` 值（两个上限取低：总内存 ÷ 1.5、可用内存 ÷ 1.5，且不超过核数；8 GB 机器上因此 ≤ 2），照它给的值传，不要自己按核数推。**默认从 `--workers 1` 起**；要加并发，先拿 3–5 秒短片段试。审阅期用工程态（`live_stage.py` + `build_review.py`，零渲染），不要拿「先渲一版看看」当开工动作。
- **证据**：9394 帧 / 1920×1080 / 8 GB RAM / 6 核 → 6 个 Chrome 进程 → swap 用满 8.2 GB → 系统崩溃。

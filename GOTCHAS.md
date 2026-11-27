# GOTCHAS

有证据的坑：会稳定导致错误的具体行为。每次开工前读它。

**两条约定。**

1. **每条都写清 `module` 与状态。** 一条 gotcha 一定属于某个 module——优化时按 module 聚类，
   不按发生次数堆规则。状态只有四个：**候选**（有怀疑、还没在真实运行里观察到）·
   **已复现**（真实运行里出现过，且没有机制能兜住它）· **已升级**（后果已有机制兜住，
   剩下的判断住在这里）· **已失效**（不再成立）。加一条之前，先有一次真实运行产生它。

2. **解决了就删。** 一条候选被机制完全接管后，在末尾「已移除的条目」表里留一行指向那个机制，
   然后从正文删掉——机制才是记忆，正文里的第二份 prose 只会烂掉。**`已升级` 的条目移出正文**，
   只在 `references/gotchas-index.md` 的迁移索引里留一行（2026-10-19 起）；正文只留
   **当前仍会造成错误**的条目。每条必须有 `enforcement` 指针，没有执行点的条目不许新增——
   由 `tests/test_gotchas.py` 强制。

**`enforcement` 只有四种类型，各指什么东西**（`tests/test_gotchas.py` 机械核对）：

| 类型 | 指向 | 真的能执行，意思是 |
|---|---|---|
| `check:` | 现行检查脚本 | 跑它，退出码就是这个判据，人不用再判一遍 |
| `test:` | 单测文件 | 判据被钉住，破坏它必红灯 |
| `env:` | 代码路径／工具本身 | 工具的行为让这个错误做不出来，或一做就出声 |
| `judgment:` | 文档或代码里的具体一处 + **看什么** | 没有自动判据；照「看什么」去看一件可观察的事 |

`check:`／`test:`／`env:` **指到 `.md` 上等于没有执行点**——文档不能跑。只能靠人判断的一律
`judgment:`，并且必须写出 `— 看什么：…`，说清看哪儿、看到什么算错。目标写**路径 + 章节/函数名**，
不写行号（行号会被别的包改走）。层级统一为 `## n. 标题`。编号不复用。

末尾两节：**「已移除的条目」**（编号与保证现在住在哪里）和**「这个文件不收什么」**。

## 1. Word-level timing must come from SeedASR 2.0

**module**：helpers/_internal/transcribe_seedasr.py + helpers/_internal/transcribe.py（转写后端与听辨防误剪）　｜　**状态**：已复现
- **enforcement**：judgment:references/captions-and-audio.md — 看什么：「1. 转写与听辨铁律」：`transcripts/<source>.json` 的 token 是不是词级（一句一个 token 就是走错了后端）；长块边缘约 3s / 5–7s 处的词界是否被拉松；删词或采信专名前是否经过第二后端交叉比对与音频听辨；对称位置怪词是不是 ASR 脏话打码。

The Ark `doubao-seed-2.0-lite` path is a generic multimodal LLM, not a reliable
ASR: it drifts 0.5–2 s, garbles fast Chinese, and hallucinates words in silence.
Long chunked requests degrade additionally near chunk edges (roughly the first
3 s and the last 5–7 s of each chunk), and no chunk-size tuning removes that.
Use `transcribe_seedasr.py`. Local `mlx_transcribe.py` is the last resort — it
keeps fillers verbatim but drifts ±0.3 s and drops punctuation.

**同根并入**（#2 / #3 / #42 对称打码防误剪）：

- **双引擎分歧是信号，不是噪声**（原 #2）：删词或采信专名前，把该窗口用第二个后端再转一遍，逐词比对字面与 `start/end`。两版不一致就回音频听辨——既能修出 `关线`→`关键`、`Chatbox`→`Chatbot` 或被 ASR 拆半的词，也能分辨说话人自己的口误。
- **能列模型不代表账号能调用**（原 #3）：Volcengine 模型列表与 Ark LLM key 不能当语音控制台 `APPID/token` 用；ElevenLabs Scribe 的配额预检仅作参考，真实上传仍可能返回 401。接入前用真实短音频试打端点，以真实上传响应为权威并保留显式回退。
- **ASR 对称打码防误剪**（原 #42 并入）：SeedASR 会把敏感词静默打码成「嗯 / NR」，且不报错不留标记，在重复遍数的同义位置对称出现（如「什么嗯啊是嗯啊的洞察」与「什么 NR 的是 NR 的洞察」）。切勿当成口误直接删剪音频；判据是同义位置对称出现，修法是在 `edit/caption_corrections.json` 按 `transcript_index` 还原原文，保留原音频与剪点（拿不准时字幕写通顺保守版并在交付说明点出）。

## 4. Hiragino Sans GB has no ✓/✗

**module**：helpers/frame.py 与 PIL 卡片管线 + references/visual-checks.md　｜　**状态**：已复现
- **enforcement**：judgment:references/intake-and-frames.md — 看什么：字体回退那一条：抽一帧看 ✓／✗／☑ 是不是同一个带叉方框；符号的 mask 与 notdef 相同即不可用。

`U+2713 ✓`, `U+2714 ✔`, `U+2717 ✗`, `U+2718 ✘`, `U+2715 ✕` and `U+2611 ☑` all
render as the same notdef tofu box — a rounded square with a crossed rectangle,
which reads as a *rejection* mark. `U+221A √` and `U+00D7 ×` are real glyphs.
Check any symbol by comparing its mask against notdef before shipping it in a
PIL card.

## 6. A claim must match the evidence behind it

**module**：SKILL.md 与 stages.md 的判断类规则（跨 module）　｜　**状态**：已复现
- **enforcement**：judgment:references/stages.md — 看什么：「10. 核验与严格交付」的完成标准：每条结论点名命令与它实际量的属性；一个绿灯不许替另一个属性背书。

Say what was directly verified, and by which command; never let a passing check
stand in for a different property. The gates do not imply one another:

- `check_edl.py` — the cut is legal and the SRT sits on the render's timeline;
- `check_overlay.py` — every overlay can actually be composited;
- `verify_av.py` — the rendered file's tracks and its tail;
- `verify_delivery.py` — the DELIVERED artefacts, byte-identical to the working
  files;
- `helpers/film.py verify <project>` — `storyboard.json` (or legacy `visual-plan.json` / `pages/`) schema is valid.
  It says **nothing** about whether the motion scene compiles or passes visual quality: Remotion typecheck, frame sync, mid-segment stills, and layout safety belong to `helpers/check_visual.py` / `helpers/_internal/remotion_gates.py` (or `hyperframes check` on frozen legacy projects).

An exception is not evidence of a diagnosis: "it worked last time" proves
nothing about an intermittent failure.

## 11. Multi-round loops must be flattened into one step sequence

**module**：references/visual-grammar.md（组成品写作顺序）　｜　**状态**：已复现
- **enforcement**：judgment:references/visual-grammar.md — 看什么：「4. Remotion 4 场景写作硬规（含历史 HyperFrames 只读兼容边界）」与 `check_motion`：多轮动效要核第二轮与最后一轮，不只看首中尾三张图。

A two-round page flip written as nested loops left round 1's last card on top —
the animation looked stuck on one page (2026-09-21, found by the author). Compute
one flat step index `s`, show `s % N`, and explicitly push down `(s-1) % N`. Never
let a second round rely on the previous round having cleaned up.

## 12. Composition assets must be enumerated from the real files

**module**：references/visual-grammar.md（资产清点）　｜　**状态**：已复现
- **enforcement**：judgment:references/visual-grammar.md — 看什么：「4. Remotion 4 场景写作硬规（含历史 HyperFrames 只读兼容边界）」与出片前 `stills` / `snapshot`：资产清单是不是从真实目录枚举生成，并逐格看有没有内容。

Thumbnail paths were generated as `%02d_cover.png` when only the first page was
named `cover`; 20 of 21 tiles rendered empty and the encode still succeeded. Build
asset lists from `glob()` on the actual directory and eyeball a `snapshot` frame —
a green render is not a picture with content in it.

## 18. A review copy needs sound, a visible save state, and per-round archiving

**module**：references/review-and-delivery.md（审阅页的硬约定）　｜　**状态**：已复现
- **enforcement**：judgment:references/review-and-delivery.md — 看什么：「1. 两种审阅面与横竖屏自适应构建模式」及「媒体解析与公共宿主接口」：审阅副本有声（含声景与底噪开关）、保存时间常驻且能手存、`feedback/*.round-N.json` 里躺着上一轮。

Three separate complaints in one session, all about the review artefact rather
than the film: the visual slices were `<video muted>` so the author could not judge
sync; auto-save worked but its indicator was a line in the corner, so the author
reported the feedback as lost; and the page reloaded the previous round's notes and
re-saved them with the new ones, making six old comments look like six new ones.
Mux the voiceover (and Visual Soundscape when present) into the review copy; for
delivery, the visual leg carries Visual Soundscape when present and stays silent
only when no soundscape is needed. Keep a sticky saved-at indicator plus a manual
save, and archive the feedback file as `<name>.round-N.json` before opening a
fresh round.

## 19. Loudness and true peak are measured on the DELIVERED file, in stereo, whole-program

**module**：helpers/_internal/verify_av.py + helpers/_internal/audio_diag.py　｜　**状态**：已复现
- **enforcement**：judgment:references/captions-and-audio.md — 看什么：「4. 双轨音频分离：Voice Polish（人声润色）与 Visual Soundscape（画面声景）」 + **交付件**上跑 `ffmpeg -i 交付.mp4 -filter_complex ebur128 -f null -`，读 I 与 True peak 两个数；`audio_diag` 的 mono 读数不算。

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
  of headroom at the source (-1.8 dBTP was the value that held).
- **A mid-chain sample-rate change spends the headroom.** loudnorm left the chain
  at 96 kHz while the concat forced `-ar 48000`; the resample cost a further
  step. **Lock one sample rate through the whole chain** (`-ar 48000` at every
  stage).

## 52. 编码产物不要直接写进云同步目录

- **module**：`visual/scripts/encode_transparent.py`、`helpers/_internal/preview_layers.py`、`helpers/montage.py` ｜ **状态**：已复现
- **enforcement**：env:helpers/montage.py
- **现象**：把视频/合成成片或长编码直接写入 OneDrive 等云同步目录，长任务跑到一半会报 `Error writing trailer: Operation timed out` / `Error closing file`，留下 0 字节文件而命令表面只像「慢」；云同步目录里刚新建的目录也可能在下一个进程静默不可见。
- **修正原则**：**凡是耗时写盘、关键帧抽取、转码或成片渲染，一律先写到本地 `/tmp`（系统临时目录），校验非空有效后再原子移入目标云同步目录**；在云同步盘新建目录后立即二次验证可见性，不可见则显式报错，绝不静默产出 0 个切片。

## 71. 合成给「每一步」发一个媒体 clip，而各步不首尾相接 → 成片里成段黑帧

- **module**：`remotion/src/`（及历史兼容 `composition/src/`）+ `helpers/_internal/verify_delivery.py` ｜ **状态**：已复现
- **enforcement**：check:helpers/_internal/verify_delivery.py
- **现象**：成片在每次「切换」的位置出现黑帧。实测一份 311s 的片子里 37 处步间空隙、合计 12.51s（占 4.0%），`blackdetect` 扫出 39 段；而字幕门、静音门、时长门**全部通过**——是作者肉眼看片发现的。
- **原因**：生成器给每一步发一个时长正好等于该步时长的媒体 clip，而步与步之间并不相接（`timeline_derive.py` 的 step 边界取自首/末 cue，cue 之间存在 0.2–0.7s 的真空隙）。空隙里画面区没有内容，渲染出来就是黑。对**连续**素材（录屏、长镜头）尤其致命：源本来一直在，是排版把它切出了洞。
- **修正原则**：连续素材用**一条贯穿全片的媒体 clip**，不要按步骤切；被上层不透明 clip（画面页、截图）覆盖的窗口不必挖洞。判据落在 `verify_delivery.py` 的 `--max-black`：**累计纯黑秒数预算**（默认 2.0s）而不是「有黑帧即失败」——深色设计的片子天然含近黑帧，逐帧判黑会做成恒真告警。报出的黑段要能区分「源素材当时就是黑的」（正常）与「本该有画面却是黑的」（缺陷）。

## 82. 命令末尾接管道，退出码就不是渲染器的了（含 ffmpeg 参数次序与 `-o` 命名防错）

**module**：SKILL.md 与 helpers/_internal/render.py（终端执行与参数防错铁律）　｜　**状态**：已复现
- **enforcement**：judgment:references/tools.md — 看什么：「4. 渲染环境、一致性检查、包装与交付指纹」那节的命令：末尾没有 `|`，`echo $?` 拿到的是渲染器自己的退出码而不是 `tail` 的；多输入 ffmpeg `-t` 写在所属 `-i` 之前；`--no-loudnorm` 的 `-o` 不取 `base*.mp4`。

`render.py … 2>&1 | tail -12` makes the shell's exit status come from `tail`, not
from the renderer: an ffmpeg failure or a raised exception still reports
`exit code 0`, so "the render succeeded" is fiction. **No pipe when the exit code
matters** — redirect to a file and read the tail separately.

**同根并入**（#83 / #84）：

- **`-t` 写在两个输入之间，属于第二个输入**（原 #83）：ffmpeg 的输入选项作用于**它紧随其后的** `-i`。每条输入各自的截断时长写在所属 `-i` 之前；要截的是**输出**总长才写在所有输入之后（`helpers/_internal/render.py::extract_segment` 依此排布，手搓命令严禁把 `-t` 错挂到下一条输入）。
- **`--no-loudnorm` 时 `-o` 撞上内部 base 名，读和写就是同一个文件**（原 #84）：`render.py` 内部汇合点占用 `edit/base.mp4`、`edit/base_preview.mp4`、`edit/base_draft.mp4`。默认路径会经 `*.prenorm.mp4` 中转，但传 `--no-loudnorm` 时第 4 步直接覆盖 `-o`；因此 `-o` 必须取成品级或工程态路径（如 `person_master.mp4` / `final.mp4` / `edit/_engineering/cut.mp4`），严禁占用 `base*.mp4`，且 `--no-loudnorm` 仅用于确已由 `audio_mix.py` 预混的音轨。

## 已移除的条目，以及保证现在住在哪里

Kept as a subtraction audit trail, so a future session can tell a deliberate
deletion from an accidental loss. 已淘汰、已固化到门禁、或已同根合并的历史编号全部登记在
`references/gotchas-index.md`。

| Removed gotcha | Now guaranteed by |
|---|---|
| Transparent overlays silently composite a black base (WebM/VP9 alpha) | `check_overlay.py` + `render.py` + `helpers/_internal/check_alpha.py` |
| Chunked doubao degradation at chunk edges | merged into #1 |
| Transcript quality + content understanding precede the EDL | SKILL.md process step 2 |
| A transcript change invalidates every old EDL boundary | `check_edl.py` cut-inside-word failure |
| Segment caches are content-blind | content-keyed cache (`clips_<tag>/manifest.json`) |
| EDL word gaps do not prove rendered pauses are within target | `check_edl.py --max-pause` |
| Multi-track sources upload the wrong audio track | `transcribe.py` cache key + silence guard |
| A multi-source render probes frame rate per segment | `render.py` resolves one rate for the whole render |
| A stale preview server serves the wrong project | 已升级，见迁移索引 #8 |
| A rendered animation is silently a still image | `check_motion.py`；创作顺序已升级，见迁移索引 #9 |
| Process words (加速/静帧/裁切…) drawn on screen | `check_screen_text.py`；判断已升级，见迁移索引 #16 |
| Captions packed to a character ceiling | `check_caption_breaks.py`；判断已升级，见迁移索引 #17 |
| A torn segment reaches the film and the render exits 0 | `render.py` `check_segment` + `check_total_duration`；见迁移索引 #25 |
| The gates read the POC's render record | `_edl.select_render_record` by EDL hash；见迁移索引 #26 |
| Cloud-synced video folders / fresh directories in the sync root | merged into #52 |
| HyperFrames 冻结只读旧引擎条目（#10 / #48 / #50 / #61 / #63 / #70 / #74 / #79） | v3 切换 Remotion 4 主引擎，已整体迁入 `references/gotchas-index.md`（2026-11-27） |
| 2026-11-27 40→10 精准清淤：6 条旧路线/旧引擎（#24/#40/#41/#44/#45/#49）、9 条旧审阅页模板修复（#33/#34/#47/#53/#55/#57/#58/#59/#62）、11 条已接管脚手架门禁（#7/#13/#21/#42/#43/#56/#73/#75/#78/#80/#81） | 全量按原编号迁入 `references/gotchas-index.md`（2026-11-27 清淤迁移索引） |
| 2026-11-27 40→10 同根合并：#2/#3 并入 #1；#83/#84 并入 #82 | 症状与规则并入宿主条目，合并记录见 `references/gotchas-index.md` |

## 这个文件不收什么（附理由）

下面几类看起来像 gotcha、但**故意不收**。写在这里是为了让下一个人不用重新判一次。

| 不收的类别 | 为什么 | 例子 |
|---|---|---|
| **一次性的规格缺失** | 它是「这个 Skill 还没写清」，不是「会稳定导致错误的具体行为」。修法是补那份规格，补完就没有候选了 | 上游契约要一个新字段而我这边没读；某份 reference 少了一节 |
| **已经修好的环境与脚手架** | 它是一次性事实，不是行为。留着只会让人以为还要处理 | 本机没有 `uv`、`<skill>/.venv` 是空壳、Python 下限被写成 3.10、`install.md` 里的 `uv sync`——统一解释器之后全部失效，见 `gotchas-index.md` |
| **别的 Skill 的问题** | 记在这里会被当成我们的待办；它的 owner 在那边 | `planners-ppt-hell` 的模板库锁层、`init` 的 `--assets` 路径口径、`validate_svg_layout.py` 把出画布降级成 info、两套审阅面不能互操作（作者已裁定不合并） |
| **作者已裁定接受的设计** | 它已经是一个决定，不是待修的缺陷。重复登记等于每轮重新讨论一次 | 两个审阅面不合并；`--assets` 与契约引用必须全等；审阅服务端口被占就报错退出；重渲会改变已交付文件的字节（见迁移索引 #24） |
| **一次运行的偶发失败** | 没有稳定复现路径的偶发失败只写现象是噪音。要收就先做一次可复现的（#52 的两次记录就是这么来的）。**边界：由默认值稳定复现的资源事故不属于这一类**——只要用了那个默认值、在那台机器上就必然发生，它是「会稳定导致错误的具体行为」，收进正文（见迁移索引 #70） | 「这次 ffmpeg 卡住了」而没有复现步骤 |
| **可以从代码/文档一眼查到的事实** | 缓存不是记忆。文件里写着的，指针就够了 | 某个脚本的 CLI 参数、某个目录的形状、某条判据的阈值 |
| **同一根因的第二张脸** | 根因合并成一条；另一张脸在正文里当实例写，不另立条目 | 坏段「静默少一段」与「未捕获崩溃」是同一条（已升级，见迁移索引 #25）；`--prove` 绿灯与「composition 渲染不出来」不是两件事，是 #6 的一个实例 |

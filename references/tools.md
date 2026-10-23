> 本手册只列**现行 recompose 路线**的命令、参数、产物与失败信号。page 路线的命令见 [legacy-page-route.md](legacy-page-route.md)。

> **查 HyperFrames 的 `data-*` 契约与属性名，不要 grep 打包后的 CLI。**
> `node_modules/hyperframes` 是几万行压缩后的 bundle：一次 `grep -rn` 就会把 100KB+ 的
> 中间代码灌进上下文，而且线上属性名与源码里的标识符并不一一对应，读到的多半是噪音
> （2026-10-21 实测两次，全部浪费）。正确做法按顺序：
>
> 1. `hyperframes <cmd> --help` —— 契约参数就在里面（例如 `check --help` 列出
>    `--range` / `--at` / `--caption-zone` / `--frame-check` / `--layout`）；
> 2. `hyperframes check --json` —— 真实加载后的 findings 与 DOM 事实（`runtime.duration`、
>    `contrast.checked`、finding 的 `code` / `selector` / `dataAttributes`）；
> 3. `hyperframes docs` 与该版本的官方文档；
> 4. 本 Skill 的 `references/`：`composition-craft.md`、`composition-facts-contract.md`、
>    `live-stage-contract.md` 写的是已经踩过的契约，不用再从 bundle 里反推；
> 5. 还确认不了就做最小实验：写 3 行 fixture composition，跑一次 `check --json`，或在
>    预览服务上用 CDP 读真实 DOM。**不要读打包后的源码。**
>
> 例外：`visual/assets/` 下本 Skill 自己的脚本（`svg-anim-engine.js`、`composition-embed-bridge.js`）
> 不是打包产物，可以正常读。

## 日常调用与诊断边界

| 任务 | 日常入口 | 何时下钻 |
|---|---|---|
| 剪辑准备、出逐字面、应用选择 | stage_cut；取舍后用 edl_from_keep / edl_edit 建或改 EDL | 定位转写、EDL、表面回执的问题时 |
| 时间与字幕 | duration_plan / srt_export / timeline_derive；外部来源用 import_srt_timeline | 尚无统一 time 命令，按 stages 5–6 顺序调用 |
| 原页拆解与画面 | film / recompose_plan；模型写 composition | 检查具体映射或场景 |
| 动效审阅构建 | review.py | check_live_stage/live_stage/build_review/review_surface/check_review_playable 是内部步骤，仅定位故障时单跑 |
| 正式反馈收件 | review_inbox.py | 它不包含在 review.py 内；拒收先解决绑定 |
| 成片合成、严格核验、包装、指纹 | deliver → verify_delivery → 按需 export_deliverables → state_fingerprint | 顺序与适用限制见 delivery.md；stage_deliver 是兼容的分动作入口 |

私有库（下划线文件、helpers/lib、live_preview）由工具调用。扩展参数查 --help；维护工具时可以读实现，日常制作先用入口与报告定位。

## recompose 主路线（composition 为源）

```bash
python3 "<craft>/helpers/recompose_plan.py" init "<project>" \
    --composition "<project>/composition" --draft "<project>/recompose/draft.mp4" \
    --person-slot "0,0,620,1080" --caption-safe "0,885,1920,195"
python3 "<craft>/helpers/recompose_plan.py" check "<project>"
python3 "<craft>/helpers/recompose_plan.py" lines "<project>"

python3 "<craft>/helpers/review.py" "<project>"                  # 构建并验证工程审阅
python3 "<craft>/helpers/review_inbox.py" "<project>"               # 密度记录落到 feedback/density.jsonl
```

recompose 不调用 `import_svg_page.py`、`generate-composition.py`、`auto_choreography.py`，也不跑 `check_parity.py`。
产物：`recompose.json`、`recompose/lines.json`。密度以**口播逐字稿的行**为单位，提交走现有审阅面；
`review_inbox.py` 校验后回写 lines，agent 只改受影响视觉段。完整说明见 [recompose-mode.md](recompose-mode.md)。
page 十步路线已归档（见 [legacy-page-route.md](legacy-page-route.md)）；新项目一律走 recompose。

# 工具调用手册

七个职责阶段对应的 11 步做什么、按什么顺序、坏了怎么认，见 [stages.md](stages.md)；本页只回答"跑哪条命令"。

按任务选入口，不逐个跑完。本页的 `<craft>`、`<idea>`、`<ppt>`、`<core>` 分别替换为对应 Skill 的绝对根目录；`<project>`、`<edit>`、`<pages>` 是项目、剪辑目录与 PPT Hell 画面项目。Python 用安装时确认的解释器；每条 Python 命令都可将 `python3` 换为该解释器。扩展参数用该命令的 `--help`，不读实现。

## 文件在哪里

| 位置 | 拥有的内容 | 下一消费者 |
|---|---|---|
| `_idea/current.md`、`deliverable/` 或 `input/` | Idea 的作者决定、脚本、内容契约、资产与制作说明 | Craft 承接；原始内容版本保留 |
| `<pages>/_internal/02_svg_source/`、`design_direction.md` | PPT Hell 的 SVG、可选稳定 id、可选合成提示 | film 原页拆解与动画；新项目不走 page 导入器 |
| `edit/project.md`、`production-plan.md` | 本次采用版、输入路径、当前决定和计划 | 制作、恢复与交接 |
| `edit/transcripts/`、`takes_packed.md` | 转写缓存、Take 阅读视图 | EDL 编辑和字幕 |
| `edit/edl.json`、`segment_durations.json` | 剪辑决定与该版底片实测记录 | 渲染、字幕与核验 |
| `edit/captions_article.txt`、`semantic_lines.txt`、`caption_lock.json` | 字幕校对与断句决定 | `srt_export.py` |
| `edit/caption_words.json`、`captions.json`、`subtitles.srt` | 字幕字级插值、cue 与导出视图；真实词锚点用 align/transcripts | 时间绑定、画面审阅、合成 |
| `timeline/grouping.json`、`content-alignment.json`、`timeline.json` | 屏/Beat 对齐、cue 分组与唯一视觉时钟 | 手写 composition 与审阅 |
| `composition/`、`edit/overlays/` | 渲染源与已渲染视觉层 | 渲染器、EDL 合成 |
| `review/`、`feedback/` | 页面、surface、提交、独立草稿、收件后反馈 | 宿主只传输，Craft inbox 解释 |
| `edit/verify/`、`creative-check.md`、`成品/` | 实际编码结果检查与交付 | 用户与下轮恢复 |

## 现有阶段适配器（覆盖有限）

stage_cut 提供分动作编排：prepare 没有 EDL 时只完成转写打包并指回模型取舍；apply 写选择消费回执并重建逐字页，相同选择重试不再次剪 EDL。status 区分文件存在、内容是否当前与人的确认。stage_deliver run 调用 deliver 并聚合严格核验，包装后仍需核副本；各动作和下一步不代替作者批准。

```bash
python3 "<craft>/helpers/stage_cut.py" status  --project "<项目>"
python3 "<craft>/helpers/stage_cut.py" prepare --project "<项目>" [--source "<原始视频>"]
python3 "<craft>/helpers/stage_cut.py" review  --project "<项目>"
python3 "<craft>/helpers/stage_cut.py" apply   --project "<项目>"

python3 "<craft>/helpers/stage_deliver.py" status  --project "<项目>"
python3 "<craft>/helpers/stage_deliver.py" run     --project "<项目>" [--render] [--visuals …] [--no-person]
python3 "<craft>/helpers/stage_deliver.py" verify  --project "<项目>" --video "<成片>"
python3 "<craft>/helpers/stage_deliver.py" export  --project "<项目>" [--out "<目录>"]
python3 "<craft>/helpers/stage_deliver.py" fingerprint --fingerprint-action capture --project "<项目>"
```

现有画面来源缺记录时，人工核对后可用 `deliver --visuals <视频> --visuals-confirm-current`（stage_deliver run 同名选项）。不确认则显式 --render 重新生成，不能靠改 mtime 放行。

退出码：0 动作完成（status 只表示查询成功）· 1 命令失败（含闸门拒绝）· 2 前置条件不满足。加 `--json` 得到 `steps` 与 `next`。
阶段职责与现有实现覆盖，见 [stages.md](stages.md)。

## 接上游

```bash
node "<idea>/scripts/check-handoff-artifacts.mjs" --project "<上游项目>"
python3 "<craft>/helpers/check_script_hash.py" "<project>" --script "<包>/script.md" --plan "<包>/visual-plan.json"
```

Idea 检查只核文件和素材，不代替作者决定。参考页**不导入**：用 `film.py` 拆解原页（见「SVG 与视觉时间」），页面只作视觉参考。
`import_svg_page.py` 属 page 路线，只在复活旧项目时读 [legacy-page-route.md](legacy-page-route.md)。内容契约 5.0 为当前接口，4.0 仅兼容已有项目。

## 声音与剪辑

从 keep list 建 EDL（剪点自动吸附实测静音）：

```bash
python3 "<craft>/helpers/edl_from_keep.py" "<keeps.json>" --edit-dir "<edit>" --snap-tol 0.35
```

把人声与 BGM 合成一个混音（唯一混音出口）：

```bash
python3 "<craft>/helpers/audio_mix.py" "<voice.wav>" -o "<mix.wav>" --bgm "<bgm.wav>" --bgm-lufs -32
```

```bash
python3 "<craft>/helpers/transcribe.py" "<原始视频>" --edit-dir "<edit>" --audio-track 0 --backend auto
python3 "<craft>/helpers/transcribe_batch.py" "<素材目录>" --edit-dir "<edit>" --workers 4
python3 "<craft>/helpers/pack_transcripts.py" --edit-dir "<edit>"
python3 "<craft>/helpers/refine_transcript.py" "<edit>" --source <source> --asr <词级ASR.json>
python3 "<craft>/helpers/check_edl.py" "<edit>" --max-pause 0.8
```

转写会读取缓存；云端后端会上传声音并可能收费，先沿用作者已授权配置。离线选 `--backend mlx`。多音轨先核声音，`--audio-track` 是从零起的音轨索引。EDL 字段及多轨合成见 [composition-craft](composition-craft.md)。

**转写粒度是剪辑页的前提。** `edl_preview.html` 一个可选项对应 `transcripts/<source>.json` 的一个 token；如果这份文件是「一句一个 token」，页面只能整句删。出现整句 token（>1.5s）先跑 `refine_transcript.py`：它保留确认稿文字不变，用词级 ASR + `takes_packed.md` 的短语锚点补出字/词级 `start/end`；页面构建时也会对粗粒度转写报警，不再静默出整句选择器。`render_cut.py <edl> -o <mp4> --quality draft` 只作快预览，不记录实测时长，不替代正式渲染路径（见「渲染、核验、包装」）。

应用作者在逐字剪辑面上的选择（只改 EDL，不渲染）：

```bash
python3 "<craft>/helpers/apply_selection.py" "<edit>"
```

按时间区间改词，并断言实际文字：

```bash
python3 "<craft>/helpers/edl_edit.py" "<edit>" --delete "<起秒>,<止秒>=<期望原话>|<原因>"
python3 "<craft>/helpers/edl_edit.py" "<edit>" --restore "<起秒>,<止秒>=<期望原话>"
```

多人、多机位、音质或素材定位按需调用：

| 任务 | 调用 | 输出/用途 |
|---|---|---|
| 双机位对齐 | `python3 <craft>/helpers/measure_offset.py <主机位> <副机位> --anchors 10 40` | 实测 offset，供镜像 EDL |
| 派生副机位 | `python3 <craft>/helpers/mirror_edl.py <edl> -o <副EDL> --source CAM2 --path <副机位绝对路径> --offset <秒>` | 同剪点的第二机位，不重写独立取舍 |
| 音质诊断 | `python3 <craft>/helpers/audio_diag.py <媒体> --json` | 指标/问题，先诊断再处理 |
| 音质处理 | `python3 <craft>/helpers/audio_fix.py <媒体> -o <处理.wav> --target-lufs -16.5` | 新音频；原件保留 |
| 替代 ASR | `python3 <craft>/helpers/transcribe_seedasr.py <视频> --edit-dir <edit>` | 豆包词级转写；需对应凭据 |
| 本地 ASR | `python3 <craft>/helpers/mlx_transcribe.py <视频> --edit-dir <edit>` | 本地转写；需 MLX 模型 |
| 调色 | `python3 <craft>/helpers/grade.py --help` | 选适合本项目的预设/参数，调用输入与 `-o` 输出 |
| 素材联系图 | `python3 <craft>/helpers/timeline_view.py <视频> <起秒> <止秒> -o <filmstrip.png>` | 声音/帧联合定位，供剪辑取舍 |

`doubao_asr_file.js` 是 SeedASR 的内部传输实现；`_edl.py`、`_words.py`、`_probe.py` 与 `helpers/lib/` 是库模块，不是 Agent 操作入口。`screen_detect.py` 是视觉场景检测库；需要它的策略与参数时由 `timeline_view.py --help` 选择公开能力，不直接导入内部函数。

## 免渲染的工程态（先审后渲）

审阅的**唯一公共入口是 `review.py`**；本节的 `check_live_stage` / `live_stage` / `build_review` / `review_surface` / `check_review_playable` 是它的内部步骤，只在调试或需要持久舞台时单跑（模块归属见 architecture.md）。

渲染不再是「能开始干活」的前提。段时长可以解析算出来，覆盖层可以有浏览器可合成的载体，
**画面可以直接演活的 composition**，于是剪辑、字幕、时间脊柱、审阅都先跑起来，确认后才渲染。

审阅台的首选舞台是**活的 composition**：`live_stage.py` 起 HyperFrames 预览服务并给出可嵌入地址，
`build_review.py` 把它写进 `media.liveStage`，页面 iframe 进去直接演。不需渲整片；改源后重新构建审阅快照，再刷新才反映本轮修改 —— 这一条见 [stages.md](stages.md) 第 8 步与 `GOTCHAS.md` 第 57–59 条。

```bash
python3 "<craft>/helpers/check_live_stage.py" "<project>" # build_review 前必过：活舞台契约
python3 "<craft>/helpers/live_stage.py" "<project>"       # 起服务 → 打印可嵌入地址（--stop 停）
python3 "<craft>/helpers/duration_plan.py" "<edit>"       # 解析预演（frame-quantised, projected）
python3 "<craft>/helpers/review_copy.py" "<成片>"         # 审阅副本：保时间；先保原生像素，压不进再降分辨率
python3 "<craft>/helpers/review_copy.py" "<成片>" --no-downscale  # 不允许降分辨率：压不进就失败
python3 "<craft>/helpers/review_copy.py" "<composition 里 muted 的 video>" --no-audio  # 去重复音轨
python3 "<craft>/helpers/review_copy.py" "<旁轨.m4a>"     # 纯音频也吃：降单声道
python3 "<craft>/helpers/review_copy.py" "<成片>" --gop 0 # 不切片的副本别锁每秒关键帧（体积差 4 倍）
# 活舞台的代理由 build_review.py 自动生成到 review/proxies/，不需要手工跑上面这几条
# 降分辨率会写进 review_data.json 的 mediaNotes（scaled/scale），页面据此说明是代理
python3 "<craft>/helpers/review.py" "<project>"           # 一条命令出审阅页（内部完成编译→构建→surface→运行时判据）
python3 "<craft>/helpers/check_review_playable.py" "<project>"  # 退 0 才能交给作者：能播/有画面/有声音
python3 "<craft>/helpers/review_slices.py" "<project>"    # 按步切片，页面只取当前窗口
python3 "<craft>/helpers/preview_layers.py" "<edit>"      # 已有 alpha 层补一份 WebM(VP9+alpha)
python3 "<craft>/helpers/check_review_template.py"        # 审阅页模板的静态不变量
python3 "<craft>/helpers/studio_notes.py" "<project>"     # 收集 studio 里写的意见 → jsonl
python3 "<craft>/helpers/studio_notes.py" "<project>" --tail 20   # 读回来
python3 "<craft>/helpers/render_layer.py" "<composition>" -o "<层主干名>" \
    --variables '{"set":"bolt"}'                          # HTML composition → MOV + WebM
```

**studio 的意见要收成文件。** studio 的「Describe a change to the agent」只把一句写好的
prompt 放进**剪贴板**（`navigator.clipboard.writeText`）—— 你不粘回对话，它就没了。
`studio_notes.py` 起一个只监听回环的收集器；composition 里那段钩子（由生成器随包内联）
与 studio **同源**，所以它能包住 studio 的 `writeText`：剪贴板照旧，同时把内容 POST 进
`edit/_engineering/studio-notes.jsonl`。落盘之后用 `--tail` 读，别让作者当传话筒。

`live_stage.py` 封着三件必须由确定性工具承担的事，别在会话里手搓：沙盒下 `hyperframes preview`
写 `~/.local/state` 会 EPERM 而**静默不起**（它把 `XDG_STATE_HOME` 指到项目内）；studio 的 hash 路由
不可嵌入，要换成裸路由 `/api/projects/<id>/preview/comp/index.html`；以及那条路由必须**验内容**而不是
验状态码 —— 这台服务器对未知路径一律回 200 + SPA。

**动效的源是 composition，不是那段视频。** `render_layer.py` **capture 一次**、再由
`encode_transparent.encode_sequence()` 编出两份载体：`.mov`（PNG-in-MOV，无损 RGBA，给 ffmpeg
合成成片）与 `.webm`（VP9+alpha，给浏览器——审阅页唯一能自己合成的带 alpha 载体）。同一次
capture，所以预览与交付不可能各走各的；分格式各渲一遍既慢又给了两者漂移的机会。

移植既有逐帧动效时注意第 49 条（PIL 与 CSS 旋转方向相反）与第 50 条（viewport meta 不能漏）。

编码一律**先写本地再搬入**目标目录（第 52 条）。已存在的视频层补 WebM 用
`preview_layers.py`；新做的层直接从 HTML 出。

`duration_plan.py` 写的记录带 `"projected": true`。它**可以**支撑字幕、时间脊柱与审阅页，
但**不是交付证据**：`_edl.render_record` 默认跳过它，所以 `verify_delivery.py` 永远拿真实
文件对真实渲染；交付前取得真实实测记录后，按下节显式升级字幕与 timeline。

`preview_layers.py` 产出的 `.webm` 只服务预览，交付合成仍走 MOV。审阅页据此在成片上叠层，
所以改一层不必重渲整片。

## 语义字幕

```bash
python3 "<craft>/helpers/srt_export.py" "<edit>" --prepare
```

校对生成的 `captions_article.txt`，写 `semantic_lines.txt`，按 [caption-article-first](caption-article-first.md) 保持正文字符一致，再分别运行：

```bash
python3 "<craft>/helpers/srt_export.py" "<edit>" --lock
python3 "<craft>/helpers/srt_export.py" "<edit>" --build
python3 "<craft>/helpers/srt_export.py" "<edit>" --check
python3 "<craft>/helpers/check_caption_breaks.py" "<edit>/subtitles.srt" --json
```

旧项目或预演升级实测时，显式运行 `srt_export.py <edit> --prepare --force-prepare --time-source measured`，再分别 lock、build、派生 timeline 与 check。`--time-source` 支持 auto/projected/measured/nominal；缺有效当前 EDL 指纹/段数的 measured 记录会失败，不降级。force-prepare 保留 semantic_lines 已审文字，需核对其覆盖范围。

输出 article/词契约/lock/cue/SRT。底片剪点变化后重新 prepare、核对语义行、lock、build，不沿用已失效锁。无录音预演不进入这条实测路径。

字幕派生使用已选来源合同；默认兼容旧 timeline 的口径，显式 `--time-source measured` 可以升级旧 projected/nominal 项目。后续 lock/build/check 跟随词契约。只改视觉 CSS 不改变字幕时间。`--check` 核 SRT 与 cue 契约及末条越界；timeline 派生同时核当前实测段时长，不能只改来源标签。

外部来源导入的 `timeline.sourceEvidence` v1 保存 `media`（path/sha256/bytes/durationMs）、`srt`、`alignment`、`sourcePlan` 与 `sourceScript`。总长保留实测音频尾部，`measuredTotalMs` 保持 null。旧项目缺记录时，用原 SRT、原 alignment 和现有音频重跑导入；不要求重新剪辑或转写。核验可显式给 `verify_delivery --media <本次音频> --srt <本次字幕>`；stage_deliver verify 对应使用 `--audio`、`--srt`。

## SVG 与视觉时间

EDL 路径的候选对齐：

```bash
python3 "<craft>/visual/scripts/align-visual-plan.py" --plan "<包>/visual-plan.json" --script "<包>/script.md" --edit-dir "<edit>" --output "<project>/timeline/content-alignment.json"
python3 "<craft>/helpers/timeline_derive.py" "<edit>" --stats
python3 "<craft>/helpers/timeline_derive.py" "<edit>" --entries-only
```

核听 `needsReview`，以 cue 索引写 `timeline/grouping.json`，格式见 [visual-timeline](visual-timeline.md)，然后：

```bash
python3 "<craft>/helpers/timeline_derive.py" "<edit>" --grouping "<project>/timeline/grouping.json" --alignment "<project>/timeline/content-alignment.json" --output-timeline "<project>/timeline/timeline.json" --output-durations "<project>/composition/public/step-durations.json"
```

没有上游 visual-plan 时省略 `--alignment`。所有输出显式给根 `timeline/` 的绝对路径。

`timeline_derive.py` 按**当前剪辑的指纹**认渲染记录（文件名不参与判断）；认不到会在输出里标 `!`，按名义或推定时长继续，不阻断。

已剪音频 + 对应 SRT 用 `align-visual-plan.py --srt <SRT>` 替代 `--edit-dir`，输出候选绑定标 `srt-import`。它不是 measured 契约，不能交给 `timeline_derive.py` 假装通过。核对后由 `import_srt_timeline.py` 生成统一时间轴（调用见下），原 SRT 与声音保持来源绑定。

```bash
python3 "<craft>/helpers/import_srt_timeline.py" "<project>" --srt "<已剪SRT>" --alignment "<project>/timeline/content-alignment.json" --media "<现有剪好音频>"
```

制作画面（recompose 主路线）：

```bash
python3 "<craft>/helpers/film.py" outline "<project>" --page <page_key> --source "<原页SVG绝对路径>"
python3 "<craft>/helpers/film.py" pages "<project>" --map ch01=page_01,ch02=page_04
python3 "<craft>/helpers/film.py" pages "<project>"          # 只看映射与缺哪页
python3 "<craft>/helpers/film.py" verify "<project>"         # 拆解没填满就退 1
```

composition 由 Agent 按 [film.md](film.md) 的拆解手写 `src/scenes/*.js`，时间从 `timeline/timeline.json` 取。
`generate-composition.py` / `auto_choreography.py` / `scaffold.sh --theme` 均随 page 路线归档，新项目不调用。
`check_screen_text.py` 仍用于检查真实 DOM 文字。

## 渲染、核验、包装

**渲染前置条件（缺一不渲）**：剪点已确认；动效 / 合成审阅已确认；`probe_env.py` 先报告能力（不阻断），`check_render_env.py` 退 0。
**composition 路线的音频**：进 composition 之前先用 `audio_mix.py`/`audio_fix.py` 归一（HyperFrames 不会替你做响度；实测直接塞母版会得到 -16.9 LUFS）。
**响度唯一标准**：成片混音由 `audio_mix.py` 产出一个文件（-14 LUFS / -1.5 dBTP，可带 BGM duck；用它时 render 加 `--no-loudnorm`）；没有预混音时 `render.py` 自己归一化。`audio_fix.py --target-lufs` 只用于素材预处理。

**指纹不是渲染前置，是交付过期信号**：已有交付时先跑 `state_fingerprint.py verify` 判断它有没有过期 —— 改源之后「过期」正是**需要重新输出**的信号，它不拦住新渲染。重新输出并核验后再 `capture` 新指纹，发送前再 `verify`，不一致就不能**发送**。阶段顺序见 [stages.md](stages.md) 第 10 步。
渲染前先过 [timing-lock](timing-lock.md)：`film.py verify` 退 0，且 `feedback/*.jsonl` 的未决项已清或显式接受。

工程态底片预览（`--preview` 产物属于工程态，落 `_engineering/`；`edit/cut.mp4` 这个正式底片名只留给确认后的交付态渲染）：

```bash
python3 "<craft>/helpers/render.py" "<edit>/edl.json" -o "<edit>/_engineering/cut.mp4" --preview --no-subtitles
```

```bash
python3 "<craft>/helpers/probe_env.py" "<project>"        # 能力报告：libass/字体/资产预算/残留进程；只报告不阻断
python3 "<craft>/helpers/check_render_env.py" "<project>/composition"
python3 "<craft>/helpers/check_render_env.py" "<project>/composition" --json   # {ok, workers, memory}
```

`--json` 里的 `workers` 就是这台机器该用的 `--workers` 值（按总内存、可用内存与核数三者取低算出）。
不要凭核数自己推：`--workers auto` 是按核数开满 Chrome，8GB 机器上它开 6 个、把 swap 打满并带走了系统（见 `GOTCHAS.md` #69）。

在 `<project>/composition` 作为工作目录分别执行 `npm run check`、`npm run render`；实际命令/输出以项目 `package.json` 为准。透明路线、PNG 序列编码、Alpha 选择见 [visual-rendering](visual-rendering.md)，调用示例：

```bash
python3 "<craft>/visual/scripts/encode_transparent.py" "<PNG目录>" -o "<overlay.mov>" --codec prores --fps 30

# 渲染变体（完整取舍见 visual-rendering.md）
export HYPERFRAMES_FONT_CACHE_DIR="$PWD/.hyperframes-cache"     # 受限沙箱下字体缓存要落项目内
W=$(python3 "<craft>/helpers/check_render_env.py" "<project>/composition" --json \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["workers"])')
npx hyperframes render --workers "$W" -o /tmp/<name>.mp4 --resolution landscape -f 30 -q delivery
npx hyperframes render --no-low-memory-mode --format png-sequence -o /tmp/alpha-frames
python3 "<craft>/helpers/check_alpha.py" "<overlay.mov>" --json
python3 "<craft>/helpers/check_overlay.py" "<edit>" --json
python3 "<craft>/helpers/render.py" "<edit>/edl.json" -o "<edit>/final.mp4"
python3 "<craft>/helpers/verify_av.py" "<edit>" --help
python3 "<craft>/helpers/check_motion_targets.py" "<project>" --json   # 手写 GSAP 时间轴的门禁
python3 "<craft>/helpers/check_parity.py" "<project>"                # 仅老 page 项目（真有 choreography.json）
python3 "<craft>/helpers/check_motion.py" "<编码视频>" --json
python3 "<craft>/helpers/check_screen_text.py" "<project>" --help
python3 "<craft>/helpers/verify_delivery.py" "<edit>" --video "<实际成片>" --json
```

alpha/overlay 只用于对应分支；有意静止片段用 `check_motion.py --expect-still`。`verify_av.py --help` 与 `check_screen_text.py --help` 给当前画面/EDL的精确选项，按需要调用，不把工具报告当作者观感。

出片与交付（先过渲染闸门，再交付）：

```bash
python3 "<craft>/helpers/render_gate.py" "<project>" --out "<实际成片路径>"   # 退 0 才允许出片
python3 "<craft>/helpers/deliver.py" "<project>" --render                     # 显式渲染画面层 + 人物贴回 + 声音 + 核验
python3 "<craft>/helpers/deliver.py" "<project>" --visuals "<已有画面层.mp4>"  # 画面层已存在，跳过渲染
python3 "<craft>/helpers/state_fingerprint.py" capture "<project>"             # 交付自带来源指纹
python3 "<craft>/helpers/state_fingerprint.py" verify "<project>"              # 发送前核对，不一致不能发
```

包装已核验的真实输出：

```bash
python3 "<craft>/helpers/export_video.py" "<project>" --mode speaker
python3 "<craft>/helpers/export_video.py" "<project>" --mode animation --animation "<已渲染动画.mp4>"
python3 "<craft>/helpers/export_video.py" "<project>" --mode composite --final "<已渲染整片.mp4>"
python3 "<craft>/helpers/export_video.py" "<project>" --mode split --animation "<已渲染动画.mp4>" --final "<已渲染整片.mp4>"
python3 "<craft>/helpers/export_deliverables.py" "<edit>" --videos final.mp4 --srt subtitles.srt --out "<交付目录>"
python3 "<craft>/helpers/verify_delivery.py" "<edit>" --video "<交付整片>" --deliver-dir "<交付目录>" --json
# 成片在渲染后被二次剪过（剪停顿等）：先把剪点写进 edit/cut-map.json，再用同一条命令核验——
# 没有 cut-map 又比渲染记录短 >0.5s 会被拒绝（契约见 references/delivery.md）
python3 "<craft>/helpers/verify_delivery.py" "<edit>" --video "<画面成片>" --no-audio --json   # 无声画面轨：不要求音轨
python3 "<craft>/helpers/clean_edit_dir.py" "<edit>"        # 交付确认后才可清理；首次先呈清单
```

`split` 要有 cut、SRT、动画和整片四份真实输入；只需几件就按单项包装或用 export_deliverables，不强造四件套。包装复制字节、不渲染、不保证轨道时长相同。清理仅在交付确认且明确获准后调用 `clean_edit_dir.py --help`，不是制作默认动作。

## 审阅

逐字剪辑面（EDL 预览与面上缝）：

```bash
python3 "<craft>/helpers/edl_preview_build.py" "<edit>"
python3 "<craft>/helpers/edl_review_surface.py" "<edit>" --surface-only
```

[review-ui.md](review-ui.md) 是唯一接入与处理说明，包含 build、surface-only、公共 validator、DSH `review_open`、无插件宿主、inbox、EDL 选择的完整调用。`visual_review_feedback.py <project> --check` 是开面前置检查；`review_inbox.py` 才是作者提交的收件入口。

主题库已退役（2026-10-22）：风格数值归画面侧（`planners-ppt-hell` 的模板与风格文档），本 Skill 不维护主题库、也不读别人的 tokens。公共模块诊断：`python3 <craft>/helpers/lib/planners_modules.py --check`。`archive/` 全部是历史参考，不作为当前工具入口；`skills/manim-video/SKILL.md` 是严密数学动画的按需子 Skill。

## 收尾与沉淀

```bash
python3 "<craft>/helpers/spec_lint.py"          # 规范的结构与上限；退 0 才算收尾完成
python3 "<craft>/helpers/spec_lint.py" --json  # {ok, problems}
```

规则本体在 `author-spec.md`（全局）与 `style-spec.md`（风格）；准入与淘汰在 `preferences.md`。

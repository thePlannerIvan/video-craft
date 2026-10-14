## 免渲染审阅入口

- `live_stage.py <project> --json`：启动/复用 HyperFrames 编译服务。
- `build_review.py <project> --mode auto --slices off`：编译工程预览、内联对应官方 player 和素材清单。
- `live_preview.py`：上项内部使用的纯传输模块；`compile_preview(project, stage_url)` 返回 HTML、素材映射和 sourceHash。
- `review_surface.py <project> --surface-only`：把 surface 交 DSH；无插件时去掉该选项。
- `edl_preview_build.py <edit>`：按源媒体即时预览当前 EDL。

编辑后重建上述相应审阅页，无需先渲整片。旧媒体交付与转码工具保留如下。

# 工具调用手册

按任务选入口，不逐个跑完。本页的 `<craft>`、`<idea>`、`<ppt>`、`<core>` 分别替换为对应 Skill 的绝对根目录；`<project>`、`<edit>`、`<pages>` 是项目、剪辑目录与 PPT Hell 画面项目。Python 用安装时确认的解释器；每条 Python 命令都可将 `python3` 换为该解释器。扩展参数用该命令的 `--help`，不读实现。

## 文件在哪里

| 位置 | 拥有的内容 | 下一消费者 |
|---|---|---|
| `_idea/current.md`、`deliverable/` 或 `input/` | Idea 的作者决定、脚本、内容契约、资产与制作说明 | Craft 承接；原始内容版本保留 |
| `<pages>/_internal/02_svg_source/`、`design_direction.md` | PPT Hell 批准的 SVG、稳定 id、合成约束 | 页面导入器与动画层 |
| `edit/project.md`、`production-plan.md` | 本次采用版、输入路径、当前决定和计划 | 制作、恢复与交接 |
| `edit/transcripts/`、`takes_packed.md` | 转写缓存、Take 阅读视图 | EDL 编辑和字幕 |
| `edit/edl.json`、`segment_durations.json` | 剪辑决定与该版底片实测记录 | 渲染、字幕与核验 |
| `edit/captions_article.txt`、`semantic_lines.txt`、`caption_lock.json` | 字幕校对与断句决定 | `srt_export.py` |
| `edit/caption_words.json`、`captions.json`、`subtitles.srt` | 实测词、cue 与字幕导出视图 | 时间绑定、画面审阅、合成 |
| `timeline/grouping.json`、`content-alignment.json`、`timeline.json` | 屏/Beat 对齐、cue 分组与唯一视觉时钟 | composition 生成器与审阅 |
| `composition/`、`edit/overlays/` | 渲染源与已渲染视觉层 | 渲染器、EDL 合成 |
| `review/`、`feedback/` | 页面、surface、提交、独立草稿、收件后反馈 | 宿主只传输，Craft inbox 解释 |
| `edit/verify/`、`creative-check.md`、`成品/` | 实际编码结果检查与交付 | 用户与下轮恢复 |

## 接上游

```bash
node "<idea>/scripts/check-handoff-artifacts.mjs" --project "<上游项目>"
python3 "<craft>/helpers/check_script_hash.py" "<project>" --script "<包>/script.md" --plan "<包>/visual-plan.json"
python3 "<craft>/visual/scripts/import_svg_page.py" "<project>" --pages "<pages>" --audit --prove --emit --json
```

Idea 检查只核文件和素材，不代替作者决定。导入器读取 PPT Hell 项目根，输出 `composition/pages/manifest.json` 与导入后的页面/图片。review 构建器读取这些项目内页面，避免外部资源越出 surface dir。内容契约 5.0 为当前接口，4.0 仅兼容已有项目。

若收到的只有 `input/scenes/`，将它作为 `--pages` 参数按导入器支持的裸 SVG 目录处理；若导入器报告缺资产/无 id，回 PPT Hell 补当前页面，不能改成不可编辑 PNG 掩盖。

## 声音与剪辑

```bash
python3 "<craft>/helpers/transcribe.py" "<原始视频>" --edit-dir "<edit>" --audio-track 0 --backend auto
python3 "<craft>/helpers/transcribe_batch.py" "<素材目录>" --edit-dir "<edit>" --workers 4
python3 "<craft>/helpers/pack_transcripts.py" --edit-dir "<edit>"
python3 "<craft>/helpers/check_edl.py" "<edit>" --max-pause 0.8
python3 "<craft>/helpers/render.py" "<edit>/edl.json" -o "<edit>/cut.mp4" --preview --no-subtitles
```

转写会读取缓存；云端后端会上传声音并可能收费，先沿用作者已授权配置。离线选 `--backend mlx`。多音轨先核声音，`--audio-track` 是从零起的音轨索引。EDL 字段及多轨合成见 [composition-craft](composition-craft.md)。`render.py` 是记录实测时长的正式路径；`render_cut.py <edl> -o <mp4> --quality draft` 只作快预览，不替代实测记录。

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

渲染不再是「能开始干活」的前提。段时长可以解析算出来，覆盖层可以有浏览器可合成的载体，
**画面可以直接演活的 composition**，于是剪辑、字幕、时间脊柱、审阅都先跑起来，确认后才渲染。

审阅台的首选舞台是**活的 composition**：`live_stage.py` 起 HyperFrames 预览服务并给出可嵌入地址，
`build_review.py` 把它写进 `media.liveStage`，页面 iframe 进去直接演。零渲染、零等待，改一行动效
刷新即变 —— 这一条见 `SKILL.md`「两个态」与 `GOTCHAS.md` 第 57–59 条。

```bash
python3 "<craft>/helpers/live_stage.py" "<project>"       # 起服务 → 打印可嵌入地址（--stop 停）
python3 "<craft>/helpers/duration_plan.py" "<edit>"       # 解析预演（frame-quantised, projected）
python3 "<craft>/helpers/review_copy.py" "<成片>"         # 保留时间与原生分辨率的审阅副本
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
文件对真实渲染；交付前仍必须渲染并用 `srt_export.py --prepare --lock --build` 重建字幕。

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

输出 article/词契约/lock/cue/SRT。底片剪点变化后重新 prepare、核对语义行、lock、build，不沿用已失效锁。无录音预演不进入这条实测路径。

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

已剪音频 + 对应 SRT 用 `align-visual-plan.py --srt <SRT>` 替代 `--edit-dir`，输出候选绑定标 `srt-import`。它不是 measured 契约，不能交给 `timeline_derive.py` 假装通过。核对后由 `import_srt_timeline.py` 生成统一时间轴（调用见下），原 SRT 与声音保持来源绑定。

```bash
python3 "<craft>/helpers/import_srt_timeline.py" "<project>" --srt "<已剪SRT>" --alignment "<project>/timeline/content-alignment.json"
```

制作 HTML：

```bash
bash "<craft>/visual/scripts/scaffold.sh" "<project>" --theme=<已批准theme>
python3 "<craft>/visual/scripts/generate-composition.py" "<project>" --audio "<实际音频>" --theme <已批准theme>
python3 "<craft>/visual/scripts/auto_choreography.py" "<project>"
python3 "<craft>/visual/scripts/generate-composition.py" "<project>" --verify
```

scaffold 只用于新 composition，不在已有制作源上重复 init。生成器输出时间骨架，Agent 完成真实场景并按 [svg-animation-contract](svg-animation-contract.md) 将 `timeline/choreography.json` 的屏内参数注册到引擎；自动编排是候选，不是完成证明。已有批准 SVG/theme 直接沿用。`--verify` 校验骨架 timing，`check_screen_text.py` 检查真实 DOM 文字。

## 渲染、核验、包装

```bash
python3 "<craft>/helpers/check_render_env.py" "<project>/composition"
```

在 `<project>/composition` 作为工作目录分别执行 `npm run check`、`npm run render`；实际命令/输出以项目 `package.json` 为准。透明路线、PNG 序列编码、Alpha 选择见 [visual-rendering](visual-rendering.md)，调用示例：

```bash
python3 "<craft>/visual/scripts/encode_transparent.py" "<PNG目录>" -o "<overlay.mov>" --codec prores --fps 30
python3 "<craft>/helpers/check_alpha.py" "<overlay.mov>" --json
python3 "<craft>/helpers/check_overlay.py" "<edit>" --json
python3 "<craft>/helpers/render.py" "<edit>/edl.json" -o "<edit>/final.mp4"
python3 "<craft>/helpers/verify_av.py" "<edit>" --help
python3 "<craft>/helpers/check_motion.py" "<编码视频>" --json
python3 "<craft>/helpers/check_screen_text.py" "<project>" --help
python3 "<craft>/helpers/verify_delivery.py" "<edit>" --video "<实际成片>" --json
```

alpha/overlay 只用于对应分支；有意静止片段用 `check_motion.py --expect-still`。`verify_av.py --help` 与 `check_screen_text.py --help` 给当前画面/EDL的精确选项，按需要调用，不把工具报告当作者观感。

包装已核验的真实输出：

```bash
python3 "<craft>/helpers/export_video.py" "<project>" --mode speaker
python3 "<craft>/helpers/export_video.py" "<project>" --mode animation --animation "<已渲染动画.mp4>"
python3 "<craft>/helpers/export_video.py" "<project>" --mode composite --final "<已渲染整片.mp4>"
python3 "<craft>/helpers/export_video.py" "<project>" --mode split --animation "<已渲染动画.mp4>" --final "<已渲染整片.mp4>"
python3 "<craft>/helpers/export_deliverables.py" "<edit>" --videos final.mp4 --srt subtitles.srt --out "<交付目录>"
python3 "<craft>/helpers/verify_delivery.py" "<edit>" --video "<交付整片>" --deliver-dir "<交付目录>" --json
```

`split` 要有 cut、SRT、动画和整片四份真实输入；只需几件就按单项包装或用 export_deliverables，不强造四件套。包装复制字节、不渲染、不保证轨道时长相同。清理仅在交付确认且明确获准后调用 `clean_edit_dir.py --help`，不是制作默认动作。

## 审阅

[review-ui.md](review-ui.md) 是唯一接入与处理说明，包含 build、surface-only、公共 validator、DSH `review_open`、无插件宿主、inbox、EDL 选择的完整调用。`visual_review_feedback.py <project> --check` 是开面前置检查；`review_inbox.py` 才是作者提交的收件入口。

主题自检：`python3 <craft>/visual/scripts/check_themes.py --json`。公共模块诊断：`python3 <craft>/helpers/lib/planners_modules.py --check`。`archive/` 全部是历史参考，不作为当前工具入口；`skills/manim-video/SKILL.md` 是严密数学动画的按需子 Skill。

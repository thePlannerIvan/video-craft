# 语义字幕、ASR 转写与人声响度（`captions-and-audio.md`）

> 什么时候读：声音定剪、ASR 校对、制作语义字幕、`srt` 外挂/烧录选择，以及人声增强与全片响度混音时读本页。命令见 [tools.md](tools.md)。

## 1. 转写与听辨铁律

- **词级时间锚点首选 `transcribe_seedasr.py`**（豆包流式语音识别 2.0 SAUC，需根 `.env` 的 `DOUBAO_APP_ID` / `DOUBAO_ACCESS_TOKEN` 与 `node ws`，见 [install.md](../install.md)）。
- 历史回退 `helpers/_internal/transcribe.py --backend auto`（Scribe → Ark → mlx）仅在无语音控制台凭据时使用；**严禁拿 Ark 通用理解模型当词级 ASR**，静音中编词或整句 1 token 会直接破坏逐字剪辑（[GOTCHAS.md](../GOTCHAS.md) #1）。
- 出现 >1.5s 的粗粒度整句 token 先跑 `refine_transcript.py`；多音轨先核对 `--audio-track`（0-based）。
- **两引擎分歧信号（#2）**：删重要词或确认专名前用第二个后端复核同一窗口；两版拼写与时间戳不一致时**回到音频听辨**，不盲信任一文字框。

## 2. Article-First 语义字幕流水线（唯一字幕契约）

中文长口播与独立 SRT 交付统一按三步：**全文校对 → 语义断句 → 锁定生成**（不另造机械截字脚本）。所有步骤由 `helpers/srt_export.py` 执行：

### Stage A · `--prepare` 准备原稿与词契约

```bash
python3 "<craft>/helpers/srt_export.py" "<edit>" --prepare
```

读取当前 EDL 与缓存词级转写，产出：
- `caption_words.json`：按输出序排列的保留词、源/输出时间戳、EDL 段 ID、EDL 与转写 sha256；
- `captions_article.txt`：完整正文，只在 EDL 段界换行；
- 可选 `caption_corrections.json`：显式 `drop` 或 `replace`（按 `source` + `transcript_index` 写原因）。仅用于确认错别字/无意义语气词；**重说整句或重复起头必须回 EDL 剪除**，不得靠改字幕遮掩音频中仍在说的句子。若发现口吃拆字停留在短语中间（会切出 0.2s 破洞），保留音频并在 `caption_corrections.json` `drop` 该字词；落在子句边缘则直接进 EDL 剪掉。

已有已审稿件时勿误覆写，只有确认 EDL/转写改动或显式升级实测时长时加 `--force-prepare`。

### Stage B · 校对全文与 `--lock`

通读 `captions_article.txt`，修正专名/错字/标点（不润色改写说话人原意），运行：

```bash
python3 "<craft>/helpers/srt_export.py" "<edit>" --lock
```

若规范化文字覆盖不了保留词序，`--lock` 拒绝，须回查 EDL 或补 `caption_corrections.json` 并重跑 `--prepare`。

### Stage C · `semantic_lines.txt` 断句与 `--build` / `--check`

手工或由模型从首字到末字切分 `semantic_lines.txt`：每非空行一条 cue，EDL 段界用一空行隔开；多数 **10–18 汉字**、**严禁超过 20 个正文字符**；禁止在词/专名/英文术语/数字范围（如 `15~20 年`）/固定概念中间断开，**严禁一条 cue 跨过 EDL 段界**。

```bash
python3 "<craft>/helpers/srt_export.py" "<edit>" --build
python3 "<craft>/helpers/srt_export.py" "<edit>" --check
python3 "<craft>/helpers/_internal/check_caption_breaks.py" "<edit>/subtitles.srt" --json
```

`--build` 用 `output_time = (word_time - segment_start) / speed + segment_offset`（来源见 [visual-timeline.md](visual-timeline.md)）严格对齐起止词并校验哈希。模型自行通读并安排断句，只把真听不清的专名/重复取舍交给人，不让人核对行号时间戳。

## 3. 字幕交付形态与剪映/PR 空隙规则

在制作方案阶段明确以下三种交付形态之一并记入 `production-plan.md`：

| 形态 | 产出与核验重点 |
|---|---|
| `embed` | 成片画面直接烧录字幕（显式 `--burn-subtitles`，须本机 FFmpeg 含 `libass`，缺则编码前报错失败，不可静默退化） |
| `srt-deliver` | 无字幕成片 + 独立 UTF-8 `subtitles.srt`；审阅页可叠加显示但不代表成片已烧录 |
| `both` | 同版 `captions.json` 派生烧录成片与外挂 SRT，起止与文案同源 |

- **流水线严格对齐 vs. 交付导入空隙（#73）**：流水线 `subtitles.srt` 允许末条与尾部合理静音存在余量（`tolerance` 见 [GOTCHAS.md](../GOTCHAS.md) #7）；剪映/PR 导入要求相邻无重叠或微小间隙时，**只在交付副本包装**阶段由 `export_deliverables.py` 处理，禁止反向篡改源 `captions.json` 与流水线校验准则。
- 若从预演升级实测时长，用 `srt_export.py <edit> --prepare --force-prepare --time-source measured`，再重新 `--lock` / `--build` / 派生 `timeline` / `--check`（保留已审 `semantic_lines.txt`）。

## 4. 音频诊断、C 档人声预设与克制音效混音标准

- **先诊断与单轨边界**：用 `helpers/_internal/audio_diag.py <媒体> --json` 检出电平、削波、底噪问题；`helpers/audio_fix.py` **仅用于单轨人声前期声学试听或短片段盲听对照（`--ab`）**，输出新 `.wav` 副本并保持原母版只读。**终混勿先跑 `audio_fix.py` 再送入 `audio_mix.py`**，避免同一段人声被重复压缩两次。
- **默认 C 档「播客浑厚」预设（`podcast-warm`）**：`65Hz` 高通、`115Hz +3.0dB` 胸腔厚度、`245Hz -3.5dB` 去箱音、`3.2kHz +2.5dB` 清晰度、`9.5kHz highshelf +1.8dB` 空气感、`5.2–8.2kHz` 侧链去齿音、轻压缩 + **双遍线性响度归一**，输出至 `-14.0 LUFS / -1.5 dBTP`（48kHz 立体声）。`audio_fix.py` 单轨试听传 `--raw` 或 `--preset raw` 可绕过处理导出纯干声。
- **全片唯一混音出口与防重复压缩（#19）**：成片最终混音由 **`helpers/audio_mix.py`** 唯一产出，**默认启用 `--voice-preset podcast-warm`**，直接接收未处理的粗剪干声并完成 `-14.0 LUFS / -1.5 dBTP` 交付响度对齐（带 `--bgm` 时附加单遍 `loudnorm` 闪避混音；整体校验以交付件立体声整片 `ebur128` 为准）。仅当输入人声已被 `audio_fix.py` 预处理过时，才显式传 `--voice-preset none` 绕过人声 EQ 与压缩以防重复压缩；需一键退回纯干声时传 `--dry`（绕过 EQ/压缩、BGM 与 SFX），或传 `--raw-voice` / `--voice-preset raw` 仅绕过人声处理。`--sfx <sfx.json>` 仅使用内置 `assets/sfx/` 下的 8 个 CC0 本地柔和音效（不默认联网搜音效），强制三条硬护栏：① 只响应 `chapter` / `reveal` / `turn`；② 全片平均每 15–25s 至多 1 次（超密退 1 拒绝）；③ `--sfx-under-db` 限定在人声下 `18–22 dB`，支持 `--no-sfx` 一键剥离。
- 使用已预混音频进 `render.py` 时传 `--no-loudnorm`（且 `-o` 禁止使用 `base*.mp4` 内部保留名，#84）；交付验证须读立体声整片 `ebur128`。HyperFrames composition 旁白进 `composition/assets/` 前优先直接用 `audio_mix.py` 处理。

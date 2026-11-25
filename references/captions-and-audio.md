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

## 4. 双轨音频分离：Voice Polish（人声润色）与 Visual Soundscape（画面声景）

- **声音彻底分轨**：人声母带（**Voice Polish**，`audio_mix.py`）专注纯净人声，只随 `人物成片.mp4` 交付；画面动效起伏音效与素材原声底噪（**Visual Soundscape**，`sound_design.py`）归画面层，交付时无损封装进 `画面成片.mp4` 并同出独立 `画面音效轨.wav`。**禁止把动效音效混入人声润色默认链路**。
- **Voice Polish 唯一入口（`helpers/audio_mix.py`）**：
  - 先用 `helpers/_internal/audio_diag.py <媒体> --json` 检出电平、削波、底噪与停顿重吸气声；
  - 默认 `podcast-warm` 预设（`65Hz` 高通、`115Hz +3.0dB`、`245Hz -3.5dB`、`3.2kHz +2.5dB`、`9.5kHz +1.8dB`、侧链去齿音、轻压缩 + 双遍线性响度归一至 `-14.0 LUFS / -1.5 dBTP`，48kHz 立体声）**默认启用 `--debreath`**：采用双频段语音与清辅音保护（前 `100ms` / 后 `70ms` 膨胀保护字头与气音辅音），仅把 `≥140ms` 停顿谷底柔和衰减至 `-62 dBFS` 自然底噪，保证 `0.000s` 漂移与语音段 RMS 变化 `≤0.1 dB`（显式 `--no-debreath` 可关闭）；
  - 支持 `--ab "起始,时长"` 做单轨与停顿除吸气 A/B 盲听对照，以及 `--dry` / `--raw-voice` 导出纯干声；
  - **兼容入口 `helpers/audio_fix.py`**：仅用于独立单轨声学诊断与历史兼容，终混勿先跑 `audio_fix.py` 再送 `audio_mix.py` 以防二次压限（确需接入时传 `--voice-preset none`）。
- **Visual Soundscape 独立管线（`helpers/sound_design.py`）**：
  - `build --storyboard <storyboard.json> --voice <人声WAV> --out <soundscape.wav> [--broll-bed on|off] [--preview-variants]`：
    - **动效起伏音效层**：直接消费 `storyboard.json` 中的 `model` / `card-deck` 卡点，从内置 `assets/sfx/` 取经验证 CC0 音效完成「推起（`swell`/`riser`）→ 落点（`whoosh`/`sub-drop`/`crisp-tick`/`chime`）」配音并施加高频柔化搁架；
    - **素材原声底噪自动筛分与闪避**：提取 `footage` 片段原声，自动三档分流（纯配乐/干净环境音挖空人声频段 `1400 Hz -9dB` 与 `2400 Hz` 滚降；疑带轻对白的低频音乐仅留 `≤450 Hz` 暖底垫；清晰对白或高杂噪自动静音），再以人声母带作侧链键控 `-5 dB` 动态闪避；通过 `--broll-bed on|off` 切换开关，审阅期可通过 `--preview-variants` 生成开关对照轨；
  - **内置确定性响度门禁（`sound_design.py verify`）**：独立声景母带落在 `-37.0..-30.0 LUFS`（`TP ≤ -13.5 dBTP`），模拟「人声母带 + 声景母带」合播落在 `-14.2..-13.4 LUFS`（`TP ≤ -1.0 dBTP`），越界直接退 1 拒绝。
- 使用已预混音频进 `render.py` 时传 `--no-loudnorm`（且 `-o` 禁止使用 `base*.mp4` 内部保留名，#84）；交付验证须读立体声整片 `ebur128`。HyperFrames composition 旁白进 `composition/assets/` 前优先直接用 `audio_mix.py` 处理。

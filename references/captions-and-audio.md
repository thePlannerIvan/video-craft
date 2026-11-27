# 语义字幕、ASR 转写与人声响度（`captions-and-audio.md`）

> 什么时候读：声音定剪、ASR 校对、制作语义字幕、`srt` 外挂/烧录选择，以及人声增强与全片响度混音时读本页。命令见 [tools.md](tools.md)。

## 1. 转写与听辨铁律

- **词级时间锚点首选 `transcribe_seedasr.py`**（豆包流式语音识别 2.0 SAUC，需根 `.env` 的 `DOUBAO_APP_ID` / `DOUBAO_ACCESS_TOKEN` 与 `node ws`，见 [install.md](../install.md)）。
- **备选与交叉校验 `helpers/_internal/transcribe.py`**：`--backend auto` 仅在存在 `ELEVENLABS_API_KEY` 时运行 Scribe，缺失凭据、配额不足或返回 401 时直接报错并建议改用 `transcribe_seedasr.py` 或显式 `--backend mlx`，**从不自动回退至 `--backend ark`**；`--backend ark` 仅限显式非 ASR 调用，严禁将其用于词级时间戳（[GOTCHAS.md](../GOTCHAS.md) #1）。
- 出现 >1.5s 的粗粒度整句 token 先跑 `refine_transcript.py`；多音轨先核对 `--audio-track`（0-based）。
- **两引擎分歧信号（#2）**：删重要词或确认专名前用第二个后端复核同一窗口；两版拼写与时间戳不一致时**回到音频听辨**，以真实人声为准。

## 2. Article-First 语义字幕流水线（唯一字幕契约）

中文长口播与独立 SRT 交付统一由 `helpers/srt_export.py` 按三步推进：**全文校对 → 语义断句 → 锁定生成**。

### Stage A · `--prepare` 准备原稿与词契约

```bash
python3 "<craft>/helpers/srt_export.py" "<edit>" --prepare
```

读取当前 EDL 与缓存词级转写，产出：
- `caption_words.json`：按输出序排列的保留词、源/输出时间戳、EDL 段 ID、EDL 与转写 sha256；
- `captions_article.txt`：完整正文，只在 EDL 段界换行；
- 可选 `caption_corrections.json`：显式 `drop` 或 `replace`（按 `source` + `transcript_index` 写原因），仅用于确认错别字与无意义语气词；**重说整句或重复起头必须回 EDL 剪除**，确保音频与字幕内容同源。若口吃拆字停留在短语中间（会切出 0.2s 破洞），保留音频并在 `caption_corrections.json` `drop` 该字词；落在子句边缘则直接在 EDL 剪掉。

已有已审稿件时保留原稿，仅在确认 EDL/转写改动或显式升级实测时长时加 `--force-prepare`。

### Stage B · 校对全文与 `--lock`

通读 `captions_article.txt`，修正专名/错字/标点并保持说话人原意，运行：

```bash
python3 "<craft>/helpers/srt_export.py" "<edit>" --lock
```

若规范化文字覆盖不了保留词序，`--lock` 拒绝，须回查 EDL 或补 `caption_corrections.json` 并重跑 `--prepare`。

### Stage C · `semantic_lines.txt` 断句与 `--build` / `--check`

手工或由模型从首字到末字切分 `semantic_lines.txt`：每非空行一条 cue，EDL 段界用一空行隔开；保持 **10–18 汉字**（上限 **20 个正文字符**），保持词、专名、英文术语、数字范围（如 `15~20 年`）与固定概念完整不断开，每条 cue 严格落在单条 EDL 段内。

```bash
python3 "<craft>/helpers/srt_export.py" "<edit>" --build
python3 "<craft>/helpers/srt_export.py" "<edit>" --check
python3 "<craft>/helpers/_internal/check_caption_breaks.py" "<edit>/subtitles.srt" --json
```

`--build` 用 `output_time = (word_time - segment_start) / speed + segment_offset`（来源见 [visual-timeline.md](visual-timeline.md)）严格对齐起止词并校验哈希。模型自行通读并安排断句，只把真听不清的专名/重复取舍交给人。

## 3. 字幕交付形态与剪映/PR 空隙规则

在制作方案阶段明确以下三种交付形态之一并记入 `production-plan.md`：

| 形态 | 产出与核验重点 |
|---|---|
| `embed` | 成片画面直接烧录字幕（显式 `--burn-subtitles`，须本机 FFmpeg 含 `libass`，缺则编码前报错退出） |
| `srt-deliver` | 无字幕成片 + 独立 UTF-8 `subtitles.srt`；审阅页可叠加显示供校对 |
| `both` | 同版 `captions.json` 派生烧录成片与外挂 SRT，起止与文案同源 |

- **流水线严格对齐 vs. 交付导入空隙（#73）**：流水线 `subtitles.srt` 忠实对齐词界与尾部静音余量（`tolerance` 见 [GOTCHAS.md](../GOTCHAS.md) #7）；剪映/PR 导入所需的无重叠微小间隙只在交付包装阶段由 `export_deliverables.py` 处理，保持源 `captions.json` 与流水线校验准则不动。
- 若从预演升级实测时长，用 `srt_export.py <edit> --prepare --force-prepare --time-source measured`，再重新 `--lock` / `--build` / 派生 `timeline` / `--check`（保留已审 `semantic_lines.txt`）。

## 4. 双轨音频分离：Voice Polish（人声润色）与 Visual Soundscape（画面声景）

- **声音彻底分轨**：**Voice Polish**（`helpers/audio_mix.py`）专注纯净人声，专归 `人物成片.mp4`；**Visual Soundscape**（`helpers/sound_design.py`）负责动效起伏音效与经筛分闪避的素材原声底噪，专归 `画面成片.mp4` 与独立 `画面音效轨.wav`（无声景需求时画面成片合法保持 0 音轨）。两轨物理隔离，保持默认人声链路纯净。
- **Voice Polish 唯一权威入口（`helpers/audio_mix.py`，参数与预设细则见 `audio_mix.py --help`）**：
  - 先按需用 `helpers/_internal/audio_diag.py <媒体> --json` 检出电平、削波、底噪与停顿重吸气声；
  - 直接向 `audio_mix.py` 传入原始干声，默认 `podcast-warm` 预设自动完成播客暖声均衡/压缩与双遍响度归一（`-14.0 LUFS / -1.5 dBTP`，48kHz 立体声），并默认开启 `--debreath`（基于 `p50` 自适应门限与气流倾角筛选保护轻读尾音与清辅音，仅衰减 `≥140ms` 真实吸气停顿且保证 `0.000s` 漂移与语音段 RMS 变化 `≤0.1 dB`；已有词级时间轴时可加 `--words <caption_words.json>` 硬保护全部已出字区间，可用 `--no-debreath` 对照关闭）；
  - 支持 `--ab "起始,时长"` 做单轨与停顿除吸气 A/B 盲听对照，以及 `--dry` / `--raw-voice` 导出纯干声；
  - **兼容入口 `helpers/audio_fix.py`**：仅用于独立单轨声学诊断与历史兼容；处理终混时直接把原始干声交给 `audio_mix.py`（仅在输入确已由 `audio_fix.py` 预加工时加 `--voice-preset none` 防二次压限）。
- **Visual Soundscape 唯一权威入口（`helpers/sound_design.py`，参数细则见 `sound_design.py --help`）**：
  - `build --storyboard <storyboard.json> --voice <人声WAV> --out <soundscape.wav> [--broll-bed on|off] [--preview-variants]`：
    - **动效起伏音效层**：直接消费 `storyboard.json` 中的 `motion` / `model` / `card-deck` 卡点，从内置 `assets/sfx/` 取经验证 CC0 音效完成「推起 → 落点 → 揭示」配音；
    - **素材原声底噪自动筛分与闪避**：自动提取并三档筛分 `footage` 片段原声（干净配乐/环境音避让人声频段、疑带轻对白仅留暖低频垫、清晰对白或杂噪静音），以人声母带作侧链键控动态闪避；通过 `--broll-bed on|off` 切换底噪，`--preview-variants` 产出审阅期开关对照轨；
  - **内置确定性响度门禁（`sound_design.py verify`）**：独立声景母带落在 `-37.0..-30.0 LUFS`（`TP ≤ -13.5 dBTP`），模拟「人声母带 + 声景母带」合播落在 `-14.2..-13.4 LUFS`（`TP ≤ -1.0 dBTP`），越界直接退 1 拦截。
- 使用已预混音频进 `render.py` 时传 `--no-loudnorm`（输出命名用成品级或工程态路径，避开内部保留名 `base*.mp4`，#84）；交付响度验收统一读取交付件立体声整片 `ebur128`（#19）。Remotion 场景资产（`remotion/public/assets/`）或历史兼容 `composition/assets/` 旁白在导入前先经 `audio_mix.py` 校准。

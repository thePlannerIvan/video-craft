# 字幕形态选择

制作方案阶段明确字幕交付形态。用户已说明时沿用，不重复询问；没有决定且影响交付时再确认，记录到项目 production-plan.md。

| 模式 | 用户拿到什么 | 制作与检查 |
|---|---|---|
| embed | 画面已经带字幕的视频 | 明确字幕由 composition 或 FFmpeg 哪一层烧入，避免烧两次；实际输出帧要看见正确字幕 |
| srt-deliver | 视频和独立 SRT | 成片不烧字；工程审阅可以显示字幕，不能把审阅显示误认为成片已经烧录 |
| both | 带字幕视频和独立 SRT | 同版 cues 派生两种输出；文字与时间一致 |

这些是项目交付模式，不是宣称 deliver.py 当前已提供同名参数。准确 CLI 和当前烧录限制见 [tools.md](tools.md) 与 [delivery.md](delivery.md)。缺少 libass 等条件时不静默改合同；修复或明确尚未完成。

## 内容与时间各有 owner

- 中文语义字幕按 [caption-article-first.md](caption-article-first.md)：先全文校对、锁定与语义断句，再由现有工具绑定时间。该文件拥有长度、词边界、纠错与 EDL 边界规则；本页不再保留第二套自动断句算法。
- 有 EDL 时，字幕来自同版剪辑和时长证据；重复录制的取舍写回 EDL，不能只删字幕隐藏仍在音频中的句子。
- 外部已剪音频 + SRT 时，SRT 是输入；保留原件与采用版，核词义和真实声音再按 [visual-timeline.md](visual-timeline.md) 导入。不要为了看起来对齐而猜测或拉伸时间。
- ASR 纠错保留真实说法；专名听不清先核声音。项目里的替换词表不升为所有视频的默认替换规则。

## 交付检查

按 [delivery.md](delivery.md) 核实际视频和约定目录里的 SRT。检查当前来源、内容、起止、音画与字幕同步；存在正常尾静音时字幕不必延长到视频末帧。独立字幕保持 UTF-8 与标准 SRT 格式。若剪辑软件有特别导入要求，先验证副本，不为消除所有空隙而篡改原始 cue 时间。

旧版机械断句与逐词重建经验只供定位旧项目，见 [历史字幕说明](../archive/web-video-presentation/references/CAPTION-MODES.md)；它不再覆盖现行 article-first 语义字幕链。

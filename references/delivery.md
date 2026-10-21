# 交付：`deliver.py`（画面层 + 人物 + 声音 + 字幕 → 成片 + 核验报告）

## 它覆盖的真实形态

2026-10-21 三条片的形态不是"一次渲染出成片"，而是：

- **composition 只做画面层**：黑底，**左侧 500px 留空给人物、底部 200px 留空给字幕**；
- 人物与声音在**交付阶段贴回**；
- 字幕优先**外挂 SRT**（本机 ffmpeg 往往没有 libass，烧录要显式要求）。

这种形态以前没有入口，交付方只能手写 ffmpeg overlay。现在它是一条命令。

## 用法

```bash
# 完整流程：渲染画面层 → 贴人物 → 接声音 → 核验
python3 helpers/deliver.py <project>

# 已有画面层（跳过渲染，快）
python3 helpers/deliver.py <project> --visuals composition/_render/visuals.mp4

# 指定素材与输出
python3 helpers/deliver.py <project> --person <mp4> --audio <m4a> --srt <srt> --out <目录>

# 夹具/调试：跳过人工提交闸门
python3 helpers/deliver.py <project> --skip-gate
```

几何全部来自 `recompose.json`：`canvas`（宽高/帧率）、`personSlot`（人物贴回的位置与尺寸）、
`captionSafe`（字幕安全区）。**不要在命令里重复这些数字**，改项目配置。

## 它核验什么（写进 `<成品>/<片名>_核验报告.json`）

| 项 | 判据 |
|---|---|
| 分辨率 / 帧率 / 时长 | 与 `recompose.json` 的 canvas 一致；时长与画面层差 ≤ 0.5s |
| 音轨 | 成片真的有音频流（不是静音轨） |
| 首 / 中 / 尾帧 | 平均亮度 ≥ 6，不是全黑 |
| **字幕安全区** | 画面层在 `captionSafe` 区域内**没有内容**（有就会报出是哪几个时刻） |
| 人物贴回 | 按 `personSlot` 做 cover 裁切（先等比放大再居中裁，不挤压） |
| 字幕 | 默认外挂 SRT；`--burn-subtitles` 在 ffmpeg 没有 libass 时**明确报错**，不静默降级 |

任何一项红 → 退出码 1，并保留报告，便于回修画面层（改 composition 重渲）而不是手改成品。

## 与前两步的关系

```
film.py   → 原页拆解 + composition（画面层）
review.py → 能播的审阅页（人审通过）
deliver.py→ 成片 + 核验报告（人审之后才允许）
```

`deliver.py` 的第一件事是跑 `render_gate.py`：没有人审覆盖当前快照就拒绝出片。
这条闸门是硬的，不是因为流程好看——2026-10-21 就发生过"确认前渲染了 43 秒成片"。

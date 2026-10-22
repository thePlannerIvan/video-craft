# 交付：`deliver.py`（画面层 + 人物 + 声音 + 字幕 → 成片 + 核验报告）

## 它覆盖的真实形态

2026-10-21 三条片的形态不是"一次渲染出成片"，而是：

- **composition 只做画面层**：黑底，**左侧 500px 留空给人物、底部 200px 留空给字幕**；
- 人物与声音在**交付阶段贴回**；
- 字幕优先**外挂 SRT**（本机 ffmpeg 往往没有 libass，烧录要显式要求）。

这种形态以前没有入口，交付方只能手写 ffmpeg overlay。现在它是一条命令。

## 用法

出片只跑 `deliver.py <project> --render`（缺画面层时默认拒绝，渲染必须显式）；`--visuals` / `--person` / `--audio` / `--srt` / `--out` / `--no-person` 的完整选项见 [tools.md](tools.md)「渲染、核验、包装」。

人物素材按 `--person` → `composition/assets/person.mp4` → `edit/_engineering/person_master.mp4`
顺序找；找不到就是红项，**除非显式说这片没有人物**（`--no-person`，对应 recompose-mode 的
「仅画面层 / 纯画面 + 旁白」形态）。声音默认取 `composition/assets/audio.m4a`，字幕默认取
`edit/subtitles.srt`，两条也可用 `--audio` / `--srt` 覆盖。

几何全部来自 `recompose.json`：`canvas`（宽高/帧率）、`personSlot`（人物贴回的位置与尺寸）、
`captionSafe`（字幕安全区）。**不要在命令里重复这些数字**，改项目配置。

## 它核验什么（写进 `<成品>/<片名>_核验报告.json`）

| 项 | 判据 |
|---|---|
| 分辨率 / 帧率 / 时长 | 与 `recompose.json` 的 canvas 一致；时长与画面层差 ≤ 0.5s |
| 音轨 | 成片真的有音频流（不是静音轨） |
| 首 / 中 / 尾帧 | 平均亮度 ≥ 6，不是全黑 |
| **字幕安全区** | 画面层在 `captionSafe` 区域内**没有内容**（有就会报出是哪几个时刻） |
| 人物贴回 | 按 `personSlot` 做 cover 裁切（先等比放大再居中裁，不挤压）；`--no-person` 时跳过并在 notes 写明「无人物轨」 |
| 字幕 | 默认外挂 SRT；`--burn-subtitles` 在 ffmpeg 没有 libass 时**明确报错**，不静默降级 |

任何一项红 → 退出码 1，并保留报告，便于回修画面层（改 composition 重渲）而不是手改成品。

## 画面层缓存：源比成品新就重渲

`composition/_render/visuals.mp4` 是上一次渲染的画面层缓存，**改过 composition 之后再跑
deliver 会复用它**。所以 deliver 交付前按源文件 mtime 判新旧：composition 的 `index.html`、
`src/*`、`assets/*` 任一比缓存新就重新渲染并写一条 note（缓存不能手删才更新）。

要渲染时它会先跑 `check_render_env.py`：font cache / node / npx / composition 这些真问题拦下来；
**只有「可用内存 < 门槛」一条红时不拦**，按 `check_render_env --json` 给的 `workers`（1 起）渲染
并写 note —— deliver 本来就用 `--workers 1`，机器上有别的进程时可用内存长期低于 4GB，
照「缺一不渲」会让人根本交不出片。

## 与前两步的关系

```
film.py   → 原页拆解 + composition（画面层）
review.py → 能播的审阅页（人审通过）
deliver.py→ 成片 + 核验报告（人审之后才允许）
```

`deliver.py` 的第一件事是跑 `render_gate.py`：没有人审覆盖当前快照就拒绝出片。
这条闸门是硬的，不是因为流程好看——2026-10-21 就发生过"确认前渲染了 43 秒成片"。

## 交件的叫法

一件片子按交付形态叫三个名字，文档与对话统一用它们：

- **成片**：人物 + 画面 + 声音 + 字幕合成后的那一条
- **人物成片**：只含口播人物轨
- **画面成片**：只含画面层（没有人物、没有烧字幕）

程序当前的输出文件名这轮不改（改名会让老项目和已有习惯失效）；新项目按这三个名字命名。

## 时间轴对不对齐，报告里要看得到

`timeline_derive` 按**当前剪辑的指纹**找对应的渲染记录，不看文件名。三种情况：

- 找到指纹一致的记录 → 时间脊柱按实测总长对齐；
- 只找到没有指纹的老记录（含老式"每段秒数"格式）→ 按推定值对齐，`timeline_derive` 输出里标 `!`，交付报告的 notes 里写"推定"；
- 完全找不到（还没渲，或渲的是旧版剪辑）→ 时间轴按名义时长走，两边同样标注。

字幕与画面时间点读同一份记录；优先保证字幕对齐，画面时间点按标注复核。

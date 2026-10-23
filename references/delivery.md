# 交付：`deliver.py`（画面层 + 人物 + 声音 + 字幕 → 成片 + 核验报告）

## 它覆盖的真实形态

2026-10-21 三条片的形态不是"一次渲染出成片"，而是：

- **composition 只做画面层**：黑底，**左侧 500px 留空给人物、底部 200px 留空给字幕**；
- 人物与声音在**交付阶段贴回**；
- 字幕优先**外挂 SRT**（本机 ffmpeg 往往没有 libass，烧录要显式要求）。

这种形态以前没有入口，交付方只能手写 ffmpeg overlay。现在它是一条命令。

## 当前交付顺序与完成线

模型先核对作者明确出片指令、当前版本人工审阅与未决意见处理；render_gate 仅检查快照有提交及 manifest 变化，不能推断反馈内容是否批准。

1. `deliver` 编码前执行环境探测、适用的 film verify、HyperFrames check 和 GSAP selector/transform 检查；显式 `--visuals` 也须通过来源与版本检查。
2. 合成后调用同一份 `verify_delivery`，报告分别给出 `composition_ok`、`delivery_ok` 和 `delivery_verdict`；严格失败、进程异常、报告无效或适用核验未执行时，总 `ok=false` 并非零退出。
3. 需要包装时运行 `export_deliverables`，再对实际视频与 `--deliver-dir` 核验副本。`stage_deliver verify --no-audio` 支持无声画面轨；`run --no-audio` 明确拒绝不支持的动作组合。
4. 全部适用核验通过后 `state_fingerprint capture`；发送前 `verify`。旧交付指纹只拦发送，不能阻止重新制作。

外部剪好音频与 SRT 通过 `import_srt_timeline --media` 登记媒体、SRT、alignment 及其来源内容哈希和实测时长。时间来源仍是 `srt-import`，不伪造 EDL。旧项目可以继续读取；正式交付前补选一次现有音频，见 [tools.md](tools.md) 的导入命令。缺记录、当前文件/对齐绑定失配、字幕超长及交付目录中无法对应当前源的 MP4/SRT 均拒绝。

默认外挂字幕；`--burn-subtitles` 在两种人物路径都实际执行 libass subtitles 滤镜，缺滤镜在编码前失败。自动检查不替代对成片的审听审看，尤其内容正确性与美术质量。

## 用法

合成入口为 `deliver.py <project> --render`（缺画面层时默认拒绝，渲染必须显式）；`--visuals` / `--person` / `--audio` / `--srt` / `--out` / `--no-person` 的完整选项见 [tools.md](tools.md)「渲染、核验、包装」。

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
| 音轨 | 检查音频流存在；有流不证明非静音，仍需审听/音频核验 |
| 首 / 中 / 尾帧 | 抽样检查平均亮度；抽样不证明整片正确，且探测失败的当前实现需人工核实 |
| **字幕安全区** | 抽样亮度启发式；不能单凭亮度证明安全区无语义内容，需检查实际构图 |
| 人物贴回 | 按 `personSlot` 做 cover 裁切（先等比放大再居中裁，不挤压）；`--no-person` 时跳过并在 notes 写明「无人物轨」 |
| 字幕 | 默认外挂 SRT；显式烧录执行字幕滤镜，缺 libass 在编码前拒绝；仍需抽帧核对样式与构图 |

任何一项红 → 退出码 1，并保留报告，便于回修画面层（改 composition 重渲）而不是手改成品。

## 画面层缓存与显式渲染

默认缓存和显式 `--visuals` 都核对内容来源。自动渲染写 `<visuals>.sources.json`，记录来源指纹与画面文件哈希；缺证明或来源变化默认拒绝，显式 `--render` 才重新编码。旧缓存/外部画面经人工核对确属当前版后，加 `--visuals-confirm-current` 补记一次人工确认。这个声明不替代 render_gate，不自动证明创作内容正确。仅改文件时间不能使旧画面放行。

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

## 成片被二次剪过：`edit/cut-map.json`

EDL 项目的默认时间关系是：剪点由 EDL 表达、字幕从同版时间证据派生，画面消费派生时间脊柱。
如果成片是在渲染之后**又剪过一次**（例如为了省一次重渲，把成片里的停顿直接剪掉），
交付物其实有两条时间轴：母版（EDL 渲染的那一版）和成片。**这条路径不是默认做法**；
真要做，剪点必须声明在 `edit/cut-map.json` 里，否则 `verify_delivery.py` 直接拒绝交付。

```json
{
  "version": 1,
  "masterDuration": 354.1,
  "master": "composition/assets/person.mp4",
  "cuts": [[11.5, 12.54], [33.98, 34.69]],
  "srt": {"source": "edit/subtitles.srt", "film": "成品/v2_字幕.srt"}
}
```

- `masterDuration`：剪前母版被使用的时长（秒）。成片应有长度 = 它减去落在其中的剪点。
- `cuts`：**母版时间轴**上的剪切窗口（秒），升序、不重叠；窗口必须落在静音里（由项目自己的
  剪片脚本保证，静音判据可复用 `helpers/_silence.py`）。
- `srt.source` / `srt.film`：剪前字幕与剪后字幕。剪后字幕必须能由剪前字幕 + `cuts` 逐条复算出来。

**时间映射是单调不减的分段函数**：`t' = t - 已剪时长(t)`；窗口内部的时间压到窗口起点
（窗口是静音，字幕不应整条落在里面）。复算实现在 `helpers/_cutmap.py:remap_cue()`。
**不要**在循环里一边改 cue 的时间、一边拿改过的时间去和后面剪点的原始坐标比较——
2026-10-22 XHS v2 就是这么写的：跨刀的 cue 每步少扣一次刀长，最大偏 3.2 秒，而旧核验全绿。

`verify_delivery.py` 在 `edit/cut-map.json` 存在时：

1. 校验 schema 与路径（母版时长、剪点升序不重叠、前后字幕都在）；
2. 成片时长必须等于 `masterDuration - 被剪时长`（容差 0.5s）；
3. `srt.film` 必须与 `srt.source` 按剪点复算的结果逐条一致（条数、文字、起止 ±20ms）；
4. 交付目录里的成片/字幕按名字或哈希对回 cut-map 声明，不误报「找不到对应文件」。

没有 cut-map 但成片比渲染记录短 >0.5s → 硬失败，提示把剪点写回 EDL 重渲，或补 cut-map。

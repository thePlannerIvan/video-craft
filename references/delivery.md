# 交付：`deliver.py`（画面层 + 人物 + 声音 + 字幕 → 成片 + 核验报告）

> 出片阶段才读本页。每轮默认终点是侧边栏审阅页（见 [SKILL.md](../SKILL.md)「每轮终点：审阅页，不是成片」）；
> `edit/_engineering/**` 的渲染只是审阅素材，写 `成品/` 必须作者明确出片 + 人工提交覆盖当前快照。

## 它覆盖的真实形态

2026-10-21 三条片的形态不是"一次渲染出成片"，而是：

- **composition 只做画面层**：黑底，人物位与字幕安全区留空——坐标只有一个来源，即 `recompose.json` 的 `personSlot` / `captionSafe`（见「用法」），本页不抄数字；
- 人物与声音在**交付阶段贴回**；
- 字幕优先**外挂 SRT**（本机 ffmpeg 往往没有 libass，烧录要显式要求）。

这种形态以前没有入口，交付方只能手写 ffmpeg overlay。现在它是一条命令。

## 当前交付顺序与完成线

模型先核对作者明确出片指令、当前版本人工审阅与未决意见处理；render_gate 仅检查快照有提交及 manifest 变化，不能推断反馈内容是否批准。

0. 画面层渲染用 `--workers 1`（多 worker 截图通道会在长片后半段静默丢内容，见 GOTCHAS #79）；独立导出 recompose 的「画面成片」（纯画面轨、不经 `deliver` 的产物），渲染完先跑 `check_render_fidelity.py`。渲染前先停预览服务（`pkill -f "hyperframes preview"`，`probe_env` 的 stray 计数应归 0）：预览服务抢 GPU，实测抓帧会从 25fps 掉到 0.9fps；顺序上等作者在页面提交之后再停。作者口头说「可以导出」不产生提交记录——先请作者在审阅页提交一次（内容写「可以导出」即可），再跑 `render_gate.py`。
1. `deliver` 编码前执行环境探测、适用的 film verify、HyperFrames check 和 GSAP selector/transform 检查；显式 `--visuals` 也须通过来源与版本检查。画面层可读之后立刻跑 `check_render_fidelity.py`：抽样时间点与 composition 的 `hyperframes snapshot` 逐帧比结构相关与墨量，红即停（这一步抓的是「渲染产物与 composition 不一致」，运动/黑帧/分辨率都量不出来）。
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
| **画面层与 composition 一致** | 抽样时刻逐帧比结构相关（≥0.93）与墨量（成片墨量 < 快照 1/3 判丢失）；这一项抓渲染通道静默丢内容，性能上约 10–20 秒 |
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

## 交件的叫法（recompose 两腿交付）

一件片子按交付形态叫三个名字，文档与对话统一用它们。**这三个名字只用于 recompose 路线**
（composition → `deliver.py` / 两腿交付）；montage 路线有自己的一套同名件，音频规格相反，
见本页下文「蒙太奇项目的三件套」——核验前先确认路线，别拿这一节的定义去核另一条路线的件。

- **成片**：人物 + 画面 + 声音 + 字幕合成后的那一条
- **人物成片**：只含口播人物轨
- **画面成片**：只含画面层（没有人物、没有烧字幕）——**纯画面轨**

程序当前的输出文件名这轮不改（改名会让老项目和已有习惯失效）；新项目按这三个名字命名。

## 两腿交付（recompose）：画面层与口播层分开

画面层与口播层分开交是合法形态（[recompose-mode.md](recompose-mode.md) 的「仅画面层」）。顺序固定，每一步都核实际文件：

```bash
# 0 闸门：作者在页面上提交过当前快照
python3 "<craft>/helpers/render_gate.py" "<project>" --out "<project>/成品/03_画面成片.mp4"

# 1 画面层：单 worker 渲，去掉音轨，再核 render fidelity
(cd "<project>/composition" && HYPERFRAMES_FONT_CACHE_DIR="$PWD/.hf-fontcache" \
   npx hyperframes render . -w 1 -q delivery -o renders/03_animation.mp4)
ffmpeg -i "<project>/composition/renders/03_animation.mp4" -an -c:v copy "<edit>/03_画面成片.mp4"
python3 "<craft>/helpers/check_render_fidelity.py" "<project>" --video "<edit>/03_画面成片.mp4"

# 2 口播层：交付态（CRF20 / −14 LUFS）重渲
python3 "<craft>/helpers/render.py" "<edit>/edl.json" -o "<edit>/cut.mp4" --no-subtitles

# 3 打包（字幕自动修剪映导入空隙）+ 指纹
python3 "<craft>/helpers/export_deliverables.py" "<edit>" \
  --videos "cut.mp4=01_口播成片.mp4" "03_画面成片.mp4=03_画面成片.mp4" \
  --srt "subtitles.srt=02_字幕.srt" --out "<project>/成品"
python3 "<craft>/helpers/state_fingerprint.py" capture "<project>"
```

recompose 两腿的「画面成片」是**纯画面轨**（合成时铺在口播之上）；口播成片带声音；字幕只外挂不烧录。三条都核真实文件的时长/帧率/音轨/首中尾帧后再交付。montage 的「画面成片」相反，带口播音轨，核验按「蒙太奇项目的三件套」。

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

## 蒙太奇项目的三件套

> 什么时候读：片型是 **montage**，作者**明确出片**时。三件是并排的交付物，不是一条成片切三段。
> 走法与顺序见 [montage-route.md](montage-route.md) 第 5 节；这一节定的是每件的口径、命名与核验。
>
> **默认终点是审阅页，不是这里。** 蒙太奇的审阅对象是 `montage.py render --concat` 的默认产物
> `edit/_engineering/picture.mp4`（**审阅素材**，可随时重渲）；三件套写进 `成品/` 才叫交付，
> 前提是作者明确出片指令 + 人工提交覆盖当前快照（`render_gate.py` 放行）。`render --concat` 的
> `--out` 不在 `edit/_engineering/` 下时必须同时给 `--deliver`，否则退 1 并指向这条边界。
>
> **口播成片用 `montage.py voice-cut`**：母版 + `edit/edl.json` + 画框 canvas → 竖屏人物轨（无声画面），
> 默认 `edit/_engineering/voice_cut.mp4`（审阅素材）；要带口播音轨必须显式 `--audio`；
> 命令打印时长并与 `plan.timeline.total` 比对。

| 件 | 是什么 | 规格 |
|---|---|---|
| **画面成片** | `montage.py render --concat` 的产物（默认 `edit/_engineering/picture.mp4`） | 画幅 = 画框 canvas（竖屏 1080×1920）；时长 = 时间轴总长（不是素材总长）；**带口播音轨**（给了 `--audio` 或 `plan.audio` 时）；字幕区留白、不烧字幕。写 `成品/` 要 `--deliver` 并先过 render_gate |
| **口播成片** | `montage.py voice-cut` 的产物：母版按**同一 EDL** 剪出的竖屏人物轨 | 默认无声；要口播音轨显式 `--audio`；默认 `edit/_engineering/voice_cut.mp4`（审阅素材）；无画面层、无字幕；从母版剪，不用 proxy |
| **外挂 srt** | `edit/subtitles.srt` | 剪后时间；与画面成片同轴；只外挂不烧录 |

`montage.py render --concat` 只在给了 `--audio`（或镜头表里写了 `audio`）时才混音；
没给就是一个没有音轨的审阅素材。交付前先确认它真的有声，别默认“带口播音轨”是自动的。

### 命名与必须交代的事

| 件 | 建议文件名 | 交付说明必须写 |
|---|---|---|
| 画面成片 | `成品/<片名>_画面成片.mp4` | 有声/无声 · 烧录/外挂 · 是否含档案台标（几处、在哪个角） |
| 口播成片 | `成品/<片名>_口播成片.mp4` | `montage.py voice-cut --audio …` 的产物；有声；无画面层、无字幕；按哪一版 EDL 剪 |
| 字幕 | `成品/<片名>_字幕.srt` | 外挂；与画面成片同一时间轴 |

例：`成品/哈雷_画面成片.mp4：有声（口播音轨）、不烧字幕、含 4 处档案台标（右上 AP / British Pathé）`。
三项声明对每一件都要写，不适用的写「不适用」（如 srt 的「有声/无声：不适用」），不要留空。

三项里最容易漏的是台标声明：画面里的档案角标是合格素材（判据见
[media-sourcing.md](media-sourcing.md)），但没写进交付说明，接收方就分不清它是资产还是事故。
老项目的编号命名（`01_口播成片` / `03_画面成片`）不改；新项目按上表。

### 核验

| 件 | 命令 | 通过线 |
|---|---|---|
| 画面成片 | `check_montage.py "<project>" --video "<画面成片>"` | 退 0；报不出成段黑帧；时长与时间轴一致 |
| 画面成片（若适用） | `verify_delivery.py "<edit>" --video "<画面成片>"` | 适用严格项全绿；没有 EDL 渲染记录时不硬套 |
| 字幕 | `srt_export.py "<edit>" --build --check` | `caption check OK` |
| 口播成片 | `ffprobe` 核时长与音轨；`montage.py voice-cut` 自报的时长与 `plan.timeline.total` 比对 | 时长 = 时间轴 ±0.5s；有音频流；无画面层 |

- **口播成片只核时长与音轨，不重复核画面。** 画面那一关已经在画面成片过了一遍，
  重复核只会制造“核了很多”的假安全感。
- **逐镜体检不是交付核验。** `--shots-dir` + `--base` 是渲染阶段的自检；交付只认 `--video`。
- **montage 不跑 `check_render_fidelity.py`。** 那一项比的是成片与 composition 快照，
  montage 没有 composition（脚本会报找不到并退 2），画面由 `check_montage` 的逐镜 + 成片两关负责。

### 与 `deliver.py` 的边界

这三件不替代本页开头那条 `deliver.py` 的严格核验（人工审阅闸门、字幕安全区、首中尾帧、
交付指纹）。montage 的合成入口不是 `deliver.py`——它依赖 composition 与 `recompose.json`
的几何和来源检查，所以这条路线出片时的交付形态是三件套（审阅阶段只看 `picture.mp4`，
不写 `成品/`）。但只要某个环节仍走了
`deliver.py` / `stage_deliver`（例如要把画面成片和人物轨合成一条「成片」），
那一步的严格核验照跑，**不因为“三件齐了”就跳过**。两者都适用时，以更严格者为准。

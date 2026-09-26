# Review UI (v2)

**另一套审阅页在 `<项目>/_idea/reviews/script/`，属于 `video-idea-system`**（一个念稿审阅面：
左口播、右样张、下双反馈）。两套不合并：这一套审的是**剪辑与画面**，那套审的是**稿子与内容契约**。
按下面的条件交棒——

| 现在的状态 | 用哪一套 |
|---|---|
| 稿子或逐屏上屏文字要改 | `<项目>/_idea/reviews/script/`（回 `video-idea-system`） |
| 剪点取舍、逐段画面与节奏要改 | 本页（`helpers/review_surface.py`） |
| 两边都要改 | 先回 `video-idea-system` 定稿与契约，再回到本页 |

把本页的审阅指到一个只装了 idea 审阅页的项目会**报错退出**（要 `<project>/review/index.html`
与 `<project>/timeline/timeline.json`）——那是正确行为，不是故障：它不会端出上一个会话的旧项目。

Step-level feedback stays the core review mechanism, but the visuals are
now the HyperFrames composition, played back inside the review page via
`<hyperframes-player>` instead of bespoke React chapter components.

## 先选能审实际结果的入口

剪接页用于取舍口播，不能代替视觉审阅。默认优先审**已编码画面＋当前口播声音**的片段，可用原生 video 和 Range/时间片段播放；需要检查内部状态时才启动下述 HyperFrames 实时预览。已有可用审阅页就复用，不为每个镜头新建播放器或服务。

打开前验证作品版本、当前画面和声音、区间跳转、一次测试保存再读回；测试反馈隔离于作者反馈（收件只读 surface 声明的那份提交文件，自检与收件都不往 `feedback/*.jsonl` 里塞非作者内容）。自动播放受浏览器限制时让用户点击播放，不以静音掩盖。仅为有权管理的本次服务记录 PID/端口，不为了端口冲突杀其他项目服务。

### 变化戳与陈旧判定

surface 的 `watch` 声明 `../timeline/timeline.json`（**相对 surface 文件**）。那个文件的
mtime/size 一变，宿主就戳一下页面；宿主**只看元数据、不知道什么变了**，所以页面收到戳之后
自己 `readText` 读回时间轴、自己 diff。对不上就在保存条上方出一条橙色提示，说清
「页面上的 step 边界与 caption 是上一版」并建议重新加载。

**diff 的口径＝「记录会抄走什么，就比什么」**：`caption`、`durationMs`、`stepIndex`、step id、
章节 id/title、总时长。**只比结构会漏掉 caption** —— 而那正是记录抄走的字段：人对着旧文字提的
意见，会挂着一条已经不存在的话。实测触发过一次（只改一句 caption 验戳），所以这一条钉在测试里
（`test_review_browser.py` 的 ⑦ 步）。

它**不硬拦提交**（读不到可能只是暂时的，把人锁在外面比一句诚实的提示更糟），也**不发明版本号**
—— `codeVersion` 仍是本面的已知缺口（见 Feedback schema 那节）。权威在产出方这一侧。

修订后先呈“这轮改了什么”的短表和受影响片段；镜头顺序/时间变动还需看前后衔接，方向与样式已批准的段落无需每轮重审。最终再提供整片带声审阅。

## Review page

`visual/assets/review-page-template.html` is the v2 review page. Copy it to
`<project>/review/index.html` — 页面要**经审阅宿主**打开，不能双击打开文件：
它的时间轴与反馈都走审阅桥。模板里留了一个**注入点**：那个双花括号标记**裸着独占一行**
（放进 `src=""` 里或塞进 `<script>` 里都会被宿主的整段替换撑破标签），全页**只许一个**。
宿主 serve 时把它换成桥；**不要在页面里放一份桥的副本**（有插件时页面地址是一条路由而不是
文件路径，相对引用会 404）。

```html
<script type="module" src="https://cdn.jsdelivr.net/npm/@hyperframes/player"></script>
<hyperframes-player src="http://localhost:5176/api/projects/composition/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player" controls autoplay></hyperframes-player>
```

两个路径基准要分清（实测踩过）：
- **页面里的 `rel` 一律相对 `dir`（＝项目根）**：`timeline/timeline.json`、
  `review/review-submissions.json`。本页在 `review/` 子目录里，所以 `connect()` 时
  自己给 `base: '../'`——桥在无插件时的默认 base 是**页面自己那一层**。
- **`review-surface.json` 里的路径**（`project_root`/`dir`/`entry`/`feedback`）相对
  **surface 文件**；`watch` 也是（这一条曾经三种读法不一致，2026-09-26 统一）。

播放器那条 `src` 是**绝对跨源 URL**，不走审阅桥（桥只送 `dir` 里的文件）。它是这个面上
唯一绕过缝的资产 —— 也正因为如此，**它在插件宿主（不透明源侧栏 iframe）下能不能加载
没有实测**。判据与降级见下面那节。

The player loads the composition in a sandboxed iframe, auto-detects
dimensions/duration, and provides play/pause + scrubber, so the user
can pause exactly on a problem frame. Useful attributes: `poster`,
`playback-rate`, `muted`, `autoplay`, `loop`.

## 播放器必须指向 preview 服务器的运行时注入端点（非原始文件）

**非显然知识（实测得出）**：clip 可见性切换和音频播放由 HyperFrames 运行时
管理，而运行时只在两种路径注入：渲染器、`hyperframes preview` 服务器。
用静态文件服务器（如 python http.server）直接加载 `composition/index.html`
时没有运行时——时间轴会走，但所有 clip 同时可见（画面叠在一起，只剩 DOM
最后的 clip），音频也不播放。

因此审阅流程必须：

```bash
cd composition && npx hyperframes preview --port 5176 &   # 运行时注入服务器
```

播放器 `src` 指向该服务器的预览端点（`<meta.json>` 里的 `name` 决定路径段）：

```
http://localhost:5176/api/projects/composition/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player
```

`hyperframes preview` 会额外启动一个 Studio 壳（默认端口），审阅页只需
上述端点。端口被占用时换端口并同步改 src。

## 审阅页与审阅宿主（公共缝）

审阅页自己需要一个 http 源（要读时间轴、要提交反馈），而且它要能在**两种宿主**下跑同一份
代码：有 DSH 插件时挂在侧栏 iframe 里，没有插件时由公共件起一个本地服务器。所以这一层
**不再由本 Skill 自己写服务** —— 它交给公共缝 `planners-review-core`（审查阅面的
`review-surface.json` + 桥 + 宿主）：

```bash
# <project> 是含 review/ timeline/ composition/ 的项目目录
python3 helpers/review_surface.py <project>                  # 起无插件宿主，就绪后自动开浏览器
python3 helpers/review_surface.py <project> --no-open        # 同上，不开浏览器
python3 helpers/review_surface.py <project> --surface-only   # 只写 surface 报路径，不起宿主（宿主有 review_open 工具时用这条）
python3 helpers/review_inbox.py <project>                    # 收件：把提交翻译成 feedback/<chapterId>.jsonl 追加
```

解释器按 `SKILL.md` 的 Setup 用 `02-skills-library/.venv/bin/python`；
系统 `python3`（3.9.6）跑同一条命令同样成立。作者那侧只需要打开打印出来的 URL。

**页面必须先存在**：把 `visual/assets/review-page-template.html` 复制到
`<project>/review/index.html`（见下节）。缺页或缺时间轴时 `review_surface.py` 会**在起宿主
之前**报出来，不给人一个存不进去的页面。

### 反馈走两跳，形状在收件时翻译

宿主只会**覆盖写一份**文件（surface 的 `feedback` 字段：`review/review-submissions.json`）。
本 Skill 的存储形状是**每章一份、只追加**。两者对不上时**不改本 Skill 的形状**：
页面每次保存先把那份提交文件读回来、追加自己这条、再整体写；模型侧跑 `review_inbox.py`
把提交翻译成 `feedback/<chapterId>.jsonl` 的追加（先写 `.tmp` 再 `os.replace`，旧内容进
`feedback/.previous/`）。收件按**记录内容的哈希**去重，所以跑两遍不会长出第二条，
而作者真的重写一遍同一句话（`createdAt` 不同）算新意见。

**判断宿主死活也用 HTTP GET，不要用端口探测。** 审阅是跨回合的：作者拿到 URL 之后要
回到对话里写意见，过一会儿再回来提交。那段时间里进程可能已经不在了，**而它留在那个端口
上的 socket 仍可能接受 TCP**——`nc -z` 报 `OPEN`，同一端口上 `curl` 却得到 `000`／空响应。
`host_alive()` 的判据是：pid 还在 + 页面回 200 且注入过桥 + **`watch` 声明的项目文件逐字节
等于磁盘**。第三条就是「不端出旧项目」：老宿主靠绑死 8899 端口做到这件事，新宿主用
`--port 0`，端口不再有判断力，**内容才有**。

### 剪接预演面（同一份缝上的**第二个面**，形状不同）

`helpers/edl_review_surface.py` 声明的面与上面那个视觉面**不是一个形状**，值得对照着读：

| | 视觉审阅面 | 剪接预演面 |
|---|---|---|
| 审什么 | 逐屏画面 | **在板子上挑**（删哪些词/停顿、恢复哪段、改哪个字） |
| `dir` | 项目根 | **素材与剪辑目录的公共根** —— 页面里那些 `/<素材>.mp4` 从写出来那天起就假定 serve root 是它 |
| 落点 | 一份提交文件 → 收件时**翻译成追加** | **`selections.json` 本身**：整份覆盖，**不需要任何收件层翻译** |
| 整体意见 | 一条记录进 JSONL 之后 | **只走 `wake`，不写文件**（写进去会被 `apply_selection.py` 静默忽略——那是个死字段） |

它曾有一台自己的服务器（`edl_preview_serve.py`，固定端口 8737、`/api/save`）——**已退役**。
那台服务器要的东西里有一样是缝原本没有的：**Range**（播放器在 SOURCE 时间轴上拖，素材
0.5–2 GB）。这一面是**第四家**，也是第一个逼出"宿主得支持分段取"的：宿主的静态分支现在认
`Range`（`206` + `Content-Range` + `Accept-Ranges`；不可满足回 `416`；多区间故意不支持）。
共享的安全习惯不变：宿主只搬字节、落原样、叫人。

## Feedback schema (unchanged from v1)

Feedback is JSONL, one object per line, saved to
`feedback/<chapterId>.jsonl` (and `feedback/storyboard.jsonl` for the
Plan checkpoint):

```json
{
  "chapterId": "intro",
  "stepId": "intro-003",
  "stepIndex": 3,
  "caption": "Current caption text",
  "durationMs": 7500,
  "type": "visual",
  "text": "This screen is too dense.",
  "status": "open",
  "batchId": "review-20260705-1",
  "createdAt": "2026-07-05T12:00:00.000Z"
}
```

These ten fields are exactly what the page emits; two fields once intended are absent — `codeVersion` (binding feedback to the composition version it was written against) is a **known open gap**, and `srtRange` is redundant with the `stepIndex`/`cueRange` the timeline already carries.

Allowed `type` values: `visual` / `timing` / `asset` / `copy` / `animation`.

**第二种形状：不针对任何一屏的记录。** 页面有两条入口 —— 「当前屏」与「整片意见」，后者
**不需要先选一屏**（模组 `design-and-porting-rules` 的 R10：页面不许把逐单位当成唯一入口）。
这种记录**没有单位字段**，靠自己的 `phase` 定位落点：

```json
{
  "phase": "overall",
  "type": "timing",
  "text": "整片节奏偏慢，第三段可以再压一压",
  "status": "open",
  "batchId": "review-20260926-1",
  "createdAt": "2026-09-26T00:00:00.000Z"
}
```

`phase` 已经有两个值，各落各的文件（**都不是** `feedback/<chapterId>.jsonl`）：

| `phase` | 是什么 | 落在哪 |
|---|---|---|
| `storyboard` | Plan 检查点（规划阶段那一遍反馈） | `feedback/storyboard.jsonl` |
| `overall` | 整片意见（看完整片想说的一句） | `feedback/overall.jsonl` |

**不许给这类记录编一个假的 `chapterId`/`stepId`** —— 那正是"改形状"，而且会让下游以为
这条意见针对的是某个单位（`feedback/overall.jsonl` 里一个单位字段都没有，是能 grep 验的）。

### 可选字段：`stale` / `stale_timeline`（**只在真陈旧时出现**）

**为什么有它**：页面顶部那条橙条（时间轴在作者写着的时候变了）原本**只说给人听**。于是收进来的
记录干干净净，模型不知道那是"对着旧文字说的意见"—— 那句提示存在的全部意义在机器那一侧失效。
规则（模组 `design-and-porting-rules` 的 **R5b**）：*只给人看的告警 ＝ 机器看不见的告警*。
页面上任何"警告/前提/免责"，问一句"它该不该影响拿到这条数据的人怎么读它"，该就进数据。

```json
{
  "chapterId": "painout", "stepId": "painpoint-005", "type": "visual",
  "text": "这句话得改",
  "stale": true,
  "stale_timeline": "3f2a91c4",
  "status": "open", "createdAt": "…"
}
```

| 字段 | 何时出现 | 什么意思 |
|---|---|---|
| `stale` | **只在**页面检测到"我手上这版时间轴已经和磁盘上那版不一样"之后提交时；否则**没有这个字段** | 这条意见是**对着某一版旧时间轴**说的 |
| `stale_timeline` | 与 `stale` 同时出现 | 页面**手上那一版**的 id（8 位十六进制，同一版 → 同一个 id）。它让"对着同一版说的几条"能归到一起 |

两条约定：
- **不是常态字段**：没有橙条就不许出现（`grep '"stale"' feedback/*.jsonl` 应当只命中真陈旧的记录）。
- `stale` 说的是"**提交时**页面已知自己是旧的"，不保证那条意见一定指错了东西 —— 判它对不对是
  模型的事（见下面 agent 协议 3c）。

保存没有复制粘贴这一步，但**是两跳**：页面的「保存反馈」把这一条交给审阅宿主（写进
surface 声明的那份提交文件 `review/review-submissions.json`），模型侧跑
`python3 helpers/review_inbox.py <project>` 收件，逐单位那条**追加**进
`feedback/<chapterId>.jsonl`（文件名由 `chapterId` 折出，记录里保留原样的 `chapterId`），
带 `phase` 的那两条按上表各进 `storyboard.jsonl` / `overall.jsonl`。追加是先写 `.tmp` 再 `os.replace`，
不会留下半条记录；写之前的旧内容留在 `feedback/.previous/<name>.jsonl`——备份故意不叫
`*.jsonl` 放在旁边，否则会被下面第 1 条的 `feedback/*.jsonl` 当成作者反馈读回来。
页面状态条常驻显示未保存／保存中／已保存 HH:MM:SS + 目标文件；保存失败时文字留在
输入框里，不丢。记录字段一律透传，收件只补 `status`（缺省 `open`）和 `createdAt`
（页面没带时才补）——schema 变动不需要改收件，也不需要改宿主。

## Agent read protocol (must follow)

1. Read all `feedback/*.jsonl` files.
2. Sort by `createdAt` ascending to understand order; the latest
   `batchId` round has highest priority.
3. Group by `chapterId` + `stepId`; skip old feedback superseded by a
   newer one on the same step.
3b. A record that carries `phase` (`storyboard` / `overall`) is **not about a
   single step** — treat it as one opinion about that whole pass. It lives in
   `feedback/storyboard.jsonl` / `feedback/overall.jsonl` and has neither
   `chapterId` nor `stepId`; do not attach it to a step, and do not skip it
   because it has no step to group on. An `overall` opinion is the author
   speaking about the finished piece — it usually outranks per-screen nits.
3c. A record carrying `stale: true` was written while the page's timeline was
   already out of date. **Before acting on it, check it against the current timeline** —
   the record's own `caption` (or, for an `overall` record, the current cut) is what the
   author was looking at; if that has changed, confirm the opinion still points at the
   same thing instead of applying it blind. `stale_timeline` groups records written
   against the same old version.
4. Fix the smallest affected screen (edit `composition/index.html`).
5. Keep timing unchanged unless feedback type is `timing` and the user
   explicitly accepts regrouping (then regenerate upstream).
6. Re-run `cd composition && npm run check` — 0 errors.
7. Mark processed feedback `status: "resolved"`.

## Fix Loop

Feedback → fix composition → `npm run check` → re-render (~30s) →
show the new MP4. Fast enough to iterate per feedback round.

## 审阅页的三条硬约定（2026-09-21 三次投诉换来的）

1. **审阅副本必须带声。** 画面审阅的切片要从一条「画面 + 口播音轨」的审阅副本里切
   （交付件本身仍无声）。默认 `<video muted>` 会让人无法判断节奏。
2. **保存状态常驻可见。** 自动保存可以，但必须有一个固定的状态条：未保存 / 保存中 /
   已保存 HH:MM:SS + 一个「立即保存」。把提示放在角落等于没有提示——作者会以为丢了。
3. **每轮反馈归档。** 页面加载旧反馈、下次输入连同旧的整份重存，会让上一轮已处理的
   意见看起来像新意见。开新一轮前归档 `<name>.round-N.json`，已解决项退出待办，未解决项显式携带；新输入为空。不能把清空页面当成所有反馈已处理。按[偏好与反馈记录](preferences.md)维护版本、稳定 ID 和处理结果。

切片用 media fragment（`video.mp4#t=start,end`）指向审阅副本的区间 + 服务端支持
Range，就不必为审阅渲染任何中间文件。

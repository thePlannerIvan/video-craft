# 活舞台契约：一份 composition 要能进审阅页

`hyperframes check` 全绿**不证明**审阅页能播。2026-10-21 的 XHS 三条片就是反例：
工程在官方播放器里 6:08、画面正确；同一份工程进审阅页后时长 0、舞台区全黑、右侧人物照常，
而 `hyperframes check --json` 退 0，`runtime.duration` 为 `null`、`contrast.checked` 为 0
（时间轴没建，连可测的文字都没有）。这条差异不是 bug 偶发，而是两条加载路径不同。

本文写死「能上活舞台」的五条契约，以及它们各自的失败形态。静态自检是
`helpers/check_live_stage.py`；`build_review.py` 之前先跑它。

## 两条路径为什么不一样

| | 官方播放器 / 渲染（`hyperframes play`、`render`） | 审阅页活舞台（`build_review` → player `srcdoc`） |
|---|---|---|
| `index.html` 来源 | 预览编译服务按原文件起 | `live_preview.py` 把编译结果装进页面，再交给 player 的 `srcdoc` |
| `src=` 外部脚本 | 编译器改成 `type="text/hf-after-fonts" src=...`，由预览 runtime 在字体就绪后重跑 | `live_preview` **把 `src=` 的内容取回来、内联成普通 `<script>`**，所以会执行 |
| 内联 `<script>` | 同样改成 `type="text/hf-after-fonts"`，由同一个 runtime 重跑 | 原样留下这个数据块；srcdoc 里没有东西替它重跑，**永远不执行** |

结论只有一句：**会执行逻辑的脚本必须是外部文件**。编译器把内联 script 当“字体就绪后再跑”
的延迟块，而审阅页的 srcdoc 没有那条延迟通道。

## 五条硬契约

### 1. 根元素

```html
<div id="root" data-composition-id="main" data-start="0"
     data-width="1920" data-height="1080" data-duration="368.4" data-fps="30">
```

- `data-composition-id` 全文件**唯一**；播放器与 bridge 都按它找时间轴。
- `data-width` / `data-height` 是画布像素，也是活舞台视口；缺了会按 0 尺寸起。
- `data-duration` 是标称时长；真正的时长仍由时间轴决定，但缺失时播放器拿不到可 seek 的区间。

### 2. 时间轴：一个暂停的 timeline，注册名等于 `data-composition-id`

```js
// src/boot.js（外部文件）
window.__timelines = window.__timelines || {};
window.__timelines["main"] = HF.tl;     // 名字必须等于 #root 的 data-composition-id
```

注册名与 `data-composition-id` 不一致时，不同路径拦得住的时机不一样：`hyperframes check`
会报 `timeline_id_mismatch`，但更早的写法、或者只改了一边的半成品，不一定会被所有路径拦住。
审阅页拿不到 `__timelines[<id>]` 就是 0 秒。

### 3. 会执行逻辑的脚本全部在 `src/*.js`

被编译器改写的典型内容：

- `window.__CFG__ = {...}`（章节表、总时长）
- `HF.build()`（建时间轴）
- `window.__timelines["main"] = HF.tl`（注册）
- 任何“读配置 → 建 DOM → 挂补间”的启动代码

搬到外部文件后，`index.html` 只留引用：

```html
<script src="src/config.js"></script>
<script src="src/core.js"></script>
<script src="src/scenes/beat-01.js"></script>
<script src="src/boot.js"></script>
```

**`hyperframes check` 的 lint 又要求 `index.html` 里能看到 `window.__timelines` 初始化**
（缺失时报 `missing_timeline_registry`）。这两条要求同时成立，写法只有一种：末尾保留一行
**只建容器**的内联脚本，注册仍在外部文件里。

```html
<!-- lint 要求：本文件里要能看到 window.__timelines；
     真正的注册在 src/boot.js，别在这里赋 tl -->
<script>window.__timelines = window.__timelines || {};</script>
```

判断标准：内联的那行右边的值是 `null` / `undefined` / `{}` / 自引用兜底（`window.__timelines.x || null`），
它只保证容器存在；出现 `= tl`、`HF.tl`、`HF.build()` 就是真注册，必须移走。

### 4. 嵌入桥必须随 composition 在

```
<composition>/assets/composition-embed-bridge.js
```

由 `visual/scripts/generate-composition.py` 的 `BRIDGE_FILE` 约定拷贝进来，并在 `index.html`
里以 `src=` 引用。审阅页跑在不透明源的 sandbox iframe 里，够不着子页 DOM，`postMessage`
是唯一通道；bridge 是 composition 自己的控制面。缺文件时页面不会报错，只是**不能定位、
不能播放**。

### 5. 媒体尺寸策略

活舞台把 `liveStage.composition.assets` 的每个值变成 player srcdoc 里的 data URL，所以
**资产表的体积就是页面首次加载的体积**。

| 规则 | 数值 | 谁执行 |
|---|---|---|
| 单件资产预算 | `LIVE_STAGE_ASSET_MB = 4.0` | `build_review.py` 超预算就换 `review/proxies/` 下的审阅副本 |
| 合计预算 | `LIVE_STAGE_TOTAL_MB = 12.0` | 超了记 `mediaNotes`，页面仍会变慢 |
| 人物母版 | 不进 composition 资产表，走 `review/media.json` | 审片不需要 1GB 母版；`build_review` 会拒绝下载超大通道 |
| 分辨率 | 先保原生像素、只降码率；**仍超预算**才按 0.75 / 0.5 / 0.35 逐级降分辨率 | `review_copy.make()`，记录里 `scaled` / `scale` |
| 重复音轨 | composition 里 `muted` / `data-has-audio="false"` 的 video，副本直接去音轨 | `fit_live_stage_assets()` 读编译后的 HTML；原声另有 `<audio>` 元素，不去就是白占预算 |

画面层只画“人物之外”的区域时，不要把人物视频塞进 composition：交付形态允许**只有画面层**，
人物在合成阶段贴回（见 [recompose-mode.md](recompose-mode.md) 的「画布与人物区」）。

## 自检

```bash
python3 "<craft>/helpers/check_live_stage.py" "<project>"            # 默认 composition/
python3 "<craft>/helpers/check_live_stage.py" "<project>" --composition composition-v2
python3 "<craft>/helpers/check_live_stage.py" "<project>" --json     # 机器读
```

退出码：0 无 error；1 有 error；2 找不到 composition。检查项：

| id | error 条件 |
|---|---|
| `composition` | 没有 `index.html` |
| `composition-id` | 根元素缺 `data-composition-id`，或有多个 |
| `inline-logic` | 会执行的内联 script 里出现 `HF.build(` / `window.__CFG__` / 真正的 `__timelines[...] =` |
| `rewritten-inline` | 源文件里已经存着 `type="text/hf-after-fonts"` 的数据块 |
| `timeline-registration` | 找不到注册，或注册名 ≠ `data-composition-id` |
| `embed-bridge` | 缺 `assets/composition-embed-bridge.js` |
| `external-scripts` | 引用的本地脚本不存在（预览传输会逐个读文件） |

warning（不拦路）：画布/时长属性缺失、bridge 未被引用、注册名写成变量、composition 内媒体
超过 4MB 单件预算。

**这个检查是静态的，不证明页面能跑。** 它钉的是“这一版会不会在 srcdoc 里静默不执行”；
播放、定位、字幕同步仍要在审阅页里实测。

## 症状对照

| 现象 | 先查 |
|---|---|
| 审阅页舞台 0:00 / 全黑，右侧人物正常 | `check_live_stage.py`；再看 `inline-logic` |
| `hyperframes check` 报 `timeline_id_mismatch` | 注册名与 `data-composition-id` 不一致 |
| `hyperframes check` 报 `missing_timeline_registry` | `index.html` 里没有 `window.__timelines` 初始化那一行 |
| 审阅页能播但没有声音 | 媒体是否走 `review/media.json`；`review_data.json` 的 `mediaNotes` |
| 审阅页卡在“预览暂时无法连接” | 先看 `mediaNotes` 的资产预算，不要先怀疑服务 |

## 运行时判据：`check_review_playable.py`（静态检查之后必须跑这一条）

静态检查只能证明"这一版不会被静默改写"，证明不了"页面打开就能看、能听"。实测判据是：

```bash
python3 helpers/check_review_playable.py <project>
```

它自己起本地宿主、用 Playwright 打开审阅页，断言四件事，任一失败退出 1 并指出该修哪一层：

1. 页面挂上了一条播放通道（活舞台 / 合成成片 / 人物轨），并报出是哪一条；
2. **活舞台的时间轴真的构建了** —— 直接读 composition iframe 里的
   `window.__timelines.main.duration()` 与已渲染元素数。这一条是 0 秒事故的唯一可靠判据：
   根元素的 `data-duration` 会兜底成"看起来对"的数字，**只比 player.duration 会漏诊**；
3. 能 seek 到 beat 起点并拿到画面（活舞台按"渲染了多少元素"判，成片通道按解码像素判）；
4. 有声音且未被静音（工程声明为纯画面层时不适用，声音在交付合成阶段贴回）。

### 已确认的 0 秒根因（2026-10-21，两条片子上复现）

`window.__CFG__`（章节表）与 `HF.build()`（建时间轴）**写在 `index.html` 的内联 `<script>` 里**时，
预览编译器会把它们改写成 `type="text/hf-after-fonts"` 的数据块；srcdoc 里没有人替它重跑，
于是章节表为空、时间轴从不构建 → 播放器只有根元素的 `data-duration` 可用，页面显示
`00:00 / 00:00`（内部 `NaN`），舞台停在首帧（黑），右侧人物照常播。

判据：`curl <stageUrl> | grep -c 'text/hf-after-fonts'` 大于 0，且其中包含配置/启动逻辑，
就是这一条。修法只有一个方向 —— **把会执行逻辑的脚本挪成外部文件**（`src/*.js`），
`index.html` 里只留静态契约所需的注册语句。

复现夹具（可直接用来验判据是否还有效）：

```bash
# 造一份坏工程：把 src/config.js、src/boot.js 内联回 index.html
# 期望：check_review_playable.py 在「活舞台的时间轴真的构建了」上变红（timeline.duration=0, 已渲染元素=0）
# 把两者改回外部文件后重跑，同一断言转绿（timeline.duration=368.4, 已渲染元素=147）
```

### 「有声音」要两条路都看

工程态审阅时，**旁白在 composition 的 iframe 里**（`<audio data-start data-duration>`），
不在页面层的 media 通道里；只扫页面级 `<audio>/<video>` 会把"能听见"误判成"没有声音"。
`check_review_playable.py` 因此两路都查：

1. **页面级通道**：`#stage-speaker-video` / `#composite-video-player` / 页面 `<audio>`；
2. **composition 内**：进 iframe 查 `audio[data-start]` / `video[data-start]` 的
   `muted` / `volume` / `readyState` / `duration`，并把 `currentTime` 是否推进作为附加证据。

任一路满足即绿，并在 detail 里写明声音来自哪条（"页面级通道" vs "composition 内旁白"）。
判"能出声"用**解码就绪 + 未静音 + 有音量 + 有长度**，不强制要求时钟推进——页面停在
seek 点时官方播放器会主动暂停媒体。

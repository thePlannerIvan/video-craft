# 合成事实的字段契约：`composite` / `personWindow` / `captionSafe`

> 本文涉及 page 路线的段落已归档（见 [legacy-page-route.md](legacy-page-route.md)）；现行 recompose 路线见 [film.md](film.md) 与 [recompose-mode.md](recompose-mode.md)。命令集中在 [tools.md](tools.md)。


这三件事回答同一屏的合成问题：**这一屏是满屏替换，还是压在人物上**，以及**人物的画面矩形在哪**、
**字幕安全区留了多少**。它们跨 Skill——做画面那一步写，剪辑这一侧读——所以键名与取值域**只有这一份**：
`planners-ppt-hell` 的视频路线点名要求它们，不自己造字段名；本 Skill 的代码按这里写的名字读。

只写已经实现的东西。这份契约目前就三个键，没有第四个，也没有保留字段。

## 三个键

| 键 | 取值 | 默认 | 谁填 | 谁读 | 缺了会怎样 |
|---|---|---|---|---|---|
| `composite` | `"replace"`（满屏替换）或 `"over-person"`（压在人物上） | 读不到任何一处时按 `"replace"` | 整片默认：做画面那一步写进 `design_direction.md`；单屏例外：写在 `grouping.json` 的那一步上 | `visual/scripts/import_svg_page.py` 读默认；`visual/scripts/generate-composition.py` 合并两处 | **不报错**，按满屏替换处理。压在人物上的那一屏会被当成满屏，人物被画面盖掉 |
| `personWindow` | 矩形 `{"x": int, "y": int, "w": int, "h": int}`，**页面坐标**（= 视频像素，原点左上，单位 px） | 无 | 同上 | 同上 | 不报错；该屏没有人物窗口信息，动效与花字不知道该往哪让 |
| `captionSafe` | 同 `personWindow` 的矩形形状，指字幕安全区 | 无 | 同上 | 同上 | 不报错；该屏的字幕安全区未知 |

**目前没有形状校验**：写错的值会被原样带下去，不会失败。这三个键是给人和下游动画读的约定，
不是一道闸门。将来要加校验，是这份契约加一节，不是调用方各自猜。

## 优先级

```text
单屏（该步 grouping.json 的键）  >  整片（design_direction.md 里带 composite 键的 json 代码块）  >  默认
```

## 整片默认从哪读

`import_svg_page.read_composite_default()` 按顺序找第一个存在的文件，取其中**带 `composite` 键**的
fenced ```json 代码块：

1. `<画面项目根>/_internal/01_content/design_direction.md` ← ppt-hell 自己的位置，优先
2. `<画面项目根>/design_direction.md`
3. `<项目>/input/design_direction.md` ← 上游随包交来时的位置
4. `<项目>/design_direction.md`

代码块形状：

```json
{"composite": "over-person",
 "personWindow": {"x": 1152, "y": 0, "w": 768, "h": 1080},
 "captionSafe": {"x": 0, "y": 860, "w": 1920, "h": 220}}
```

## 落到哪里

`generate-composition.py` 把三个事实写进两处，两处内容一致：

- 该屏 clip 的属性：`data-composite` / `data-person-window` / `data-caption-safe`（后两者是 JSON 文本）；
- `composition/pages/manifest.json` 的 `perScreen[<stepId>]`。

这三个键不参与 `data-start` / `data-duration`，也不改变 clip 的时序——它们只说这一屏怎么合成。

## 谁是谁

- **出版方**：本 Skill（这份文件）。
- **写入方**：做画面那一步（`planners-ppt-hell` 的视频路线）写整片默认；`grouping.json` 的那一步提供单屏例外。
- **消费方**：本 Skill 的 `visual/scripts/import_svg_page.py`（读默认）与
  `visual/scripts/generate-composition.py`（合并、落到 clip 属性与 manifest），以及下游做动画/花字时读那两处。
- **落实**：`replace` 的屏走满屏不透明层（EDL 里 `kind: "opaque"`），`over-person` 的屏走 alpha 层
  （`kind: "alpha"`）——由 EDL 的覆盖层声明执行，见 `composition-craft.md`。

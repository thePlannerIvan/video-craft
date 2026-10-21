# 存档：page 十步路线（不再维护）

## 它是什么

一条以「先把静态页导入成页面、再逐页挂动效」为中心的老路线：

```
visual/scripts/import_svg_page.py     → 导入 SVG 页
visual/scripts/generate-composition.py → 从 timeline.json 生成 composition 骨架
helpers/check_parity.py                → 校验 spec 与 composition / 审阅页两条路径一致
```

## 为什么存档

2026-10-21，作者在三条 6 分钟的片子上把它评为「老的十步不如 recompose」，并明确
**「可以存档了」**。它的代价是结构性的：

- SKILL.md 同时摆着 page / recompose / composite 三个名字 + 一段"能力包组合"，
  入口判断没有一句"你的输入是这个就走这条命令"。结果是实现方**两条都没走**，
  自己手写 composition 把原页重画成抽象几何 —— 作者的原话是"太简单、缺画面、
  不如我 PPT 清楚"。
- 这条路线的重心是"把静态页搬进视频"，而真实需求是"**读懂原页，再按口播把它的信息
  一条条演出来**"。前者不需要理解内容，后者必须理解。

所以：新项目只走 recompose，入口是 `helpers/film.py`。

## 代码现在在哪

| 原路径 | 存档位置 | 现状 |
|---|---|---|
| `visual/scripts/import_svg_page.py` | `visual/scripts/_legacy_page/import_svg_page.py` | 原路径是兼容 shim（`build_review`、`auto_choreography` 仍按原路径 import） |
| `visual/scripts/generate-composition.py` | `visual/scripts/_legacy_page/generate-composition.py` | 原路径是 CLI 转发 shim |
| `helpers/check_parity.py` | `helpers/_legacy_page/check_parity.py` | 原路径是兼容 shim |

shim 只做转发，不含逻辑；改行为请改存档里的那份，或者干脆不用它。

## 什么时候才需要读这份存档

1. **复活一个 2026-10 之前用 page 路线做的老项目**——它的 `composition/pages/` 与
   `timeline/choreography.json` 是那条路线的产物。
2. 需要 `check_parity.py` 那条"spec 里每个效果 kind 在两条路径都有实现"的断言。

新项目不要用。`film.py` 的「原页拆解」替代了它想解决但没解决的问题。

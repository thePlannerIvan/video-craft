# 验收用例

`evals.json` 是给模型读的行为判据：把 `prompt` 当成一个真实任务派下去，然后用 `must_do` /
`must_not_do` 逐条对照它实际做了什么。它不是自动化测试——判断"有没有做到"要人或模型参与。

这里的脚本只做**机械的那一半**：用例文件本身还能不能用。

```bash
python3 evals/run_evals.py     # 从 Skill 根跑；退码 0 = 全过，1 = 有错
```

## 一条用例长什么样

```json
{
  "id": "montage-recorded-voiceover-found-footage",
  "route": "montage",
  "prompt": "口播已经录完了，画面是一批现成的历史影像和照片，没有参考页。……",
  "must_do": ["先跑 scan_materials.py 出帧带与素材清单，……"],
  "must_not_do": ["跳过素材清单，直接按文件名排镜头表"]
}
```

| 字段 | 作用 | 硬要求 |
|---|---|---|
| `id` | 稳定标识 | kebab-case、≤64 字符、整份唯一 |
| `route` | 这条用例压哪条制作路线 | 必须是 `recompose` / `montage` / `frame` / `shared` 之一 |
| `prompt` | 派给模型的原始任务 | 非空；整份不重复 |
| `must_do` | 必须出现的行为 | 非空字符串数组；每条 ≥6 字符、不重复 |
| `must_not_do` | 必须避免的行为 | 同上；且不得与同一条 `must_do` 完全同文 |

### route 的口径

- `recompose`：画面是造出来的（PPT 页 / 图形 / 字卡 / 动效）；
- `montage`：画面是选出来的（档案影像 / 实拍 / 照片）；
- `frame`：版式与画框，与片型正交的一层；
- `shared`：两条片型与两种路线都成立（工程态、返修、交付核验）。

`montage` / `frame` 的用例必须在 `must_do` 里落到该路线的真实入口（`montage.py`、
`scan_materials`、`素材清单`、`镜头表` / `frame.py`、画框、token），否则 `route` 只是标签。
老用例没有 `route` 时 runner 会按文本推断并给 WARN；新用例必须显式写。

## 覆盖矩阵

runner 每次打印两页矩阵，并按下限判失败：

- **路线**：`recompose` / `montage` / `frame` / `shared` 各至少 1 条；
- **话题**：`素材清单`、`镜头表/plan`、`画框/预览落位`、`返修闭环`、`终态分级`
  各至少命中 1 条用例。

这条下限针对的是 2026-11 之前的真实故障：七条用例全部停在 recompose 时代，
`montage` / `frame` / `素材清单` / `返修` 零命中，而全仓没有任何脚本会发现"用例已经死了"。
新增路线或新接缝时，先加用例，再改下限。

## 加一条用例

1. 一条用例只压一个判断，`prompt` 写成作者真的会说的话（带上下文与约束，不要写成考卷）；
2. `must_do` / `must_not_do` 写成**可观察的动作**：跑到哪个命令、写了哪个字段、停在哪一步；
   不写"注意质量""合理取舍"这类无法判定的要求；
3. 写清终点是审阅页还是交付件——`edit/_engineering/` 是审阅素材，`成品/` 才是交付件；
4. 跑 `python3 evals/run_evals.py`，确认路线与话题矩阵都还满足下限。

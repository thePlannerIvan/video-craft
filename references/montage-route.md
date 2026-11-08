# 蒙太奇路线：现成素材 + 口播

> 什么时候读：**片型 = montage**（画面是现成的档案影像 / 实拍 / 照片，不是画出来的页）。
> 画面是生成出来的（PPT 页、图形、字卡、动效）走 [recompose-mode.md](recompose-mode.md)，不读本页。
> 版式/画框（竖屏上下留白、字幕安全区、人物位）见 [frame-spec.md](frame-spec.md)。

## 这条路线解决什么

口播已经录完、没有参考页、画面来自一批真实素材。它和 recompose 的区别是**画面不是造出来的，
是选出来的**：难点不在"这一屏怎么演"，而在"哪段素材、从第几秒开始、和这句话对不对得上"。
2026-11 的哈雷片（67 镜 / 4:28 / 1080×1920）是这条路线的第一个实例。

三个动作，顺序不能换：**素材清单 → 镜头表 → 渲染 + 体检**。
跳过清单直接排镜头，等于凭文件名猜素材：那次 54 个镜头里 18 个渲成了空画面。

## 1. 素材清单

```bash
python3 "<craft>/helpers/scan_materials.py" "<project>/material/clips"
```

产出 `material-inventory.md`（清单骨架）+ `_sheets/sheet-*.jpg`（帧带：一行一个文件，帧上标时间码）。
模型照着帧带把三列填完：**可用段落 / 画面一句话 / 水印台标**，出处记 URL。

判据的权威版本在 [media-sourcing.md](media-sourcing.md)（水印分级、时代与画质、出处与授权、失败处理）。
本节只留三条摘要：可用段落要写成「几秒到几秒是同一内容」；整屏水印/台标/烧录字幕/时间码不可用，
小角标登记后可用；写不出一句话画面的素材不要进镜头表。

**完成标准**：每条候选素材都有一行登记，且「不可用」的写了原因。素材清单只增不删，
第二版发现看错了就改那一行，不要新建第二份清单。

## 2. 镜头表

镜头表是**人读**的 JSON，一镜一条，字段只有七个。三个时间坐标（源片时间 / 素材入点 / 剪后时间）
的定义与换算在 [visual-timeline.md](visual-timeline.md) 的「三个时间坐标」一节——**镜头表只填「段 + 词」，
其它时间由 `plan` 算**：

```json
{"range": 2, "word": 30, "kind": "clip",
 "material": "material/clips/g2_wwii/N2.mp4", "in": 89.0,
 "grade": "vintage", "note": "1969 飞车党车队在荒漠公路"}
```

| 字段 | 含义 | 容易搞错的地方 |
|---|---|---|
| `range` | 第几段（对应 `edit/edl.json` 的 ranges 序号） | 是段号不是镜头号 |
| `word` | 这一镜从**本段第几个词**开始 | 0 起算；决定剪点落在哪个气口 |
| `material` / `in` | 素材路径 + **素材内的秒数** | `in` 不是 EDL 源时间（见 GOTCHAS #80） |
| `kind` | `clip` / `photo` | 照片走慢推；clip 必须有 `in` |
| `grade` | 调色档名（`grades` 里定义） | 同一句话的相邻镜头别换调色档 |
| `note` | 这一镜在讲什么 | 体检和复盘都靠它 |

```bash
python3 "<craft>/helpers/montage.py" plan "<project>" --shots "<镜头表.json>"
```

`plan` 做的事：用词级时间把「段 + 起始词」展开成绝对时间（起步落在前一词与本词的停顿中点）、
把花字的词锚换算成**剪后时间**并钳进所在镜头、校验素材存在/入点不越界/素材不重复/时长合计
等于时间轴。任何一条不过就退 1 并指出是第几镜——**不要绕过它手写 montage-plan.json**。

`plan` 的产出 `edit/montage-plan.json` 是渲染的唯一输入：渲染只认绝对时间，不再做换算。

**完成标准**：`plan` 退 0；镜头表里每一镜的 `note` 都能在口播里找到对应的那半句。

## 3. 渲染

```bash
python3 "<craft>/helpers/montage.py" render "<project>" --max 20        # 分块跑，可重复
python3 "<craft>/helpers/montage.py" render "<project>" --concat        # 全渲完后拼接+混音
```

- 每镜一个中间文件，已存在的跳过；`--force` 重渲。**分块跑**：一次 20–40 镜，
  长任务别堆在一个前台命令里。
- 中间文件默认落 `/tmp/montage_<hash>/`，成片再搬进项目目录——云同步目录不能长写（GOTCHAS #52）。
- 花字已经烘进它所在的那个镜头（一条花字一次 overlay），不需要单独的花字层。
- `--only 1,6,20` 只渲指定镜头，用来先对几个关键画面。

**完成标准**：`render` 打印的镜头数和计划一致；没有「素材不存在 / 入点越界」的报错。

## 4. 体检（这一步不能省）

```bash
python3 "<craft>/helpers/check_montage.py" "<project>" \
    --shots-dir /tmp/montage_<hash> --base "<project>/material/frame/base.png"
python3 "<craft>/helpers/check_montage.py" "<project>" --video "<成片>"
```

- **逐镜**：文件齐、时长对、不是黑帧、不是「只有底图」。给了 `--base` 时直接比底图；
  没给底图时用「不同素材的镜头统计值一模一样」当空镜指纹。
- **成片**：抽样亮度，报出成段黑帧的时间范围（拼接丢段、编码段为空都会在这里露出来）。
- `--json` 给机器读，人看默认输出即可；`RESULT: OK` 才算过。

**完成标准**：`check_montage` 退 0。它不通过时不要交付，也不要用「我看过没问题」代替——
那次 18 个空镜的退出码全是 0。

## 5. 交付

输出三件套：画面成片（`montage.py render --concat --audio` 的产物）、口播成片（母版按同一 EDL 剪的
竖屏人物轨 + 口播音轨）、外挂 `edit/subtitles.srt`。三件的规格、命名、核验与边界都在
[delivery.md](delivery.md) 的「蒙太奇项目的三件套」一节，字幕链见 [caption-article-first.md](caption-article-first.md)。

审阅：成片态审阅面看画面与声音，`check_review_playable.py` 通过才算能看；见 [review-ui.md](review-ui.md)。

## 常见失败与去处

| 现象 | 原因 | 去哪 |
|---|---|---|
| 某些镜头只有底图 | 渲染用了 EDL 源时间当素材入点 | GOTCHAS #80；`plan` 会先拒 |
| 花字整体错位几十秒 | 词锚的源时间当成剪后时间 | 花字一律写「段 + 词」，由 `plan` 换算 |
| 花字只闪一下或跨镜 | 词锚贴着镜头尾巴 | `plan` 会推到下一镜开头并钳住停留 |
| 成片某段全黑 | 拼接缺镜 / 某镜编码为空 | `check_montage --video` 报时间范围 |
| 素材重复出现 | 同素材换了入点但相隔太近 | `plan` 按入点距离判重（默认 5 秒） |
| 素材带水印 | 清单没标水印 | 回第 1 步补清单，不靠肉眼在成片里找 |

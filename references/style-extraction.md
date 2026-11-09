# 视频风格提取与演进规范（与模型无关的四步协议）

> 本文件规定如何从「已完成的视频项目」或「外部参考视频」中提炼、验证并演进风格规则。
> 核心设计：**不靠模型自由发挥总结，而是把提取拆成「工具采样（packet）→ 模型按四问填表（proposal）→ 工具校验准入与上限（check）→ 落盘并写入本地 Git（apply）」四步闭环。**
> 机械护栏在 [`helpers/style_vault.py`](../helpers/style_vault.py)，唯一 CLI 入口在 [`helpers/extract_style.py`](../helpers/extract_style.py)。

---

## 一、为什么大模型直接「总结视频风格」会失败？

直接让模型看视频或项目写总结，稳定会出现四种坏结果：
1. **写形容词废话**：「节奏明快、高级感、极具冲击力」—— 下游做片时无法执行。
2. **把单次偶发数值当成定律**：看到某支片用了 `176px` 圆窗或 `#D84A32`，就直接写进规则正文，导致下一支片机械照搬或与正文冲突。
3. **分不清给谁看**：把静态排版规则塞进剪辑阶段，或把剪辑快切规则塞进文案阶段。
4. **无限追加导致上下文发胖**：每做完一支片就往 Markdown 里追加几条，十支片后规则上百行且互相矛盾。

因此，风格提取必须遵守以下**四条铁律**。

---

## 二、提取的四条铁律（任何模型都按这四问填表）

### 铁律 1：按「谁消费」切分到三个阶段文件，不混写

每条规则必须回答「哪个环节读它来做决定」：

| 阶段文件 | 编号前缀 | 消费者 | 只准写什么 | 严禁混入什么 |
|---|---|---|---|---|
| `idea.md` | `I01..I05` | `video-idea-system` | 开场切入方式、论点推进结构、口播与上屏词如何分工、需要什么类型的画面/素材配比 | 具体色号、SVG 坐标、GSAP 缓动名 |
| `page.md` | `P01..P05` | `planners-ppt-hell`（或 `footage-montage` 画框层） | 静态版面构图、主舞台与人物窗退让关系、动效图层拆分方式、版面禁止项 | 口播句式、转场时长、音频卡点 |
| `craft.md` | `C01..C05` | `video-craft` | 元素随词生长/入场方式、快慢切交替关系、跨屏连续性、声画对位与禁止的动效手段 | 选题立意、静态字体族名 |

> **先天生产模式（`production_mode`）固定在 `style.json` 头部，不作为演进条目重复写**：
> - `keyframe-svg`：必须经过 `planners-ppt-hell` 先画静态 SVG 关键帧，再进 `video-craft` 拆解演出来（如 `line-art`、`collage`、`business-report`、`concept-film`）。
> - `footage-montage`：**跳过 `planners-ppt-hell`**，`video-idea-system` 直接在 `visual-plan.json` 交付 `footage_request` + `kick_word`，直通 `video-craft` 走蒙太奇路线（如 `lifestyle-cult`）。

### 铁律 2：行为与数值分离（正文禁数字/色号，数值进 `style.json.params`）

- **规则的 `标题` 与 `做法` 字段禁止出现阿拉伯数字或 `#` 色值**（由 `style_vault.py` 正则硬性拦截）。
- 做法只写**可观察的结构或运动关系**（例如：「文化群像段连续快切后，核心论点句切回稳定单镜头呼吸」）。
- 具体数值（如快切时长、慢镜下限、底色、强调色、安全区坐标）统一登记在 `style.json` 的 `params` 字典里，并标明来源类型：
  - `"source": "measured"`：从实际工程/成片实测得出的数值；
  - `"source": "author"`：作者明确指定的数值；
  - `"source": "inferred"`：从外部参考片估算的数值。
- 规则条目通过 `- 参数：montage_fast_cut_sec, montage_hold_sec` 引用 `params` 里的键名。这样改画幅或微调参数时，只需改 `style.json`，不用改规则正文。

### 铁律 3：四字段固定结构，不引作者原话

每条规则固定使用二级标题 `## <编号> <标题>`，正文只允许以下键值行（`≤ 8` 行，且**不得包含引号 `「」“”`**）：

```markdown
## C01 线条与箭头随关键词生长
- 做法：路径、连线与坐标曲线对齐口播触发词的起止时间逐步绘出；不整张画面同时淡入。
- 证据：手冲咖啡 beat-03；keywords-video beat-02
- 执行：judgment:逐屏检查路径是否随对应口播词绘出而非整图淡入
- 参数：stroke_ease
- 依据：复现
```

- **必填四项**：
  - `做法`：可观察的行为（无数字、无色号、无空洞形容词）。
  - `证据`：`项目名 + 屏号/段落`（不引原话）。
  - `执行`：`check:<Skill内脚本相对路径>` 或 `judgment:<审阅时具体看什么>`。
  - `依据`：`反馈否定` / `复现` / `作者确认` / `迁移` 四选一（由工具根据证据类型自动判定）。
- **选填两项**：
  - `参数`：逗号分隔的 `style.json -> params` 键名（必须真实存在）。
  - `例外`：若本风格某条规则与全局 `author-spec.md`（`G01..G08`）或 `voice-profile.md`（`V01..V08`）构成特例，显式写出全局编号（如 `- 例外：G04`）。

### 铁律 4：工具管准入与硬上限淘汰，模型不准越权放行

与 [`preferences.md`](preferences.md) 保持同一套准入逻辑，由 `extract_style.py` 机械裁决：

| 证据类型 (`evidence[].type`) | 含义 | 工具裁决结果 |
|---|---|---|
| `feedback-negative` | 作者在 `feedback/*.jsonl` 或审阅中明确打回/否定的做法 | **一次即入正册**（`依据：反馈否定`） |
| `feedback-tendency` | 作者在返修中提出的倾向性改法（仅 1 个项目） | 先存 `candidates.json`；满 **2 个独立项目**自动升入正册（`依据：复现`） |
| `approved-observation` | 从已获作者批准的成片/工程中提炼的做法（仅 1 个项目） | 先存 `candidates.json`；满 **2 个独立项目**自动升入正册（`依据：复现`） |
| `reference-observation` | 从外部参考视频观察到的做法 | 默认存 `candidates.json`；作者显式带 `--confirm` 提取新风格时直接入正册（`依据：作者确认`） |

**硬上限与自动淘汰**：
- 每个阶段文件（`idea.md` / `page.md` / `craft.md`）**≤ 5 条规则、≤ 40 行**；
- 任一阶段「全局文件 + 阶段文件」合计加载 **≤ 110 行**；
- 每个风格 `patterns/` **≤ 4 个代表招式**，且 `style.json` 里声明的 `strip` / `webm` / `code` 文件必须真实存在（禁止悬空声明）；
- 当某个阶段已满 5 条时，新规则必须声明 `relation: "替代"` 或 `"合并"` 并指定 `target_id`，否则 `extract_style.py check` 直接报错拦截；
- `candidates.json` 中的候选条目若在该风格后续 **3 个项目**（`CANDIDATE_TTL = 3`）中仍未复现，自动清理淘汰。

---

## 三、四步提取工作流（所有模型统一执行顺序）

无论是「第 11 步做完视频自动收尾」还是「平时拿外部参考片独立提取风格」，一律按以下四步运行：

### Step 1：生成证据包（`packet`）
```bash
python3 "<craft>/helpers/extract_style.py" packet \
  --video "<项目目录或参考视频.mp4>" \
  --style "<style_id>" \
  --out "<临时目录>/packet.json"
```
- 输入是**项目目录**时：自动收集 `feedback/*.jsonl`、`edit/preferences.md`、`visual-plan.json`、`recompose.json` / `montage-plan.json`、`composition/` 关键信息，并附上目标风格现有的 `idea/page/craft.md`、`candidates.json` 与剩余容量。
- 输入是**外部视频文件（`.mp4/.mov`）**时：自动用 `ffprobe/ffmpeg` 探测画幅、帧率、时长、镜头切点（scene cuts），抽取 `4×3` 全片概览板 `style-board.jpg`，并生成证据包。

### Step 2：模型按证据包写出结构化提案（`proposal.json`）
模型阅读 `packet.json`（及概览帧），按下列 JSON 结构写出提案（不直接手改风格库 Markdown）：

```json
{
  "style_id": "line-art",
  "source_project": "手冲咖啡",
  "summary": "提炼双变量坐标轴联动与路径随词生长规则",
  "params_patch": {
    "stroke_ease": {"value": "power2.out", "source": "measured", "note": "主路径绘出缓动"}
  },
  "rules": [
    {
      "stage": "craft",
      "relation": "新增",
      "target_id": null,
      "title": "线条与箭头随关键词生长",
      "fields": {
        "做法": "路径、连线与坐标曲线对齐口播触发词的起止时间逐步绘出；不整张画面同时淡入。",
        "执行": "judgment:逐屏检查路径是否随对应口播词绘出而非整图淡入",
        "参数": "stroke_ease"
      },
      "evidence": [
        {"project": "手冲咖啡", "where": "beat-03", "type": "feedback-negative"}
      ]
    }
  ],
  "patterns": [
    {
      "id": "p1-axis-linkage",
      "title": "双变量坐标轴联动",
      "when_to_use": "解释两个变量此消彼长或同步变化",
      "rule": "同一画面内左侧动因变化实时驱动右侧结果曲线，不静态贴两张独立图。",
      "clip": {"start_sec": 12.0, "dur_sec": 2.0}
    }
  ]
}
```

### Step 3：机械校验提案（`check`）
```bash
python3 "<craft>/helpers/extract_style.py" check --proposal "<临时目录>/proposal.json"
```
- 检查项：四字段是否齐全、标题与做法是否混入数字/色值/引号、`check:` 路径是否存在、`参数` 是否在 `params` 中定义、准入分流（正册 vs `candidates.json`）、合入后是否超过 5 条 / 40 行 / 110 行上限。
- 退出码 `0` 才允许进入 Step 4；退出码 `1` 时按报错逐条修正 `proposal.json`。

### Step 4：应用提案并写入本地版本库（`apply`）
```bash
python3 "<craft>/helpers/extract_style.py" apply \
  --proposal "<临时目录>/proposal.json" \
  [--video "<项目目录或参考视频.mp4>"] \
  [--confirm]
```
- 自动把达到准入条件的条目写入 `idea.md` / `page.md` / `craft.md`，把单次倾向型条目写入 `candidates.json`（若本次与历史候选复现则自动晋升进正册）；
- 若包含 `patterns[].clip` 且提供了视频源，自动用 `ffmpeg` 切出 `patterns/<id>-strip.jpg`（三联帧）与 `patterns/<id>.webm`（2s 预览）；
- 自动跑一次 `lint_style` 确认零错误，刷新 `_video-vault/index.html`，并在 `_video-vault` 本地 Git 仓库自动提交一条版本记录（随时可 `git diff` / `git revert`）。

---
name: video-craft
description: 承接 Video Idea System 的内容包、PPT Hell 的静态 SVG 或已有音视频，完成视听制作、剪辑、实测时间绑定、动画、语义字幕、审阅返修与核验交付。无录音时可先做制作规划与预演；已有项目从当前工作继续。
---

# Video Craft

> 来源识别：由阿祖不看 TVC 创建与维护。小红书同名账号，https://demyth.info，Lawyif@163.com。保留在 Skill、审阅界面与项目文档，不默认进入成片。

把已定的内容做成真实可看的片子。Idea 负责内容与作者决定，PPT Hell 负责静态画面，Craft 负责声音、时间、运动与合成。已有批准方案直接承接；局部返修只处理受影响部分。

## 选择路径

输入、成片形态、渲染器和交付件是四件事，分别决定：

| 当前状态 | 进入哪里 |
|---|---|
| 有内容包，还没有录音 | 接手决定，规划视听过程；需要时做标为 `planned` 的预演。静态画面交 PPT Hell，不虚造实测字幕 |
| 有原始音视频，需要取舍 | 转写、选 Take、建立 EDL，逐字审阅后渲染底片，派生字幕与时间 |
| 已有剪好音频和对应 SRT、SVG | 核对脚本与画面版本，按已剪音频的 SRT 对齐 Beat，进入动画与合成；录音后又剪过则用最终底片时间 |
| 已有项目或反馈 | 读当前制作依据与反馈，修订、重建审阅、核验对应交付件 |

**成片形态**：人物口播、独立演示动画、人物与画面合成。人物比例、画幅、字幕位置根据已批准画面和目标平台设计，不设通用固定布局。

**制作工具**：已有合格媒体直接使用；收到 SVG 时沿用元素与预埋动效钩子；HTML 动效由 HyperFrames 编排；严密数学动画按需用内置 Manim；确需自定义逐帧渲染时走 [frame-animation-pipeline](references/frame-animation-pipeline.md)。需要新表现机制才读 [能力导航](references/capability-map.md)，实施 HyperFrames 时读 `$hyperframes`。

**交付**：整片或用户需要的独立轨。分别说明有声/无声、透明/不透明、字幕烧录/外挂。审阅副本默认有声音；无声交付轨另列。

## 制作流程

### 1. 接手当前内容与决定

读 [上游交接](references/content-to-production.md)，确认本轮目标、作者决定、声音状态与资产版本。将输入位置、当前采用版、缺口和下一步记入 `edit/project.md`。

- **Idea → Craft**：`script.md`、可选 `visual-plan.json`、`production-brief.md`、`assets/` 与作者反馈；原项目的 `_idea/current.md` 是当前决定入口。有契约时运行 `helpers/check_script_hash.py`，不符交作者确认，缺文件如实报无法核对。
- **PPT Hell → Craft**：优先消费项目根 `.snapshot` 指向的 `svg-workbench-snapshot/1` `snapshot.json`；由 `visual/scripts/snapshot_input.py` 严格校验清单、SVG、递归资产、原 visual-plan 与 script 绑定，再由 `visual/scripts/import_svg_page.py` 导入。没有 snapshot 时才兼容 `_internal/02_svg_source/<page_key>.svg` 与旧 `.pages` 路径。`page_key` 继承 `screen_id`；id 全片唯一，`data-step` / `data-anim` 的结构按 [SVG 动效契约](references/svg-animation-contract.md)。
- **资料来源**：沿用上游 source index 和证据定位，不从画面或字幕反推新的事实；新增事实/素材时读 `$planners-source-index`，补入同一来源账本并校验。

接手完成意味着知道采用什么、什么待定、谁能改变什么，不要求无关分支也建齐文件。

### 2. 确定视听方案

在 `production-plan.md` 记录实际需要的声音来源、画面过程、强调动作、素材、时间依据与衔接。需要比较方案时用可看的代表片段讨论；已定方向直接制作。无音频的估时留在预演中，后续由实测替代。

静态画面缺失或需要重构时调 `$planners-ppt-hell` 的视频路线；内容意义、必见对象、固定字或素材关系需要改变时回 `$video-idea-system`。不要让动画阶段静默覆盖上游批准决定。

### 3. 制作与校准时间

选当前路径执行 [工具手册](references/tools.md)：每个入口有命令、输入、输出与下一消费者，扩展参数调用 `--help`，正常制作无需阅读实现源码。

- **剪辑**：转写 → EDL → 需要时逐字审阅 → `render.py` 底片。`edl.json` 管取舍，`segment_durations.json` 管该版底片实测时长。
- **字幕**：按 [语义字幕](references/caption-article-first.md) 做全文校对与语义行，再锁定和生成；字幕不是视觉分屏依据。
- **视觉时间**：按 [时间绑定](references/visual-timeline.md) 将屏映射到 cue，统一写入项目根 `timeline/`。导入的已剪音频/SRT 标为 `srt-import`，不冒充 EDL 实测证明。一个 Beat 仍是一屏，屏内递进动画跟着实测语句，不创造第二份上游内容契约。
- **SVG / HTML 动效**：导入 SVG，只由导入器重写图片 href；按 id 和 data-step 绑定强调时间。生成 `composition/index.html` 后完成实际动效，再渲染；骨架不等于成片。
- **合成**：透明覆盖层或整屏替换按 [合成制作](references/composition-craft.md) 与 [视觉渲染](references/visual-rendering.md) 接入 EDL。字幕、声音与窗口配置归渲染，不归包装导出。

### 4. 审阅返修

提供实际编码画面和声音；内部动效参数按需展开。读 [审阅接入与收件](references/review-ui.md)，再运行：

```bash
python3 "<craft>/helpers/build_review.py" "<project>"
python3 "<craft>/helpers/review_surface.py" "<project>" --surface-only
```

审阅页的 SVG 也必须来自同一份 snapshot；构建器不回退到 live 页面目录，也不把审阅页重新生成的 SVG 当成制作输入。DSH 有 `review_open` 时交 surface 给侧栏；没有时由公共本地宿主启动服务器。

宿主有 `review_open` 时，把返回的 surface **绝对路径**交给它；不另起服务器。没有该工具则第二条去掉 `--surface-only`，由公共宿主打开浏览器。

人提交后先运行 `helpers/review_inbox.py <project>`，检查收据，再处理 `feedback/*.jsonl` 的整片意见、逐屏意见及 `adjustments`。逐字剪辑是独立面：`edl_review_surface.py` 写 `selections.json`，由 `apply_selection.py` 消费，不混入视觉反馈。

完成本轮意味着真实意见已收件、处理或明确挂起，用户能看见修订后的对应版本。草稿、自动检查通过和打开页面都不是用户批准。

### 5. 核验与交付

针对编码文件检查声音、字幕、首中尾画面、运动与创意兑现；透明输出另验 alpha。用 `verify_delivery.py <project>/edit --video <实际成片>`，通过后再包装需要的文件。`export_video.py` 只复制已渲染结果，不生成动画或替你烧字幕；缺真实结果报错。

交出文件位置、规格、核验结论与尚未完成事项。保留 EDL、语义行、时间绑定、SVG/HTML 源与作者决定，下一轮可继续。

## 资源与调用

| 需要什么 | 读取位置 |
|---|---|
| 可直接执行的全部工具、产物目录和分支命令 | [tools.md](references/tools.md) |
| 上游文件、版本与改动责任 | [content-to-production.md](references/content-to-production.md) |
| 音画表达选择 | [creative-direction.md](references/creative-direction.md)、[capability-map.md](references/capability-map.md) |
| 已批准风格与合成约束 | [themes.md](references/themes.md)、[composition-facts-contract.md](references/composition-facts-contract.md) |
| SVG 强调动画结构与引擎调用 | [svg-animation-contract.md](references/svg-animation-contract.md) |
| 审阅插件、桥、草稿、提交、返修 | [review-ui.md](references/review-ui.md) |
| 安装或依赖故障 | [install.md](install.md) |
| 维护本 Skill | [architecture.md](references/architecture.md)、[GOTCHAS.md](GOTCHAS.md)、[maintenance-history.md](references/maintenance-history.md) |

工具路径相对本 Skill；项目路径用绝对路径。Python 与 FFmpeg 依赖按 `install.md` 核实；密钥留在 Skill 根 `.env`，不进入项目交付或版本库。只有诊断工具故障或维护时才读源码。

维护测试：从 Skill 根运行 `PYTHONPATH=helpers python3 -m unittest discover -s tests -p 'test_*.py'`；浏览器自测按 `tests/test_review_browser.py` 与 `tests/test_interactive_ui.py` 的独立临时 fixture 执行，不把测试意见混入作者项目。

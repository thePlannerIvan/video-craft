# Video Craft

编辑视频的单一 skill：**剪辑、画面、花字、字幕、交付**，一条流程走完。

它存在的原因是：剪辑和画面原本是两个 skill，只有靠人手工搬数据才能配合起来——
而那段"手工搬数据"里最容易出错的覆盖层合成，没有任何一个 skill 拥有。

## 它能做的四件事，其实是同一件事

| 你要的 | 底片 | 视觉层 |
|---|---|---|
| 做画面，把口播压上去 | 空 | 不透明，满屏 |
| 做花字，压在口播上 | 口播剪辑 | alpha 覆盖层 |
| 纯剪辑 | 素材 | 无 |
| 纯动画 | 空 | 不透明 + 自带音频 |

没有素材时（画面 + 口播）在 EDL 里声明 `canvas` + `fps`，`render.py` 合成黑底承载口播；
满屏不透明覆盖层走 `-c:v copy`，画面不多编码一代。

四种都是 `时间脊柱 → 视觉层 → 一个合成器`。

## 使用与维护

默认先交工程态审阅；作者明确出片后再合成与核验。逐字剪辑和动效审阅是两种制作界面，均使用公共审阅宿主。

- [SKILL.md](SKILL.md)：按输入和本轮目标选阶段。
- [阶段契约](references/stages.md)：11 步的输入、完成条件与返回路径。
- [工具手册](references/tools.md)：现有入口与调试命令。
- [架构与 Debug](references/architecture.md)：职责、失效范围、局部优化和验证。
- [实现 Brief](references/implementation-brief.md)：B1–B8 的实现范围、兼容方式与实际验收记录。

EDL 时间与外部 SRT 来源分别登记；工程态 projected 不冒充实测。新视觉制作固定走 recompose，先拆批准原页，再手写 composition；旧 page 路线隔离恢复。

## 为什么覆盖层要单独有校验器

覆盖层是唯一一处"做错了不会失败，只会产出一个看起来合理的错视频"的接缝。
2026-09-15 的真实事故：花字按某个文档的说法渲成 WebM，而本机 ffmpeg 的 libvpx
没编 alpha，WebM 静默丢了透明；合成器照叠不误，渲染六分钟之后底片全黑。
正确做法早就写在另一个 skill 的文档里 —— 两个 skill 各自记住了一半。

现在 `check_overlay.py` 把这条接口变成机器可证的：alpha 平面真的存在吗、
alpha 是不是被烘成了不透明、帧率对得上底片吗、时长等于声明的窗口吗。
`render.py` 在合成前会再验一次——坏层一秒失败，而不是渲染六分钟才发现。

## 安装

从 GitHub 装：

```bash
npx skills add https://github.com/thePlannerIvan/video-craft --skill video-craft
```

## 公共模组（缺了会自动装）

同族**公共模组**（独立发布的条目，不是本仓库的一部分）。**本 Skill 只解析 `planners-review-core`**（见 `helpers/lib/planners_modules.py --check`），其余三个是同一族的邻居、本 Skill 不需要：

- [`planners-review-core`](https://github.com/thePlannerIvan/planners-review-core) —— 审阅面契约、桥与本地宿主 ← **本 Skill 用到**
- [`planners-source-index`](https://github.com/thePlannerIvan/planners-source-index) —— 来源索引契约与唯一校验器（本 Skill 不消费）
- [`planners-fact-check`](https://github.com/thePlannerIvan/planners-fact-check) —— 事实核查契约与校验器（本 Skill 不消费）
- [`planners-report-kit`](https://github.com/thePlannerIvan/planners-report-kit) —— 报告装配与校验（仅带报告出口的 Skill 需要；本 Skill 无报告出口）

某个模组不在本地时，本 Skill 的适配器会**自动从 GitHub 装它**，不需要手动准备。适配器找的地方按顺序：

1. `$PLANNERS_MODULES_HOME/<模组名>`
2. 本 Skill 的兄弟目录 `<skills-root>/<模组名>`（发布后的主路径）
3. monorepo 里 `02-skills-library/<分类>/<模组名>`
4. **用户级安装根**：`$PLANNERS_MODULES_INSTALL_DIR` → `$PLANNERS_MODULES_HOME`（仅当它已含该模组，或那目录还不存在）→ 默认 `~/.planners-modules/<模组名>`

前三条都没有时才自动安装（顺序不变，**本地永远优先、不会无条件联网**）；装到第 4 条那个**库外**用户级目录，**绝不写进** `02-skills-library` 工作树、`~/.codex|~/.claude|~/.gemini` 的技能目录、或任何系统目录。安装过程**不静默**：会打印缺哪个、找过哪些路径、从哪个 URL 装、装到哪、用的是 `git clone --depth 1` 还是 `npx skills add`、以及装到的 **commit**。装完先在暂存目录里验证（`SKILL.md` + 该模组声明的契约/校验器锚点文件都在），再用 rename 原子就位；**任何失败都会清掉暂存、不留半成品**，并给出可复制的手动安装命令。

要它**只报不装**（CI／离线／审计）：

```bash
PLANNERS_NO_AUTO_INSTALL=1 <你的命令>
```

| 环境变量 | 作用 |
|---|---|
| `PLANNERS_MODULES_HOME` | 指定已有模组所在目录（解析第 1 条，也兼作安装根） |
| `PLANNERS_MODULES_INSTALL_DIR` | 只指定**自动安装**的落点（优先级高于上面那条） |
| `PLANNERS_MODULES_REF` | 要钉的 tag 或分支（不设 = 装默认分支 HEAD） |
| `PLANNERS_NO_AUTO_INSTALL=1` | 只报不装；缺依赖时如实失败并打印手动命令 |

装的是**默认分支 HEAD**，日志里**永远打 commit**；HEAD 恰好被某个 tag 指着时，tag 也一并打出来。想钉版本就设 `PLANNERS_MODULES_REF`：

```bash
PLANNERS_MODULES_REF=v1.0.0 <你的命令>     # 钉在 tag 上
PLANNERS_MODULES_REF=main   <你的命令>     # 钉在某个分支上
```

钉了不存在的 ref 会**如实失败**（不会悄悄退回 HEAD），错误里带正确的可复制命令。

### 两条命令别搞混：谁装 Skill，谁抓依赖

**用户装一个 Skill** —— 用 Skills CLI，它会把条目放进各 agent 的技能目录：

```bash
npx skills add https://github.com/thePlannerIvan/video-craft --skill video-craft
```

**Skill 自己抓一个公共模组（内部依赖）** —— 用 `git clone`，落在库外的单一安装根：

```bash
git clone --depth 1 https://github.com/thePlannerIvan/<模组名>.git \
  "$HOME/.planners-modules/<模组名>"
# 想钉版本：加 --branch v1.0.0
```

**内部依赖为什么不走 `npx skills add`**：它没有 `--dir` 之类的落点参数，只会写进 `~/.claude/skills`、`~/.codex/skills` 这类 **runtime 技能目录**（那是发布器的领地，写进去等于多一份漂移副本）；而且它下载的目录**不带 `.git`**，拿不到 commit、也就没法追溯装的是哪一版。**门面命令归用户，内部依赖归 clone** —— 上面自动安装走的就是这条。


或克隆到 skills 目录：

```bash
git clone https://github.com/thePlannerIvan/video-craft.git ~/.claude/skills/video-craft
```

在 monorepo 中开发时，runtime 同步使用仓库发布器：

```bash
cd 02-skills-library
python3 publish_skills.py --dry-run
python3 publish_skills.py --target all
```

发布器是 runtime 同步的唯一入口；不要手动复制或链接 Codex、Claude Code、Antigravity 目录。先按测试与发布规则验收，再从 `02-skills-library` 发布。

Python 用 `02-skills-library/.venv/bin/python`（3.9.6，`pptx` / `lxml` / `PIL` /
`playwright` / `numpy` 齐，本类别共用，离线可用）；系统 `python3` 同样能跑测试套件。
需要单独装依赖时用 `pip install -e .`，清单见 `pyproject.toml`。

密钥放本 skill 的 `.env`（**不要**放进用户的视频目录）：

```
ELEVENLABS_API_KEY=...
ARK_API_KEY=...
DOUBAO_APP_ID=...
DOUBAO_ACCESS_TOKEN=...
```

详见 `install.md`；日常用法见 `SKILL.md`。

## 测试

```bash
cd tests
# CATEGORY_PY is the interpreter the whole category shares — set in install.md step 1.
PYTHONPATH=..:../helpers PATH=/opt/homebrew/bin:$PATH \
  "${CATEGORY_PY:?set CATEGORY_PY to the shared category python (see install.md)}" \
  -m unittest discover -s . -p "test_*.py"
```

`PATH` 那一段是必须的：`check_overlay` 的 16 条要真起 `ffmpeg` 造文件。

公共模组自动安装器自己的不变量测试（安装根优先级、禁地断言、候选顺序、幂等、失败清理、只报不装）：

```bash
cd helpers/lib
python3 planners_modules_install_test.py
```


覆盖：剪辑契约、SRT/时间来源与时间轴、帧率解析、人像探测、覆盖层契约及坏覆盖层拒绝、
视觉审阅的实际播放/反馈/收件、上屏文字闸门、`script_hash` 比对、抽段完整性、
按 EDL 哈希选取渲染记录、交付与二次剪映射、HyperFrames 环境预检。
SVG page 导入用例只保护旧项目兼容，不代表它是新项目路线；旧 page 流程见归档说明。

单独跑某一项，例如：

```bash
cd tests
PYTHONPATH=..:../helpers "${CATEGORY_PY:?set CATEGORY_PY as described in install.md}" -m unittest test_time_source test_svg_page_import -v
```

## 血统

由 `video-use`（时间脊柱 / 合成器 / 字幕链 / 交付校验）与
`web-video-presentation`（视觉层创作面 / alpha 编码 / 视觉审阅环）合并而来，
**已于 2026-09-15 与两个上游脱钩**。吸收了什么、故意偏离了什么，见
`upstream-diff.md`。两个旧 skill 整份留在 `archive/` 里。

上游 `browser-use/video-use` 是 MIT 许可（Copyright (c) 2026 Browser Use），
原文保留在 `archive/video-use/LICENSE`；归属与血统详见 `NOTICE`。

## 适合 / 不适合

**适合**

- 已有素材或录音，要**走完剪辑到交付**：剪接决策、实测时间轴、语义字幕、覆盖层、合成、核验。
- 已有口播稿和画面要求，要把画面/花字**压在口播上**，且不想多编码一代。
- 要做**纯动画**或**画面为主**的片子，自带音频。
- 需要**在渲染前**就挡住坏覆盖层（alpha 被烘成不透明、帧率对不上、时长不等于声明窗口）—— 而不是渲完六分钟才发现。
- 需要在交付前对**成片文件本身**做核验，而不是只看中间产物。

**不适合**

- **只要创意、选题、口播稿** —— 用 `video-idea-system`，本 Skill 正是接它的产物。
- **只做静态画面 / 可编辑 PPT** —— 用 `planners-ppt-hell` 的视频画面路线或幻灯片路线。
- 想要**一键自动剪辑**、不做任何取舍确认 —— 剪接审阅是流程的一部分，不是可跳过的装饰。
- 本机没有 `ffmpeg` / `ffprobe` —— 覆盖层校验与渲染会直接拒绝（这是有意的设计，不是缺陷）。

## 品牌与署名边界

本项目开源，但**项目名与作者身份不等于开源授权**。你可以 fork、修改、商用（AGPL-3.0 允许商业使用），但修改版必须**换名或明确标注是 fork**，不能暗示作者为你背书。完整边界见 `TRADEMARK.md`。

出处识别可以出现在仓库文档、流程 HTML、审阅页与验证页里，**但默认不写进最终客户交付物**：不成片、不导出 PNG、不进最终 PPT —— 除非用户明确要求。

## 开源协议和商业入口

以 **AGPL-3.0** 开源 —— 允许商业使用；保护的是**修改版与网络服务也要公开对应源码**，不保护项目名与作者身份。品牌边界靠 `TRADEMARK.md`。

需要私有部署、风格/主题库适配、定制交付质检、闭源商业授权或内部培训，见 `COMMERCIAL.md`。

由阿祖不看 TVC 创建与维护 · https://demyth.info · Lawyif@163.com。授权和归属详见 `LICENSE`、`NOTICE`、`TRADEMARK.md`；安全说明见 `SECURITY.md`。

## 在 DSH 中使用

在 Planners Form 设置中安装本 Skill；回到对话后使用 `video-craft` 调用，审阅页面由 Skill 在流程需要时打开。Planners Form 安装 Skill 与公共审阅依赖；视频渲染所需的 FFmpeg、Python 包及可选引擎仍按 [install.md](install.md) 准备。API 凭据由使用者自行配置，不随仓库分发。

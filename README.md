# Video Craft

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-2563eb)](LICENSE)
[![Python](https://img.shields.io/badge/python-%3E%3D3.9-3776ab)](https://www.python.org)
[![FFmpeg](https://img.shields.io/badge/ffmpeg-required-007808)](install.md)

**从粗录音/散落素材或上游内容包出发，一竿子走完「逐字剪辑 → 实测词级时间轴 → 画面/混剪/大字报 → 语义字幕 → 侧栏播映审阅 → 核验出片」。**

> 作者：阿祖不看 TVC（小红书同名）· [demyth.info](https://demyth.info) · [Lawyif@163.com](mailto:Lawyif@163.com)

---

## 一句话看懂：它帮你做什么

普通视频工具只能管其中一截：文字工具不懂帧率和透明通道，剪辑脚本不管台词意思，动效渲染又和录音对不上拍。

**Video Craft** 把“时间脊柱、视觉层和最终核验”合成一条防错工作流，默认先把片子推到**随时可重播、可划词返修的侧边栏审阅页**，等你点头发话出片，再经严格检查写进成品：

```text
4 种常见起点：原始录屏/录音 · 已定内容包+静态 SVG (keyframe-svg) · 实拍/档案混剪 (footage-montage) · 参考片提炼风格
  → 1. 接入风格配置（读私有 ~/.config/planners/video-vault 或自动退回开源内置规范）并选定片型路线
  → 2. 词级转录 + 网页逐字剪辑审阅（直接删口误/气口，重算真实音频时间轴）
  → 3. 合成视觉层（图形拆解重构 recompose / 素材体检+镜头表混剪 montage / 或纯黑底直压不重编码）
  → 4. 出工程审阅态（edit/_engineering/）：逐句校对与视觉审阅页播放确认
  → 5. 作者下明确出片指令 → render_gate + 成片真实核验 → 写入 成品/
```

**重要原则——不要把“渲染预览”和“正式交付”混为一谈**：
- `edit/_engineering/**` 是每轮可随意重渲的**工程审阅态**，永远不算成品；
- `成品/**` 是**正式交付件**，只有作者口头指令 + 人工审阅提交覆盖当前版本（`render_gate` 放行）才允许写入。

---

## 你手头的材料，它会怎么接

| 你交给它的输入 | 自动走哪条路线 | 你每一轮能拿到什么 |
| --- | --- | --- |
| 刚录完的粗音视频（需要删口癖、定节奏） | 在线词级转录 → 逐字剪辑面 → 时间与画面 | 可在网页直接删句剪接的逐字审阅页与对齐字幕 |
| `video-idea-system` + `planners-ppt-hell` 的静态 SVG 关键帧 | `recompose`（原页拆解并编写动效贴合实测声音） | 可播放的逐句动效工程审阅页与调整待办 |
| 实拍/档案素材 + 口播（或上游 `footage-montage` 直通包） | `montage`（素材登记体检 → 镜头表 → 画框/大字报） | 拒绝胡编素材的镜头表、两关渲染体检与可播审阅 |
| 严密数学原理 / 算法推演动画需求 | 按需调用内置子技能 `skills/manim-video/` | Manim 数学动画片段合成进时间轴 |
| 一条参考视频或已完工老片 | 风格提取与进化（`helpers/extract_style.py`） | 沉淀三段式风格规则、三联帧与 2s 预览卡片 |

---

## 核心特色：两道护栏专治“静默翻车”

- **覆盖层出片前 1 秒先验透明度**：透明花字或动效层如果缺少 alpha 通道、帧率差一拍或时长不对，传统合成器不会报错，而是默默渲染五六分钟吐出全黑画面。`check_overlay.py` 会在合成前 1 秒当场拦截坏层；纯不透明满屏覆层还会走 `-c:v copy` 避免底片多编码一代。
- **不伪造词级时间戳**：词级时间直接锚定剪辑点、字幕断句与动效重音。未配置可用转录服务时脚本直接报错提示缺什么，绝不用普通大模型或估算去“猜”毫秒时间。

---

## 什么时候选我 vs 选别的 Skill

| 你的需要 | 选哪个 Skill | 理由 |
| --- | --- | --- |
| 还没想好讲什么、口播稿还没定、缺画面/素材想法 | 先用 [`video-idea-system`](https://github.com/thePlannerIvan/video-idea-system) | 先把核心洞察、可录稿和内容契约谈出来并念过确认 |
| 只需把逐页文案排成静态图 / 可编辑 PowerPoint | 用 [`planners-ppt-hell`](https://github.com/thePlannerIvan/planners-ppt-hell) | 专做静态 SVG 关键帧和 `.pptx` 导出 |
| 已经有录音/视频/素材或内容包，要剪辑、加动效字幕、审阅出片 | **本 Skill (`video-craft`)** | 接手全部制作、工程态返修与成品交付核验 |

---

## 快速开始与环境准备

> 首次配置 `ffmpeg`、Node 22+、`ws`、Python 依赖与自备转录凭据，请直接按 **[安装手册 install.md](install.md)** 逐步完成（仓库不随带任何 API 密钥）。

### 1. DSH 用户（推荐）

通过 [Planners Form](https://github.com/thePlannerIvan/planners-form) 在 DSH 设置里勾选 `video-craft` 一键安装（`ffmpeg` 与转录 API Key 仍需按 [install.md](install.md) 在本地备妥）。

### 2. Codex / Claude Code 用户

```bash
npx skills add https://github.com/thePlannerIvan/video-craft --skill video-craft
```

### 3. 直接这样开始（示例指令）

```text
使用 $video-craft 接手当前目录里的口播录音和 deliverable/：
先帮我做逐词转录并打开逐字剪辑审阅页删掉废话，确认剪点后再绑定字幕、渲染一版工程态让我试看。
```

### 运行时依赖与公共模组

- **本机必填**：`ffmpeg` / `ffprobe`、Python 3.9+（依赖见 `pyproject.toml`）、Node.js 22+（使用豆包流式 ASR 2.0 需在本 Skill 目录运行 `npm install ws`）、`.env` 填写你自己的转录凭据（模板见 `.env.example`）。
- **自动按需加载的公共模组**：仅依赖 [`planners-review-core`](https://github.com/thePlannerIvan/planners-review-core)（剪辑面与动效审阅页契约及本地宿主，缺失时自动拉取至 `~/.planners-modules/`）。*(同族另外三个模组 `planners-source-index`、`planners-fact-check`、`planners-report-kit` 本 Skill 不消费。)*

---

<details>
<summary>开发者说明：环境变量、合并血统、单测与验收指令（普通用户可忽略）</summary>

### 公共模组解析顺序与测试命令

适配器（`helpers/lib/planners_modules.py`）按 `$PLANNERS_MODULES_HOME` → `<skills-root>` → `02-skills-library/<分类>` → 用户级目录（`$PLANNERS_MODULES_INSTALL_DIR` → `$PLANNERS_MODULES_HOME` → `~/.planners-modules/`）查找 `planners-review-core`。设 `PLANNERS_NO_AUTO_INSTALL=1` 可禁止联网；`PLANNERS_MODULES_REF` 可锁定分支/tag。

```bash
# 自检公共模组绑定
python3 helpers/lib/planners_modules.py --check

# 运行单元与覆盖层 FFmpeg 实测（注意保留 ffmpeg 所在 PATH）
cd tests
PYTHONPATH=..:../helpers PATH=/opt/homebrew/bin:$PATH \
  python3 -m unittest discover -s . -p "test_*.py"

# 验收用例结构与路线矩阵检查（从 Skill 根执行）
python3 evals/run_evals.py

# 公共模组自动安装器不变量测试
python3 helpers/lib/planners_modules_install_test.py
```

### 历史演进与血统

- **2026-09-15 合并与事故防线**：由 `video-use`（时间脊柱/合成器/字幕链/交付）与 `web-video-presentation`（视觉层/alpha 编码/视觉审阅）合并脱离上游；因一次本机 libvpx 未编入 alpha 导致渲染 6 分钟全黑的教训，新增了 `check_overlay.py` 入口门禁。历史记录留在 [upstream-diff.md](upstream-diff.md) 与 `archive/`。

### 目录结构

```text
video-craft/
├── SKILL.md                 接手入口路由、主路线与完成判据
├── install.md               首次安装 FFmpeg / Python / Node / 凭据清单
├── helpers/                 转录、剪辑 EDL、overlay 校验、montage/recompose、风格提取与合成器
├── references/              11 步阶段契约 stages.md、tools.md、architecture.md 等规范
├── skills/manim-video/      数学与严密技术动画内置子技能
├── tests/                   unittest 回归（含 FFmpeg 真建文件检查）
└── evals/                   四路线覆盖矩阵校验 run_evals.py
```

</details>

---

## 第三方许可、品牌边界与商业合作

- **许可协议**：项目原创代码与文档以 [AGPL-3.0-only](LICENSE) 发布；上游源自 MIT 许可的 `browser-use/video-use` 与 `ConardLi/garden-skills`，完整声明与许可原文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 [NOTICE](NOTICE)。
- **署名边界**：出处保留在仓库与工程审阅面中，默认不写入最终成片或客户交付物；品牌与二开要求见 [TRADEMARK.md](TRADEMARK.md)，安全说明见 [SECURITY.md](SECURITY.md)。
- **商业支持**：私有视觉风格库集成、团队审阅流定制或闭源商业授权，请联系 `Lawyif@163.com` 或访问 [demyth.info](https://demyth.info)，详见 [COMMERCIAL.md](COMMERCIAL.md)。

## 相关项目

- [Video Idea System](https://github.com/thePlannerIvan/video-idea-system) —— 上游口播稿、内容契约与念稿拍板
- [Planner's PPT Hell](https://github.com/thePlannerIvan/planners-ppt-hell) —— 静态 SVG 关键帧绘制
- [Planners Review Core](https://github.com/thePlannerIvan/planners-review-core) —— 审阅页宿主与桥接缝

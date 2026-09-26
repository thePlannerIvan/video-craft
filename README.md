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

## 结构

```
L1 剪辑层    edit/edl.json               保留哪些段、怎么调色
L2 时间脊柱  edit/segment_durations.json 实测时钟（字幕与视觉层共用的真相）
L3a 字幕     srt_export.py               article-first，只认实测时间轴
L3b 视觉层   visual/                     HyperFrames / PIL / Manim / Remotion
合成         render.py                   底片 + 覆盖层 + 字幕最后
交付         成品/                       在渲染文件上验证过的视频与 SRT
```

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

或克隆到 skills 目录：

```bash
git clone https://github.com/thePlannerIvan/video-craft.git ~/.claude/skills/video-craft
```

本地开发、在本仓库内使用时：

```bash
cd 02-skills-library/03-design-delivery/video-craft
npm install                   # ws，给 SeedASR 的 WebSocket 用

# 三处同步（见仓库 AGENTS.md）
ln -sfn "$PWD" ~/.codex/skills/video-craft
ln -sfn "$PWD" ~/.claude/skills/video-craft
```

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
PYTHONPATH=..:../helpers PATH=/opt/homebrew/bin:$PATH \
  /Users/ivan/Library/CloudStorage/OneDrive-个人/文档/CodexProject/02-skills-library/.venv/bin/python \
  -m unittest discover -s . -p "test_*.py"
```

`PATH` 那一段是必须的：`check_overlay` 的 16 条要真起 `ffmpeg` 造文件。

覆盖：剪辑契约、SRT 链、实测时间轴、帧率解析与归一化、人像探测、
覆盖层契约，"渲染器真的会拒绝坏覆盖层"，以及视觉审阅的反馈直存
（服务真起来、记录按原 schema 落进 `feedback/<chapterId>.jsonl`、旧版本留底、
端口被占不冒充旧项目）、上屏文字闸门扫得到做画面产出的 SVG、
画面页导入的逐字保真与 id 碰撞、主题库校验（`theme.json` 能不能解析、
每个 `var()` 有没有解析到值、正文对比度、节奏只由 `mood` 承载）、
`script_hash` 与 `script.md` 的比对、抽段完整性（坏段重抽 / 硬失败 / 总长断言）、
渲染记录按 EDL 哈希选取、HyperFrames 渲染环境的字体缓存预检。

单独跑某一项，例如：

```bash
cd tests
PYTHONPATH=..:../helpers ../.venv/bin/python -m unittest test_themes test_svg_page_import -v
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

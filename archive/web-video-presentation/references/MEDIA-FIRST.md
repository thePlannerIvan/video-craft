# 真实素材优先（Media First，v2.1）

> 用户可验证的素材永远优先于 agent 画的示意图。违反本条是最常见的不满来源
> （"你都没用资料，而是自己画了很多模型"）。

## 素材优先级（强制顺序）

每个 visual step 的画面来源按此顺序选择，**只有前两级都没有时才允许示意图**：

1. **真实产物截图** — 项目里已有的页面/文件渲染截图（wiki、review 页、proposal.md
   渲染、品牌页面、用户丢来的素材）→ 用 playwright 截真实页面
2. **真实产物的忠实复刻** — 无法直接截图的产物（命令行输出、工具内部状态），
   用与真实产物一致的 CSS/HTML 复刻渲染后截图（字体、颜色、布局照抄）
3. **手绘示意（最后手段）** — 以上都没有时，标注 "schematic" 并在 checkpoint
   时明确告知用户这是示意

禁止：存在真实素材却自己画模型。

## 采集流程（Checkpoint Plan 前完成）

```bash
# 1. 清点素材：项目中可截图的真实页面
#    - 素材目录（如 *_test_library*/，注意脱敏副本）
#    - review 页（review/index.html）
#    - deliverable（proposal.md → html 渲染）
#    - wiki/说明页（*.html）
# 2. playwright 截图脚本 → input/assets/*.png
```

截图规范：

- 视口 1600×1000，`waitUntil: networkidle` + 400ms 稳定
- md → html 渲染用 `npx marked --gfm`，外层套统一的文档皮肤（正文字号
  15px/1.75，h2 左色条，blockquote 底色）——皮肤 = 文档的忠实呈现，不是示意
- 命名与步骤绑定：`proposal.png` / `needscope.png` / `wiki-review.png`
- 输出到 `input/assets/`，composition 引用相对路径

## 对话框 UI（一等视觉模式）

涉及"AI 如何生成/工具如何运行"的画面，用**对话框形式**呈现，不用自己画流程图：

- 用户消息：暖白气泡（白底 + 1px 边框），助手消息：IKB 蓝底白字（或主题
  accent），圆角 18px，最大宽 640px，左右交错
- 头像用首字母方块，不用图片
- 打字机 reveal 只在对话行的最后一行做，其余行按入场顺序淡入
- 示例骨架（气泡样式）见 `archive/legacy-recording/EXAMPLES/` 或按主题 token 自行实现，
  规则只有一条：**看起来像真实工具的对话界面，不像示意图**

## 脱敏副本约定

- 用户素材含敏感信息时，约定"脱敏版"目录（如 `素材_脱敏版/`）：文件名同
  原目录，内容脱敏，**只允许在脱敏版上截图**，不允许截图原始素材目录
- 截图脚本的输入路径显式写脱敏版路径，并在脚本头注释说明

## 每步素材来源记录

`storyboard.md` 每行加 `media:` 字段（`screenshot:assets/proposal.png` /
`replica` / `schematic`），checkpoint 时用户可一眼看出哪些是示意。

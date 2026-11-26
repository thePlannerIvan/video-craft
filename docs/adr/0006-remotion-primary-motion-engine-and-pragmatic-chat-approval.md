# 0006 · Remotion 4 主动效引擎、零渲染活舞台与务实会话出片授权

**Status**: accepted (supersedes ADR-0001; amends ADR-0004 chat-approval drift rule and ADR-0005 motion engine)

我们决定将新建做动效（`motion`）项目及静态视觉参考页导入的默认主动效引擎由 HyperFrames 切换为 **Remotion 4**（`<project>/remotion/src/Root.tsx`），将所有前端依赖统一托管于项目外便携**外部运行壳**，并通过基于 `@remotion/player` 的零渲染 `{kw: 1}` **活舞台桥**接入横竖屏自适应审阅台；既有 `composition/index.html` 老工程冻结为静默只读兼容通道。同时修订 `ADR-0004` 的会话出片授权漂移门禁：在坚守「必须已建审阅快照且获显式授权」底线的前提下，作者当轮在对话中明确指示微调后立即导出（`--approve-in-chat`）时直接写入最新源码指纹审计记录并放行渲染，不再被快照后源码漂移机械阻断。

## Considered Options

- **继续把 HyperFrames 作为新建动效项目的唯一引擎**：命令式时间轴在物理弹性、组件复用与真音频频谱驱动上受限，且持续暴露 `srcdoc` 时序与多 worker 脏区风险；为避免双引擎认知负担，不让新建入口继续保留双栈二选一。
- **在每个视频项目内独立执行 `npm install`**：会把数万个 `node_modules` 文件写入云盘同步目录与代码仓库，造成同步卡顿与批量删文件风险，且不利于开源用户跨平台一键配置。
- **继续保留「源码较旧审阅快照变动即阻断 `--approve-in-chat`」**：迫使创作者在对话中明确说「改完这处直接导出」后仍需无意义地重走一轮审阅重建，形成高频协作摩擦。

## Consequences

- **单引擎默认与老工程只读兼容（替代 `ADR-0001`）**：`helpers/_internal/remotion_stage.py::detect_motion_engine()` 确定性识别工程目录特征——存在 `remotion/src/Root.*`（或 `storyboard.json` 的 `remotionDir`）即走 Remotion 4，仅存在 `composition/index.html` 的存量项目继续走冻结只读兼容层；`film.py import-svg` 直接将静态 SVG 参考页包装为 Remotion 运镜场景（`remotion/src/scenes/StaticSvgReference.tsx`）。
- **便携外部运行壳**：`helpers/remotion_runtime.py {setup|doctor|path}` 统一管理 `$VIDEO_CRAFT_REMOTION_HOME`（默认 `~/.cache/video-craft/remotion-runtime/`），锁版本维护 Remotion 4、React、esbuild、TypeScript 与无头浏览器，尊重本机 npm 配置且零个人路径硬编码。
- **零渲染活舞台与横竖屏自适应审阅**：`@remotion/player` 通过 `{kw: 1}` `postMessage` 四句协议（`hello/ready`、`seek`、`play`、`pause` + 200ms `time` 节拍）与本地 esbuild 增量服务对接审阅页；单套审阅模板根据 `frame.py resolve` 自动切换横屏（反馈表单落于视频下方、零历史时右侧历史栏默认折叠）与竖屏（9:16 画布撑满视口高度、反馈与历史收拢右侧）并保留手动切换。
- **务实会话出片授权（修订 `ADR-0004`）**：存在 `review/review_data.json` 快照且传入 `--approve-in-chat` 时，`helpers/_internal/render_gate.py` 写入含 `liveSourceHash`、`driftedFromReview` 与时间戳的 `chat-approval` 审计条目并放行导出，最终由 `state_fingerprint.py` 固化实际出片源码指纹；无审阅数据或浏览器未带显式授权仍严防偷渲。
- **四道 Remotion 确定性质量门禁与缺陷根除**：新增 `helpers/_internal/remotion_gates.py` 执行静态 TypeScript 编译（`typecheck`）、分镜帧数与切点硬对账（`sync`）、每镜中段静帧自动抽取与非黑校验（`stills`）及成片交付核验；修复安全区祖先容器偏移累加误报与 `lookdev-manifest.json` 假性漂移。

# Video Craft

视频剪辑、视听合成与动画制作领域：以「剪口播」为固定底座，围绕正交的能力组合与画框，完成逐字剪辑、实测时间轴与字幕、按段分流画面制作、声景设计、交互审阅以及交付核验。

## Language

**能力组合（Capabilities）**:
围绕固定底座「剪口播」（逐字精剪、语义字幕、唯一时间脊柱与人声润色）自由叠加的零至三项正交画面能力——剪视频（`footage`）、做动效（`motion`）与实机录屏（`screen-demo`），与画框及风格彼此独立。
_Avoid_: 互斥路线硬切, 单一固定片型, 风格锁死能力

**人声润色（Voice Polish）**:
专属于人声母带的音频处理管线，默认含停顿重吸气声衰减与播客暖声校准，仅随 `人物成片.mp4` 交付而不再混入动效音效。
_Avoid_: 人声混音带音效, 二次压缩人声

**画面声景（Visual Soundscape）**:
独立于人声母带的画面声音层，由动效起伏音效与经自动筛分、避让人声频段并侧链闪避后的可选素材原声底噪组成，交付时封装进 `画面成片.mp4` 并同出无损 `画面音效轨.wav`。
_Avoid_: 画面成片必须 0 音轨, 强制画面无音轨, 把动效音效混进人物轨

**思维模型动效（Mental-Model Motion）**:
在无现成静态参考页而开启「做动效」时，构建随口播推进持续演化的单一空间概念模型与结构关系动画，与逐页文字框拼接及逐页卡片区分。
_Avoid_: 逐页 PPT 文字框拼接, 静态页面逐元素搬运

**轻量样镜定调（Look-Dev Gate）**:
开启「做动效」且上游未提供静态参考页时在全片编码前执行的前置定调关卡，只输出极简画面配比意图清单与一个匹配口播节奏的代表性样镜供创作者拍板。
_Avoid_: 未定调直接全片编码

**执行分镜（`storyboard.json`）**:
下游画面执行、媒体直切拼合、动效渲染与声景卡点共享的唯一机器真源分镜契约，用于决定各段引擎分流并派生人读概览。
_Avoid_: 图文两张皮, 手工维护多份时间轴

**动效引擎（Motion Engine）**:
承担 `motion` 与静态视觉参考页动效化的渲染与预览运行时；v3 起所有新建工程统一以 Remotion 4（`<project>/remotion/src/Root.tsx`）为默认主引擎，既有旧引擎目录（`composition/index.html`）仅作冻结只读兼容通道，由 `helpers/_internal/remotion_stage.py::detect_motion_engine()` 确定性自动识别路由。
_Avoid_: 新建项目混用双引擎, 退回命令式时间轴

**活舞台桥（Live Stage Bridge）**:
嵌入审阅页的零渲染实时交互预览容器（基于 `@remotion/player` 封装），通过 `{kw: 1}` `postMessage` 四句协议（`hello/ready`、`seek`、`play`、`pause` 与 200ms `time` 回传）及本地 esbuild 增量打包回环端口同步驱动播映、章节跳转、字幕与双轨声景试听，全程不触发视频帧渲染。
_Avoid_: 审阅期整片编码, 另造第二套播放时钟

**外部运行壳（External Runtime Shell）**:
统一托管前端动效依赖（Remotion 4、React、esbuild、TypeScript 与无头浏览器）的跨平台全局共享缓存目录，默认落在 `$VIDEO_CRAFT_REMOTION_HOME` 或 `~/.cache/video-craft/remotion-runtime/`（云盘同步目录与视频项目之外），由 `helpers/remotion_runtime.py` 幂等管理，确保项目目录内零 `node_modules` 污染。
_Avoid_: 在视频项目内安装 node_modules, 硬编码本机个人路径

**四档视觉语法（Visual Grammar）**:
在动效与画面规划中按口播语义为每一段选择的画面呈现形态，分为只看人留白（`talk-only`）、逻辑演进（`logic-diagram`）、理论拆解（`theory-board`）与实机演示录屏（`demo-footage`）。
_Avoid_: PPT 逐项搬运, 全程动画

**视觉分拍表（Visual Beat Sheet）**:
在生成执行分镜前登记每段口播的画面意图、视觉主角、关键词锚点与素材入出点的人读概览或前置草表。
_Avoid_: 原页元素逐项抄写表

**画框（Frame）**:
人物孔位、画面舞台安全区与字幕安全区的唯一权威像素几何定义，与能力组合及风格完全正交，供画面构建、录屏裁切、构建门禁、渲染交付与审阅页同源读取。
_Avoid_: 独立硬编码坐标, 风格锁死画框

**视觉参考（Visual Reference）**:
上游交付的关键帧静态页或参考截图，仅作配色、比例与造型风格参考，不再作为逐像素搬运契约。
_Avoid_: 必须逐字还原的母版

**工程态与交付态（Engineering vs Delivery）**:
工程中间态产物存放在工程工作区供编译、预览与返修；交付成片与字幕仅在创作者明确下达出片指令且通过渲染闸门后才允许写入成品交付区。
_Avoid_: 把预览产物直接拷进成品区

**分轨交付与合流交付（Split vs Composite Delivery）**:
分轨交付是同时存在真人口播与画面层时的默认交付形态，分别输出高码率人物成片（仅含人声润色）、画面成片（存在画面声景时无损封装声景并同出独立 `画面音效轨.wav`，无声景需求时合法保持零音轨）与经导入空隙修正的外挂字幕；合流交付（`--composite`）仅在显式需要单一视听成片时将人物与画面合流输出。
_Avoid_: 把动效音效混进人物成片, 强制画面成片零音轨

**会话出片授权（Chat Approval）**:
作者已建审阅快照（`review/review_data.json` 存在）并在当前对话中明确指示改动细节后立即导出时，经由 `--approve-in-chat` 写入包含最新实时源码指纹（`liveSourceHash`）、是否较审阅快照变动及时间戳的可审计 `chat-approval` 记录直接放行渲染，并在交付档案中固化最终实际源码指纹；未建审阅或未获明确指令时仍严防跳过闸门。
_Avoid_: 未建审阅或未获明确指令时私自跳过闸门, 跨版本直接跳过审阅

**时间来源（Time Source）**:
用于标定当前时间轴依据的身份级别：未录音预演（`planned`）、剪辑单预估（`projected`）、实际编码测量（`measured`）与外部字幕导入（`srt-import`）。
_Avoid_: 把预演时长当实测

## Retired Terms

- `生产模式（Production Mode）` / `pure-talking` / `footage-montage` / `keyframe-svg` / `片型` / `graphic` / `montage` → 已退役互斥分流概念（见 `ADR-0005`），统一改用正交的 `能力组合`（底座「剪口播」+ `footage` / `motion` / `screen-demo`）与 `画框`
- `画面成片必须 0 音轨` / `无声纯画面` / `音效归人物轨` → 已退役（见 `ADR-0005`），改用 `人声润色` 归 `人物成片.mp4`、`画面声景` 归 `画面成片.mp4` 与独立 `画面音效轨.wav`
- `page 十步路线` / `video-idea-system` → 已退役历史流程，不再作为默认入口

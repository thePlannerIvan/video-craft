# Video Craft

视频剪辑、视听合成与动画制作领域：承接已确定内容或原始口播录像，完成逐字剪辑、实测时间轴与字幕、画面与声音合成、交互审阅以及交付核验。

## Language

**生产模式（Production Mode）**:
对外唯一的主线分流轴，与上游 `video-manager` 一一对应，分为纯口播（`pure-talking`）、实景素材混剪（`footage-montage`）与关键帧及图形动画（`keyframe-svg`）三种。
_Avoid_: 片型, graphic, 十步路线

**四档视觉语法（Visual Grammar）**:
在 `keyframe-svg` 主线中按口播语义为每一段选择的画面呈现形态，分为只看人留白（`talk-only`）、逻辑演进（`logic-diagram`）、理论拆解（`theory-board`）与实机演示录屏（`demo-footage`）。
_Avoid_: PPT 逐项搬运, 全程动画

**视觉分拍表（Visual Beat Sheet）**:
在动工制作画面前登记每段口播所选视觉语法、核心视觉主角、大字锚点、实机录屏入出点及对应口播词锚的简表。
_Avoid_: 原页元素逐项抄写表

**画框（Frame）**:
人物孔位、画面舞台安全区与字幕安全区的唯一权威像素几何定义，供画面构建、录屏裁切、构建门禁、渲染交付与审阅页同源读取。
_Avoid_: 独立硬编码坐标, 仅用于蒙太奇的底框

**视觉参考（Visual Reference）**:
上游交付的关键帧静态页或参考截图，仅作配色、比例与造型风格参考，不再作为逐像素搬运契约。
_Avoid_: 必须逐字还原的母版

**工程态与交付态（Engineering vs Delivery）**:
工程中间态产物存放在工程工作区供编译、预览与返修；交付成片与字幕仅在创作者明确下达出片指令且通过渲染闸门后才允许写入成品交付区。
_Avoid_: 把预览产物直接拷进成品区

**时间来源（Time Source）**:
用于标定当前时间轴依据的身份级别：未录音预演（`planned`）、剪辑单预估（`projected`）、实际编码测量（`measured`）与外部字幕导入（`srt-import`）。
_Avoid_: 把预演时长当实测

## Retired Terms

- `片型` / `graphic` / `montage`（外部路由用词）→ 统一改用 `生产模式`（`keyframe-svg` / `footage-montage` / `pure-talking`）
- `page 十步路线` / `video-idea-system` → 已退役历史流程，不再作为默认入口

# HyperFrames 审阅适配器

HyperFrames 是新工程的唯一播放与动效运行时。官方 player 负责时间、媒体、clip 显隐、播放、定位和倍速；审阅页不再复制一套 GSAP、SVG 定时器或隐藏视频时钟。

## 两条修改路径

没有适配器时，审阅页只提供真实工程的播放控制与批注。动画修改写成结构化反馈，由模型修改 composition 或 `timeline/choreography.json`，重新构建审阅后再看结果。这是默认且最稳定的路径。

有适配器时，composition 可以额外提供一组**可审阅参数**。适配器必须跟随 composition 一起构建，并且只修改声明过的参数：

```js
window.VideoCraftReviewAdapter = {
  getModel() {
    return {
      steps: [],
      primitives: [],
      cameras: [],
      cues: []
    };
  },
  applyOverride(override) {},
  serializeOverrides() { return {}; },
  resetOverrides() {}
};
```

这是可选能力，不是每个 composition 都必须实现。适配器不能创建第二个播放头，不能自行推进时间，也不能依赖父页面直接访问子 iframe DOM。播放状态从 HyperFrames player 读取；需要试听时由审阅页调用 player 的 `seek`、`play`、`pause` 和 `playbackRate`。

## 与旧 SVG 引擎的关系

`visual/assets/svg-anim-engine.js` 和 `VideoCraftAnimEngine` 只服务于旧 SVG 审阅兼容路径：它可以在静态 SVG 舞台上即时预演 Step、原语、镜头和子延迟。它不是新 HyperFrames composition 的控制器，也不应再被写入 HyperFrames 的主时间轴。

旧项目迁移时可以继续使用它；新项目应优先把需要调整的参数写进 composition 的声明式配置，或走反馈 → 修改源 → 重建的路径。只有在适配器真实存在并通过播放、定位、快照和反馈回归后，审阅页才可以显示对应的即时参数控件。

## 反馈记录

无论有没有适配器，审阅意见都必须记录稳定 `unitId`、`stepId`、`playbackTimeMs`、`animationAnchor` 和结构化调整。页面上的即时 override 是预览状态，不等于源工程已经修改；提交后仍需由模型收件、修改源文件、重建审阅并重新核验。

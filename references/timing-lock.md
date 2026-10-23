# 渲染前置：时间、画面与审阅

作者明确出片后、启动生产编码前读本页。`deliver` 自动执行适用机械检查；人工判断仍按本页完成，合成后的完成线见 delivery.md。

1. 读取当前 timeline 的来源与绑定。EDL 项目区分 projected 与 measured，交付必须完成同版实测核验；外部 SRT 保持 srt-import 并核真实音频；未录音 planned 不进入成片。来源规则归 visual-timeline.md。
2. 有参考页动画时 film verify 通过；拆解表与 Beat 映射完整。纯剪辑不伪造参考页来通过此检查。
3. composition 通过 HyperFrames check；手写 GSAP 还跑 check_motion_targets（selector 与静态 transform）。两者检查不同问题。
4. 读取项目实际声音路径，核音轨、时长与字幕覆盖；不强制输入必须叫 input/audio.mp3。明确有声/无声、人物/无人物、外挂/烧录合同。
5. review 运行时检查通过；人工提交对应当前快照；模型读取反馈，未决项已经处理或由作者明确接受；作者指令覆盖当前出片版本。render_gate 放行不能替代这三个人工判断。
6. probe_env 报能力；check_render_env 给预算。环境硬错误阻断；内存预算例外按 delivery.md 记录，不自行扩大并发。

时间发生变化：改来源或分组 → 重派生 timeline → 更新场景绑定 → 重建审阅 → 新版本人审。允许模型编写消费 timeline 的场景代码；不允许手调最终数字掩盖源不一致。要验证像素时优先工程播放器截图；生产 render 只在本页条件满足后执行。

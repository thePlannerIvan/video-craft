# Recording

The default output path is: play the webpage once by SRT timing, then align it with the already edited audio/video track.

> **v1-era chapter anchors**（React 时代结构参考，v2 勿抄代码）见本目录
> 下 `EXAMPLES/`；当前 v2 章节写法见 `../references/COMPOSITION-CRAFT.md`。

## Before Recording

Complete Timing Lock first:

- `presentation/public/step-durations.json` exists and is SRT-derived
- every chapter has `timeline.ts`
- `timeline.ts.length` matches implemented visual steps
- `?auto=1` plays from start to end without manual clicks
- open feedback items are fixed or explicitly accepted

## Final Recording

1. Start the dev server.
2. Open the page in a browser.
3. Use `http://localhost:5174/?auto=1` for one-shot playback.
4. Fullscreen the browser window.
5. Start screen recording.
6. Let the page play through once.
7. Stop recording and trim head/tail in the editor.
8. Place the already edited audio under the screen recording; it should align with the SRT timing.

## Review Recording

During review, open the normal page without `?auto=1`:

1. Use the Play button to start/pause SRT-timed playback.
2. Expand ReviewPanel.
3. Pause on a problem step.
4. Save step-level feedback.
5. Fix the page and replay the affected section.

## Tools

| Platform | Tool | Notes |
|---|---|---|
| macOS | Cmd+Shift+5 | Record selected browser window |
| macOS | QuickTime | Simple full-screen recording |
| Cross-platform | OBS Studio | 1920x1080 canvas, 60fps |

## If Timing Feels Wrong

Do not stretch CSS animation timing to fake sync.

Instead:

1. regroup SRT lines in `timeline/grouping.json`
2. rebuild `timeline/timeline.json`
3. rebuild `presentation/public/step-durations.json`
4. update affected chapter `timeline.ts`
5. replay with `?auto=1`

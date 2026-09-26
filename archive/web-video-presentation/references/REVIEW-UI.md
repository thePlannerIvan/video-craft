# Review UI (v2)

Step-level feedback stays the core review mechanism, but the visuals are
now the HyperFrames composition, played back inside the review page via
`<hyperframes-player>` instead of bespoke React chapter components.

## Review page

`assets/review-page-template.html` is the v2 review page. Copy it to
`<project>/review/index.html` (paths in the template assume
`<project>/review/` — it reads `../timeline/timeline.json` and embeds
`../composition/index.html`):

```html
<script type="module" src="https://cdn.jsdelivr.net/npm/@hyperframes/player"></script>
<hyperframes-player src="../composition/index.html" controls></hyperframes-player>
```

The player loads the composition in a sandboxed iframe, auto-detects
dimensions/duration, and provides play/pause + scrubber, so the user
can pause exactly on a problem frame. Useful attributes: `poster`,
`playback-rate`, `muted`, `autoplay`, `loop`.

## 播放器必须指向 preview 服务器的运行时注入端点（非原始文件）

**非显然知识（实测得出）**：clip 可见性切换和音频播放由 HyperFrames 运行时
管理，而运行时只在两种路径注入：渲染器、`hyperframes preview` 服务器。
用静态文件服务器（如 python http.server）直接加载 `composition/index.html`
时没有运行时——时间轴会走，但所有 clip 同时可见（画面叠在一起，只剩 DOM
最后的 clip），音频也不播放。

因此审阅流程必须：

```bash
cd composition && npx hyperframes preview --port 5176 &   # 运行时注入服务器
```

播放器 `src` 指向该服务器的预览端点（`<meta.json>` 里的 `name` 决定路径段）：

```
http://localhost:5176/api/projects/composition/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player
```

`hyperframes preview` 会额外启动一个 Studio 壳（默认端口），审阅页只需
上述端点。端口被占用时换端口并同步改 src。

## Feedback schema (unchanged from v1)

Feedback is JSONL, one object per line, saved to
`feedback/<chapterId>.jsonl` (and `feedback/storyboard.jsonl` for the
Plan checkpoint):

```json
{
  "chapterId": "intro",
  "stepId": "intro-003",
  "stepIndex": 3,
  "srtRange": [12, 14],
  "caption": "Current caption text",
  "durationMs": 7500,
  "type": "visual",
  "text": "This screen is too dense.",
  "status": "open",
  "batchId": "review-20260705-1",
  "createdAt": "2026-07-05T12:00:00.000Z",
  "codeVersion": "abc1234"
}
```

Allowed `type` values: `visual` / `timing` / `asset` / `copy` / `animation`.

The review page copies a generated JSONL line to the clipboard; the
agent appends it to the right `feedback/<chapterId>.jsonl`.

## Agent read protocol (must follow)

1. Read all `feedback/*.jsonl` files.
2. Sort by `createdAt` ascending to understand order; the latest
   `batchId` round has highest priority.
3. Group by `chapterId` + `stepId`; skip old feedback superseded by a
   newer one on the same step.
4. Fix the smallest affected screen (edit `composition/index.html`).
5. Keep timing unchanged unless feedback type is `timing` and the user
   explicitly accepts regrouping (then regenerate upstream).
6. Re-run `cd composition && npm run check` — 0 errors.
7. Mark processed feedback `status: "resolved"`.

## Fix Loop

Feedback → fix composition → `npm run check` → re-render (~30s) →
show the new MP4. Fast enough to iterate per feedback round.

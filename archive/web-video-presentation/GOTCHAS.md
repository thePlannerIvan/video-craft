# GOTCHAS

Session-learned pitfalls. Read before starting a new session.

## 1. Stale review servers keep ports 5176 / 8899

The Review checkpoint serves two processes: `npx hyperframes preview
--port 5176` (runtime injection) and `python3 -m http.server 8899`
(static review page). Servers left running from a previous session keep
listening and will serve the **old project** — a newly started pair then
either dies on the port or you silently review the wrong project (observed
2026-08: both ports held by leftover processes from an earlier session).

**Before serving:**
1. `lsof -nP -iTCP:5176 -sTCP:LISTEN` and same for 8899 — kill leftovers.
2. After starting, verify the served project: `curl -s
   http://localhost:8899/review/` must contain the current project's
   markers (a stale server still returns 200 — check content, not status).
3. If the port is genuinely taken by another service, change the port AND
   the player `src` in the review page (REVIEW-UI.md).

## 2. EXAMPLES anchors are v1-era — structure only, never copy code

`archive/legacy-recording/EXAMPLES/` was moved out of the v2 active path
(2026-08): the `.tsx` anchors import the v1 React `templates/` app, and
their internal links pointed at the pre-rename `CHAPTER-CRAFT.md`. They
exist only as structural reference. In a v2 HyperFrames composition
(HTML/CSS/JS), copying their React code breaks the build; current chapter
guidance lives in `references/COMPOSITION-CRAFT.md`.

"""Generate a HyperFrames composition skeleton from timeline.json + theme.

The composition is the single visual source of truth in web-video-
presentation v2. This script owns everything deterministic:

  - one clip per visual step (data-start/data-duration straight from
    timeline.json, track = chapter index)
  - theme tokens.css -> :root CSS variables
  - one <audio> element spanning the whole timeline (SRT-aligned)
  - a paused GSAP timeline with per-chapter boundary hints for the
    agent's progressive-reveal implementation

The agent implements visuals inside each clip; it must NOT change the
generated timing (--verify re-derives the timeline from the HTML and
compares it field-by-field against timeline.json).

Usage:
    python scripts/generate-composition.py <project> [--theme <id>] [--audio <path>]
    python scripts/generate-composition.py <project> --verify
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
THEMES_DIR = SKILL_DIR / "themes"
DEFAULT_THEME = "midnight-press"
GSAP_FILE = "gsap-3.14.2.min.js"          # 版本写进文件名，便于追溯
BRIDGE_FILE = "composition-embed-bridge.js"
STUDIO_HOOK_FILE = "composition-studio-hook.js"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_svg_page as pages  # noqa: E402  (same directory)

# .layout file values: landscape 1920x1080, portrait / overlay 1080x1920.
# overlay additionally renders with a transparent canvas (花字层 compositing).
LAYOUTS = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1920),
    "overlay": (1080, 1920),
}
DEFAULT_LAYOUT = "landscape"

BASE_CSS = """
      .clip { position: absolute; inset: 0; }
      .scene { position: absolute; inset: 0; }
      .fill { position: absolute; inset: 0; background: var(--fill-bg, var(--surface, #fafaf8)); }
      .scene-body {
        position: absolute; inset: 0;
        display: flex; align-items: center; justify-content: center;
        overflow: hidden;
      }
      /* imported SVG page: page coordinates are video pixels
         (viewBox 0 0 1920 1080), so no transform is needed here. */
      .video-page { position: absolute; inset: 0; }
      .video-page > svg { width: 100%; height: 100%; display: block; }
"""


def load_layout(project: Path) -> str:
    layout_file = project / ".layout"
    if not layout_file.exists():
        return DEFAULT_LAYOUT
    layout = layout_file.read_text(encoding="utf-8").strip()
    return layout if layout in LAYOUTS else DEFAULT_LAYOUT


def load_picture_pages(project: Path):
    """(page dir, package root) for the static SVG screens, or (None, None).

    Either the project's `.pages` pointer at the picture project, or the
    package the upstream hands over at `input/scenes/`.
    """
    return pages.resolve_pages(project)


def load_theme_tokens(theme_id: str) -> str:
    tokens_css = THEMES_DIR / theme_id / "tokens.css"
    if not tokens_css.exists():
        sys.exit(f"theme not found: {theme_id} (themes live in {THEMES_DIR})")
    css = tokens_css.read_text(encoding="utf-8")
    m = re.search(r":root\s*\{(.*?)\}", css, re.S)
    if not m:
        sys.exit(f"no :root block in {tokens_css}")
    return m.group(1).strip()


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate(project: Path, theme_id: str, audio: Path | None,
             layout: str | None = None, media_box: tuple[float, float, float, float] | None = None,
             studio_notes_url: str | None = None) -> Path:
    timeline = json.loads((project / "timeline" / "timeline.json").read_text(encoding="utf-8"))
    total_ms = timeline["totalDurationMs"]
    total_s = total_ms / 1000.0
    # Resolve the exact snapshot before any output or audio copy is written.
    page_dir, asset_root = load_picture_pages(project)
    tokens = load_theme_tokens(theme_id)

    layout = layout or load_layout(project)
    width, height = LAYOUTS[layout]
    transparent = layout == "overlay"
    if transparent:
        # overlay canvas: no opaque body/root background, .fill defaults to
        # transparent unless the agent sets --fill-bg per scene
        tokens += "\n        --canvas-bg: transparent;\n        --fill-bg: transparent;"

    audio_attr = ""
    if audio is not None and audio.exists():
        # HyperFrames requires media inside the composition project (no ../ paths)
        assets_dir = project / "composition" / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        # 保留源的后缀：把 m4a 改名成 .mp3 会让 MIME 与容器对不上（能播是碰运气）。
        audio_name = f"audio{audio.suffix.lower() or '.m4a'}"
        shutil.copy2(audio, assets_dir / audio_name)
        audio_attr = (
            f'\n    <audio id="narration" data-start="0" data-duration="{total_s:.3f}" '
            f'src="assets/{audio_name}"></audio>'
        )

    # 随 composition 走的本地资源，一律不外链：
    #   · GSAP —— 渲染不该依赖网络，同一份 composition 在不同的机器上必须同字节；
    #   · 嵌入桥 —— 审阅页要演活的工程态，就得能驱动这份文件。审阅页自己跑在
    #     不透明源的 sandbox iframe 里，够不着子页 DOM，只能 postMessage；协议因此
    #     必须随 composition 走，而且只在被嵌入时生效（单独打开或渲染时 bridge
    #     第一行就返回，一个字节都不影响）。
    # 放 assets/ 而非 CDN，才不会被信任围栏打回。版本写进文件名，便于追溯。
    # 注意：本文件里的 SKILL_DIR 是 visual/ 目录（THEMES_DIR = SKILL_DIR/"themes"）。
    assets_dir = project / "composition" / "assets"
    vendor_tags: list[str] = []
    for src in (SKILL_DIR / "assets" / "vendor" / GSAP_FILE,
                SKILL_DIR / "assets" / BRIDGE_FILE):
        if not src.is_file():
            continue
        assets_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, assets_dir / src.name)
        vendor_tags.append(f'<script src="assets/{src.name}"></script>')
    # studio 意见收集器：studio 的「Describe a change to the agent」只把 prompt 放进
    # 剪贴板，不写任何文件。composition 与 studio 同源（shadow iframe，已实测
    # allow-same-origin），所以它能把那一枪顺手 POST 到收集器落成文件。
    # 收集器没起时 fetch 静默失败，studio 行为一个字节都不变。
    # studio 意见钩子**必须内联**：studio 的 player 路由会把 composition 里所有
    # `src=` 的脚本剥掉（它用自己的 runtime 提供 GSAP），只留内联脚本 —— 实测过：
    # player 文档里只剩 runtime.js 一个 src 脚本。所以钩子不能靠 assets/ 引用。
    # 它同时很小（约 2.5KB），内联的代价可以忽略。
    hook_src = SKILL_DIR / "assets" / STUDIO_HOOK_FILE
    if studio_notes_url and hook_src.is_file():
        # meta 而不是内联 <script> 传配置：下游有工具按「第一个内联 script」定位生成器的
        # 骨架脚本，多一个内联脚本会把锚点抢走（踩过：配置脚本被整块替换掉）。
        vendor_tags.append(
            '<meta name="kw-studio-notes" content="' + esc(studio_notes_url) + '">')
        # 拷进 assets/ 但**不发 <script src>**：studio 的 runtime 会把内联脚本拼成
        # 一个大脚本执行，实测我们的钩子排在动画之后、而它前面那段抛了错，于是钩子
        # 永远轮不到 —— 而动画那段是确实执行的。所以钩子由组装动画那一步并进同一个
        # 块里（patch_composition.py），跟着已经证明能跑的东西走。
        assets_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(hook_src, assets_dir / hook_src.name)
    vendor_attr = ("\n    ".join(vendor_tags) + "\n    ") if vendor_tags else ""

    page_default = pages.read_composite_default(asset_root, project) if page_dir else {}
    imported: list = []
    per_screen: dict[str, dict] = {}

    clips: list[str] = []
    tl_hints: list[str] = []
    for ci, ch in enumerate(timeline["chapters"]):
        tl_hints.append(
            f"      // {ch['id']}: boundaries " + ", ".join(f"{st['startMs'] / 1000.0:.2f}s" for st in ch["steps"][1:]) + " — progressive reveals go here"
        )
        for st in ch["steps"]:
            start_s = st["startMs"] / 1000.0
            dur_s = st["durationMs"] / 1000.0
            facts = {
                "composite": st.get("composite") or page_default.get("composite") or "replace",
                "personWindow": st.get("personWindow") or page_default.get("personWindow"),
                "captionSafe": st.get("captionSafe") or page_default.get("captionSafe"),
            }
            per_screen[st["id"]] = facts

            # 录屏 / 实拍段：时间轴用 mediaClips 声明「这一段画面来自哪个文件的哪一段」。
            # 媒体由框架播（data-media-start 是源内起点），所以它不该被包进 <section>：
            # <video> 自己就是一个 clip。这样 composition 就是画面轨的唯一源 ——
            # 审阅页演的、渲染出来的，是同一份东西，不需要在 ffmpeg 里再拼一次。
            step_media = st.get("mediaClips") or []
            for mi, mc in enumerate(step_media):
                src = Path(str(mc.get("src") or ""))
                if not src.is_absolute():
                    src = project / src
                if not src.is_file():
                    sys.exit(f"step {st['id']} 声明了 mediaClips src={mc.get('src')!r}，"
                             f"但 {src} 不存在")
                assets_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, assets_dir / src.name)
                box = mc.get("box") or st.get("mediaBox") or media_box or (0, 0, width, height)
                left, top, mw, mh = (float(v) for v in box)
                m_start = float(mc.get("startMs", st["startMs"])) / 1000.0
                m_dur = float(mc.get("durationMs", st["durationMs"])) / 1000.0
                clips.append(
                    f"    <!-- step {st['id']} media #{mi + 1}/{len(step_media)} | "
                    f"源 {esc(src.name)} in={float(mc.get('in', 0)):.3f}s | "
                    f"{esc(st.get('screenIntent') or '')} -->\n"
                    f'    <video class="clip" id="step-{esc(st["id"])}-{mi}" '
                    f'data-start="{m_start:.3f}" data-duration="{m_dur:.3f}" '
                    f'data-media-start="{float(mc.get("in", 0)):.3f}" '
                    f'data-track-index="{ci}" src="assets/{esc(src.name)}" '
                    f'muted data-has-audio="false" '
                    f'style="position:absolute; left:{left:g}px; top:{top:g}px; '
                    f'width:{mw:g}px; height:{mh:g}px; object-fit:contain;"></video>'
                )
            if step_media and not st.get("sourcePageKey"):
                continue          # 这一段只有媒体，没有模板页

            page_key = st.get("sourcePageKey")
            page_comment = ""
            if page_key:
                if page_dir is None:
                    sys.exit(f"step {st['id']} declares sourcePageKey={page_key}, but the project "
                             f"has no picture pages: write {project / '.pages'} with the picture "
                             f"project, or put one SVG per screen in {project / pages.PACKAGE_SCENES}")
                try:
                    result = pages.import_page(page_key, page_dir=page_dir,
                                               asset_root=asset_root, project=project)
                except (pages.PageImportError, FileNotFoundError) as exc:
                    sys.exit(str(exc))
                imported.append(result)
                if result.problems:
                    sys.exit(f"page {page_key} cannot be imported as-is:\n  "
                             + "\n  ".join(result.problems))
                if not result.verbatim:
                    sys.exit(f"page {page_key}: the import changed the page — the round trip is not "
                             "byte-identical, so what landed here is not the page any more")
                ids = result.audit["element_ids"]
                if not ids:
                    print(f"warn: page {page_key} has no element id below <svg> — the animation "
                          "layer can only address the page as a whole. Ask the picture side to give "
                          "every element that may be emphasized a stable id, then re-render.")
                page_comment = (
                    f"    <!-- page {esc(page_key)} imported verbatim from {result.source}\n"
                    f"         · only <image> href prefixes rewritten; round trip proved byte-identical\n"
                    f"         · address elements by id ({len(ids)} on this page) — never by DOM index:\n"
                    f"           one more element after a re-render re-binds an index silently\n"
                    f"         · animate on wrapper layers outside <svg>; the page itself is not rewritten -->\n"
                )
                body = (
                    f'        <div class="video-page" data-page-key="{esc(page_key)}">\n'
                    f"{result.inlined}\n"
                    f"        </div>"
                )
            else:
                body = (
                    f'        <div class="placeholder" style="color: var(--text-mute, #737373); '
                    f'font-size: 28px; text-align: center; padding: 40px;">{esc(st["id"])}</div>'
                )
            comment = (
                f"    <!-- step {st['id']} {dur_s:.2f}s | caption: {esc(st['caption'])}"
                f" | intent: {esc(st.get('screenIntent') or '')}"
                f" | model: {esc(st.get('visualModel') or '')}"
                f" | {esc(st.get('modelStructure') or '')}"
                f" | text rule: {esc(st.get('onScreenTextRule') or '')}"
                f" | composite: {esc(str(facts['composite']))}"
                f" | TODO: implement visual inside this clip; do not change data-start/data-duration -->"
            )
            window_attr = (f' data-person-window="{esc(json.dumps(facts["personWindow"], ensure_ascii=False))}"'
                           if facts["personWindow"] else "")
            safe_attr = (f' data-caption-safe="{esc(json.dumps(facts["captionSafe"], ensure_ascii=False))}"'
                         if facts["captionSafe"] else "")
            clips.append(
                f"{page_comment}{comment}\n"
                f'    <section class="clip scene" id="step-{esc(st["id"])}" '
                f'data-start="{start_s:.3f}" data-duration="{dur_s:.3f}" data-track-index="{ci}" '
                f'data-composite="{esc(str(facts["composite"]))}"{window_attr}{safe_attr}>\n'
                f'      <div class="fill"></div>\n'
                f'      <div class="scene-body">\n'
                f"{body}\n"
                f"      </div>\n"
                f"    </section>"
            )

    if imported:
        ids = pages.audit_pages(imported)
        if not ids["clean"]:
            print("warn: ids shared by more than one page — the pages land in ONE DOM, where a")
            print("      repeated id makes \"#name\" resolve to the first match, so animating it")
            print("      can hit another screen's element and nothing fails:")
            for name, owners in ids["collisions"].items():
                print(f"        #{name}  in  {', '.join(owners)}")
            print("      Fix on the picture side: prefix every id with its page key.")
        print(f"pages imported -> "
              f"{pages.write_manifest(project, page_default, imported, per_screen, ids)}")

    html = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    {vendor_attr}<style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: var(--canvas-bg, #000); }}
      #root {{ position: relative; width: {width}px; height: {height}px; background: var(--canvas-bg, #000); }}
      :root {{
{tokens}
      }}
{BASE_CSS}
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="{total_s:.3f}"
      data-width="{width}"
      data-height="{height}"
    >
{audio_attr}
{chr(10).join(clips)}
    </div>

    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
{chr(10).join(tl_hints)}
      // Scene entrances: gsap.set/fromTo on .scene-body or inner elements.
      // Boundary initial states must be set OUTSIDE the timeline (gsap.set) for frame 0.
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""
    out = project / "composition" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    n_steps = sum(len(c["steps"]) for c in timeline["chapters"])
    print(f"composition skeleton -> {out}")
    print(f"  {len(timeline['chapters'])} chapters / {n_steps} steps / {total_s:.2f}s total")
    if audio_attr:
        print("  audio embedded")
    return out


STEP_RE = re.compile(r'id="step-([^"]+)" data-start="([\d.]+)" data-duration="([\d.]+)"')
AUDIO_RE = re.compile(r'<audio id="narration" data-start="([\d.]+)" data-duration="([\d.]+)"')


def verify(project: Path) -> int:
    timeline = json.loads((project / "timeline" / "timeline.json").read_text(encoding="utf-8"))
    html_path = project / "composition" / "index.html"
    if not html_path.exists():
        print(f"x composition not found: {html_path}")
        return 1
    html = html_path.read_text(encoding="utf-8")

    expected = []
    for ch in timeline["chapters"]:
        for st in ch["steps"]:
            expected.append((st["id"], st["startMs"] / 1000.0, st["durationMs"] / 1000.0))

    found = {i: (float(s), float(d)) for i, s, d in STEP_RE.findall(html)}
    errors = 0

    # 一屏不一定等于一个 clip。声明了 mediaClips 的屏（录屏/实拍）拆成若干个
    # step-<id>-<n> 的 <video>，各自带 data-media-start 指回源内位置；而它们的落片时间
    # 按**实测累计**走，不按步区间 —— 步区间是 cue 派生的，比媒体窗口少一个片头静音。
    # 所以这里逐片核对，别拿步区间去套。
    want = 0
    for st in (s2 for ch in timeline["chapters"] for s2 in ch["steps"]):
        sid = st["id"]
        media = st.get("mediaClips") or []
        if media:
            want += len(media)
            for n, mc in enumerate(media):
                key = f"{sid}-{n}"
                if key not in found:
                    print(f"x missing media clip: {key}")
                    errors += 1
                    continue
                fstart, fdur = found[key]
                mstart, mdur = mc["startMs"] / 1000.0, mc["durationMs"] / 1000.0
                if abs(fstart - mstart) > 0.05 or abs(fdur - mdur) > 0.05:
                    print(f"x {key}: html {fstart:.3f}+{fdur:.3f} "
                          f"vs timeline mediaClips {mstart:.3f}+{mdur:.3f}")
                    errors += 1
        else:
            want += 1
            if sid not in found:
                print(f"x missing clip: {sid}")
                errors += 1
                continue
            fstart, fdur = found[sid]
            estart, edur = float(st["startMs"]) / 1000.0, float(st["durationMs"]) / 1000.0
            if abs(fstart - estart) > 0.05 or abs(fdur - edur) > 0.05:
                print(f"x {sid}: html {fstart:.3f}+{fdur:.3f} vs json {estart:.3f}+{edur:.3f}")
                errors += 1

    if len(found) != want:
        print(f"x clip count mismatch: html {len(found)} vs expected {want}")
        errors += 1

    total_s = timeline["totalDurationMs"] / 1000.0
    width, height = LAYOUTS[load_layout(project)]
    root_size = re.search(r'data-width="(\d+)" data-height="(\d+)"', html)
    if root_size and (int(root_size.group(1)), int(root_size.group(2))) != (width, height):
        print(f"x root size {root_size.group(1)}x{root_size.group(2)} vs .layout {width}x{height}")
        errors += 1

    # Assets must stay inside the composition. `hyperframes check` rejects a
    # `../` path outright (invalid_parent_traversal_in_asset_path), so a page
    # that reached this file without its image hrefs rewritten is caught here
    # rather than at render time. The importer does the rewrite; this asserts it
    # happened.
    traversal = sorted({m for m in re.findall(r'(?:href|src)="(\.\./[^"]*)"', html)})
    if traversal:
        print(f"x {len(traversal)} asset path(s) traverse above the composition root: "
              + ", ".join(traversal[:3]))
        print("  HyperFrames rejects these. The page importer rewrites <image> hrefs to")
        print("  assets/pages/<page_key>/...; a page inlined without that rewrite is the cause.")
        errors += 1

    audio = AUDIO_RE.search(html)
    if audio is None:
        print("warn: no <audio> element (expected when the project has narration audio)")
    elif abs(float(audio.group(2)) - total_s) > 0.1:
        print(f"x audio duration {audio.group(2)}s vs total {total_s:.3f}s")
        errors += 1

    root_dur = re.search(r'data-duration="([\d.]+)"', html)
    if root_dur and abs(float(root_dur.group(1)) - total_s) > 0.1:
        print(f"x root duration {root_dur.group(1)}s vs total {total_s:.3f}s")
        errors += 1

    if errors == 0:
        print(f"ok: verify passed, {len(expected)} steps match timeline.json, total {total_s:.2f}s")
    return 1 if errors else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate/verify HyperFrames composition skeleton")
    ap.add_argument("project", type=Path)
    ap.add_argument("--theme", type=str, default=None, help=f"theme id (default: .theme file or {DEFAULT_THEME})")
    ap.add_argument("--audio", type=Path, default=None, help="narration audio file (default: <project>/input/audio.mp3)")
    ap.add_argument("--layout", type=str, default=None,
                    help=f"layout: landscape|portrait|overlay (default: .layout file or {DEFAULT_LAYOUT})")
    ap.add_argument("--studio-notes-url", type=str, default="http://127.0.0.1:4319/note",
                    help="studio 意见收集器地址（helpers/studio_notes.py 起的那个）；"
                         "传空字符串则不给 composition 装这个钩子")
    ap.add_argument("--media-box", type=str, default=None,
                    help="录屏/实拍段落在画布上的落位 x,y,w,h（像素）。默认满幅；"
                         "留白的分屏构图在这里给，例如 personWindow 在左时用 620,0,1300,1080")
    ap.add_argument("--verify", action="store_true", help="verify composition timing against timeline.json and exit")
    args = ap.parse_args()

    project = args.project.resolve()
    if not (project / "timeline" / "timeline.json").exists():
        sys.exit(f"no timeline/timeline.json at {project}")

    if args.verify:
        sys.exit(verify(project))

    theme = args.theme
    if theme is None:
        theme_file = project / ".theme"
        theme = theme_file.read_text().strip() if theme_file.exists() else DEFAULT_THEME
    audio = args.audio or (project / "input" / "audio.mp3")
    layout = args.layout or load_layout(project)
    media_box = None
    if args.media_box:
        try:
            parts = [float(v) for v in args.media_box.split(",")]
        except ValueError:
            sys.exit("--media-box 需要四个数：x,y,w,h")
        if len(parts) != 4:
            sys.exit("--media-box 需要四个数：x,y,w,h")
        media_box = tuple(parts)
    generate(project, theme, audio, layout, media_box,
             args.studio_notes_url or None)
    sys.exit(verify(project))


if __name__ == "__main__":
    main()

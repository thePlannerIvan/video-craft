#!/usr/bin/env python3
"""静态断言：这份 composition 能不能进审阅页的活舞台。

`hyperframes check` 全绿**不能**回答这个问题。它跑的是官方预览服务的加载路径；
审阅页的舞台是另一条路：`build_review.py` 把编译后的 HTML 连同素材装进页面，
再由页面交给官方 player 的 `srcdoc`。在那条路上，`index.html` 里的内联
`<script>` 会被预览编译器改写成 `type="text/hf-after-fonts"`，而 srcdoc 里没有
人替它重跑——时间轴从未构建，播放器拿到 0 秒、舞台全黑，右侧人物却照常播。
2026-10-21 的 XHS 三条片就是这样：`hyperframes check` 0 error、对比度 46/46，
审阅页 0 秒。`hyperframes check --json` 那次也没有报错，只是 `runtime.duration`
为 `null`、`contrast.checked` 为 0（没有构建出 DOM，自然没有可测的对比度）。

本检查只做**静态**判断，不需要浏览器、不启动服务。它钉住四件事：

1. 根元素有唯一的 `data-composition-id`；
2. 会执行逻辑的内联 `<script>` 里没有 `HF.build(` / `window.__CFG__` /
   `__timelines[...] =`（这些都会被编译器改写成永不执行的数据块）；
3. 时间轴的注册名等于根元素的 `data-composition-id`；
4. `assets/composition-embed-bridge.js` 随 composition 一起在。

用法与退出码
------------
    python3 helpers/check_live_stage.py <project>
    python3 helpers/check_live_stage.py <project> --composition composition-v2
    python3 helpers/check_live_stage.py <project> --json

退出 0 = 没有 error（warning 不影响放行）；退出 1 = 至少一条 error；
退出 2 = 连 composition 都找不到（先修路径，不是契约问题）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 会被浏览器执行的 script type。没有 type 属性等价于 text/javascript。
EXECUTABLE_TYPES = {
    "", "text/javascript", "application/javascript", "application/ecmascript",
    "text/ecmascript", "module",
}
# 这些是数据块：编译器不会执行它们，也不该在这里找逻辑。
DATA_TYPES = {"application/json", "application/ld+json", "text/template",
              "text/x-template", "text/hf-after-fonts", "text/hf-after-fonts+module"}

SCRIPT_RE = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>",
                       re.S | re.I)
ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
ROOT_RE = re.compile(
    r"<(?P<tag>[a-zA-Z][\w:-]*)\b(?P<attrs>[^<>]*\bdata-composition-id\s*=\s*"
    r"(?:\"[^\"]*\"|'[^']*')[^<>]*)>", re.S)

# 内联脚本里一旦出现这些，就说明“本该执行的逻辑”被放在了会被改写的位置。
HF_BUILD_RE = re.compile(r"\bHF\.build\s*\(")
CFG_RE = re.compile(r"\b__CFG__\b")
TIMELINE_ASSIGN_RE = re.compile(
    r"__timelines\s*(?:\[\s*['\"][^'\"]+['\"]\s*\]|\.[A-Za-z_$][\w$]*)\s*=(?!=)")
# `hyperframes check` 的 lint 要求 index.html 里能看到一段 `window.__timelines` 初始化
# （缺失时报 missing_timeline_registry）。所以 index.html 允许留一行**只建容器**的内联
# 脚本；真正的 `window.__timelines["main"] = tl` 必须在外部文件里。下面这条判据把
# “建容器”和“注册时间轴”分开：右边是 null / undefined / {} / 自引用兜底，才算建容器。
CONTAINER_INIT_RHS = re.compile(
    r"^(?:null|undefined|\{\}|window\.__timelines(?:\.[A-Za-z_$][\w$]*|\[[^\]]+\])?"
    r"\s*\|\|\s*(?:null|undefined|\{\}))$")

# 注册名：支持 __timelines["main"] 与 __timelines.main 两种写法。
REGISTER_LITERAL = re.compile(
    r"__timelines\s*(?:\[\s*(['\"])(?P<bracket>[^'\"]+)\1\s*\]"
    r"|\.\s*(?P<dot>[A-Za-z_$][\w$]*))\s*=(?!=)")
REGISTER_DYNAMIC = re.compile(
    r"__timelines\s*\[\s*(?!['\"])(?P<expr>[^\]]+?)\s*\]\s*=(?!=)")

SKIP_DIRS = {"node_modules", ".git", ".hyperframes", "renders", ".cache"}
SKIP_JS = re.compile(r"(\.min\.js$|^gsap[^/]*\.js$|hyperframes[^/]*\.js$)")
MAX_JS_BYTES = 4_000_000
MEDIA_SUFFIXES = {".mp4", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".aac", ".png",
                  ".jpg", ".jpeg", ".webp"}
LIVE_STAGE_ASSET_MB = 4.0


class Report:
    def __init__(self, project: Path, comp: Path):
        self.project = project
        self.comp = comp
        self.checks: list[dict] = []

    def add(self, cid: str, ok: bool, detail: str, *, hint: str = "",
            level: str = "error") -> None:
        self.checks.append({"id": cid, "ok": ok, "detail": detail,
                            "hint": hint, "level": level})

    @property
    def errors(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"] and c["level"] == "error"]

    @property
    def warnings(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"] and c["level"] == "warning"]

    def as_dict(self) -> dict:
        return {
            "ok": not self.errors,
            "project": str(self.project),
            "composition": str(self.comp),
            "checks": self.checks,
            "errors": [c["detail"] for c in self.errors],
            "warnings": [c["detail"] for c in self.warnings],
        }


def _attrs(raw: str) -> dict:
    out = {}
    for match in ATTR_RE.finditer(raw):
        name = match.group(1).lower()
        value = match.group(2) if match.group(2) is not None else match.group(3)
        out[name] = value
    return out


def _is_local_src(src: str) -> bool:
    # A leading "/" is a route the preview server resolves; it is not a file we can
    # stat here, so it is neither verified nor reported missing.
    return bool(src) and not src.startswith(
        ("#", "/", "data:", "blob:", "http://", "https://", "mailto:", "javascript:"))


def resolve_composition(project: Path, explicit: str | None) -> tuple[Path, Path]:
    """(project_root, composition_dir). 接受项目根、edit/，或 composition 目录本身。"""
    p = Path(project).expanduser().resolve()
    if p.name in {"composition", "edit"} and (p.parent / "composition").is_dir():
        root = p.parent
    else:
        root = p
    if explicit:
        comp = Path(explicit)
        comp = (comp if comp.is_absolute() else root / comp).resolve()
    elif (root / "composition" / "index.html").is_file():
        comp = root / "composition"
    else:
        # 没有名为 composition 的目录时，给 recompose.json 记的那个目录一次机会。
        cfg = {}
        try:
            cfg = json.loads((root / "recompose.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
        named = str(cfg.get("composition") or "")
        cand = Path(named)
        if named and not cand.is_absolute():
            cand = root / named
        comp = cand.resolve() if named and (cand / "index.html").is_file() else root / "composition"
    return root, comp


def _inline_logic_hits(body: str) -> list[str]:
    """这段内联脚本里，哪些东西会被编译器改写成永不执行的数据块。"""
    hits: list[str] = []
    if HF_BUILD_RE.search(body):
        hits.append("HF.build()")
    if CFG_RE.search(body):
        hits.append("window.__CFG__")
    for match in TIMELINE_ASSIGN_RE.finditer(body):
        rhs = body[match.end():].split(";", 1)[0].splitlines()[0].strip().rstrip(";").strip()
        if not CONTAINER_INIT_RHS.match(rhs):
            hits.append("window.__timelines[...] =")
            break
    return hits


def _inline_scripts(html: str) -> list[dict]:
    out = []
    for match in SCRIPT_RE.finditer(html):
        attrs = _attrs(match.group("attrs"))
        if attrs.get("src"):
            continue
        kind = (attrs.get("type") or "").strip().lower()
        out.append({"type": kind, "body": match.group("body"),
                    "executable": kind in EXECUTABLE_TYPES})
    return out


def _root_ids(html: str) -> list[tuple[str, dict]]:
    found = []
    for match in ROOT_RE.finditer(html):
        attrs = _attrs(match.group("attrs"))
        found.append((attrs.get("data-composition-id", ""), attrs))
    return found


def _js_files(comp: Path) -> list[Path]:
    out = []
    for path in sorted(comp.rglob("*.js")):
        rel = path.relative_to(comp)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if SKIP_JS.search(rel.name):
            continue
        try:
            if path.stat().st_size > MAX_JS_BYTES:
                continue
        except OSError:
            continue
        out.append(path)
    return out


def _registered_names(comp: Path, html: str) -> tuple[dict[str, list[str]], list[str]]:
    """{name: [来源文件]} 与无法静态解析的表达式列表。"""
    names: dict[str, list[str]] = {}
    dynamic: list[str] = []

    def scan(text: str, where: str) -> None:
        for match in REGISTER_LITERAL.finditer(text):
            rhs = text[match.end():].split(";", 1)[0].splitlines()[0].strip().rstrip(";").strip()
            # 只建容器的赋值（= null / = ... || {}）不是注册：它满足 lint，
            # 却不会让 __timelines[<id>] 变成一个能 seek 的时间轴。
            if CONTAINER_INIT_RHS.match(rhs):
                continue
            name = match.group("bracket") or match.group("dot")
            names.setdefault(name, [])
            if where not in names[name]:
                names[name].append(where)
        for match in REGISTER_DYNAMIC.finditer(text):
            expr = match.group("expr").strip()
            # 自引用 / 明显不是注册的赋值不算（例如 x = __timelines[key] 的读侧不会被这条捕获）
            if expr and expr not in dynamic:
                dynamic.append(expr)

    for script in _inline_scripts(html):
        if script["executable"]:
            scan(script["body"], "index.html 内联脚本")
    for path in _js_files(comp):
        try:
            scan(path.read_text(encoding="utf-8", errors="replace"),
                 str(path.relative_to(comp)))
        except OSError:
            continue
    return names, dynamic


def inspect(project: Path, explicit: str | None = None) -> Report:
    root, comp = resolve_composition(Path(project), explicit)
    report = Report(root, comp)

    index = comp / "index.html"
    if not index.is_file():
        report.add("composition", False,
                   f"找不到 {index}：这个项目没有可上活舞台的 composition",
                   hint="用 --composition 指定目录；或在 recompose.json 里写对 composition 路径")
        return report
    html = index.read_text(encoding="utf-8", errors="replace")

    # 1) 根元素与画布事实
    roots = _root_ids(html)
    if not roots:
        report.add("composition-id", False,
                   "index.html 里没有带 data-composition-id 的根元素",
                   hint="根元素需要 data-composition-id / data-start / data-width / "
                        "data-height / data-duration 五个属性")
    elif len(roots) > 1:
        report.add("composition-id", False,
                   "有多个 data-composition-id 根元素："
                   + ", ".join(repr(r[0]) for r in roots)
                   + "；播放器只认一个，时间轴的归属会含糊")
    comp_id = roots[0][0] if roots else ""
    if roots:
        report.add("composition-id", bool(comp_id),
                   f"根 data-composition-id = {comp_id!r}")
        attrs = roots[0][1]
        width = attrs.get("data-width") or ""
        height = attrs.get("data-height") or ""
        duration = attrs.get("data-duration") or ""
        if width and height:
            report.add("canvas", True, f"画布 {width}×{height}")
        else:
            report.add("canvas", False, "根元素缺 data-width / data-height",
                       hint="活舞台按这两个值给 player 设视口；缺了会按 0 尺寸起",
                       level="warning")
        try:
            if float(duration) > 0:
                report.add("duration", True, f"标称时长 {float(duration):.3f}s")
            else:
                raise ValueError
        except (TypeError, ValueError):
            report.add("duration", False,
                       f"根元素 data-duration 不是正数：{duration!r}",
                       hint="标称时长缺失时，官方播放器拿不到可 seek 的区间；"
                            "真正的时长仍由时间轴决定", level="warning")

    # 2) 内联逻辑脚本
    inline = _inline_scripts(html)
    rewritten = [s for s in inline if s["type"] in {"text/hf-after-fonts",
                                                    "text/hf-after-fonts+module"}]
    dead = [s for s in rewritten if _inline_logic_hits(s["body"])]
    logic = []
    for script in inline:
        if not script["executable"]:
            continue
        hits = _inline_logic_hits(script["body"])
        if hits:
            logic.append(hits)
    if logic:
        labels = sorted({label for hits in logic for label in hits})
        report.add("inline-logic", False,
                   f"{len(logic)} 段内联 <script> 里放着本该执行的逻辑："
                   + "、".join(labels),
                   hint="把这些代码移到 src/*.js 外部文件，再在 index.html 里用 "
                        "<script src=\"src/...\"></script> 引用。预览编译器会把内联 "
                        "script 改写成 type=\"text/hf-after-fonts\"，审阅页的 srcdoc "
                        "没人替它重跑：时间轴不构建、播放器 0 秒、舞台全黑。")
    else:
        report.add("inline-logic", True, "没有会执行逻辑的内联 <script>")
    if dead:
        report.add("rewritten-inline", False,
                   f"{len(dead)} 段内联 <script> 已经被写成 type=\"text/hf-after-fonts\""
                   "（编译产物被存回了源文件）—— 它们永远不会执行",
                   hint="删掉这些数据块，把逻辑放进 src/*.js；不要保存编译后的 index.html")

    # lint 的静态要求：index.html 里必须能看到一段 window.__timelines 初始化。
    # 这不是活舞台的要求，但 `hyperframes check` 会因此报 error，所以提前说出来。
    if not any("window.__timelines" in s["body"] for s in inline):
        report.add("lint-registry-marker", False,
                   "index.html 里看不到 window.__timelines 初始化",
                   hint="hyperframes check 的 lint 会报 missing_timeline_registry。"
                        "在 index.html 末尾保留一行只建容器的内联脚本："
                        "<script>window.__timelines = window.__timelines || {};</script>"
                        "（真正的注册仍在 src/*.js 里；不要把 __timelines[\"main\"] = tl 内联）",
                   level="warning")

    # 3) 时间轴注册名
    names, dynamic = _registered_names(comp, html)
    if not names and not dynamic:
        report.add("timeline-registration", False,
                   "在 composition 的 JS 里找不到 window.__timelines[...] 注册",
                   hint="活舞台的 bridge 与官方 player 都按这个名字取时间轴；"
                        "没有它就是 0 秒")
    elif comp_id and comp_id not in names:
        report.add("timeline-registration", False,
                   f"注册名 {sorted(names)} 与根 data-composition-id "
                   f"{comp_id!r} 不一致",
                   hint=f"把注册改成 window.__timelines[{comp_id!r}] = tl；"
                        "名字不一致时不同路径拦得住的时机不一样，"
                        "build_review 出来的页面可能安静地演 0 秒")
    else:
        where = ", ".join(names.get(comp_id, []))
        report.add("timeline-registration", True,
                   f"时间轴注册名与 data-composition-id 一致：{comp_id!r}"
                   + (f"（{where}）" if where else ""))
    if dynamic:
        report.add("timeline-registration-dynamic", False,
                   "有无法静态解析的注册表达式：__timelines[" + "], __timelines[".join(dynamic) + "]",
                   hint="注册名写成变量时本检查无法核对；改成字面量，或在 "
                        "timeline 里断言 Object.keys(window.__timelines) === [data-composition-id]",
                   level="warning")

    # 4) 嵌入桥
    bridge = comp / "assets" / "composition-embed-bridge.js"
    if bridge.is_file():
        report.add("embed-bridge", True,
                   f"嵌入桥存在：{bridge.relative_to(root).as_posix() if root in bridge.parents else bridge}"
                   f"（{bridge.stat().st_size} bytes）")
    else:
        report.add("embed-bridge", False,
                   f"缺 {bridge.relative_to(root).as_posix() if root in bridge.parents else bridge}",
                   hint="按 visual/scripts/generate-composition.py 的 BRIDGE_FILE 约定，"
                        "它随 composition 一起走；审阅页只能通过它 drive 这份工程")
    refs_bridge = any(
        "composition-embed-bridge.js" in (a.get("src") or "")
        for a in (_attrs(m.group("attrs")) for m in SCRIPT_RE.finditer(html))
    )
    if bridge.is_file() and not refs_bridge:
        report.add("embed-bridge-ref", False,
                   "index.html 没有引用 assets/composition-embed-bridge.js",
                   hint="文件在但没引用，服务端的 composition 不会挂上控制面",
                   level="warning")

    # 5) 外部脚本必须真的存在（预览传输会逐个内联它们）
    missing = []
    for match in SCRIPT_RE.finditer(html):
        src = _attrs(match.group("attrs")).get("src") or ""
        if not _is_local_src(src):
            continue
        if "composition-embed-bridge.js" in src:
            continue
        target = (comp / src.split("?", 1)[0]).resolve()
        if target.is_relative_to(comp) and not target.is_file():
            missing.append(src)
        elif not target.is_relative_to(comp):
            missing.append(src + "（越出 composition）")
    if missing:
        report.add("external-scripts", False,
                   "引用了不存在的外部脚本：" + "、".join(missing[:6])
                   + ("…" if len(missing) > 6 else ""),
                   hint="live_preview 会逐个读到本地文件；缺一个，整份预览编译失败")
    else:
        report.add("external-scripts", True, "所有本地 <script src> 都读得到")

    # 6) 媒体预算（warning：build_review 会换成审阅副本，但换不动的会拖慢整页）
    big = []
    for path in sorted(comp.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in MEDIA_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(comp).parts):
            continue
        mb = path.stat().st_size / 1e6
        if mb > LIVE_STAGE_ASSET_MB:
            big.append((path.relative_to(comp).as_posix(), mb))
    if big:
        sample = "、".join(f"{rel} {mb:.1f}MB" for rel, mb in big[:4])
        report.add("media-budget", False,
                   f"{len(big)} 个 composition 内媒体超过活舞台单件预算 "
                   f"{LIVE_STAGE_ASSET_MB:.0f}MB：{sample}"
                   + ("…" if len(big) > 4 else ""),
                   hint="build_review 会压成 review/proxies/ 下的审阅副本；"
                        "压不进时会先降码率、再按比例降分辨率（见 review_copy.py）。"
                        "人物母版更适合走 review/media.json，不进 composition 资产表",
                   level="warning")
    else:
        report.add("media-budget", True,
                   f"composition 内媒体都在 {LIVE_STAGE_ASSET_MB:.0f}MB 单件预算内")

    return report


def print_report(report: Report) -> None:
    rel_comp = report.comp
    try:
        rel_comp = report.comp.relative_to(report.project)
    except ValueError:
        pass
    print(f"活舞台契约检查 · {report.project}")
    print(f"  composition = {rel_comp}")
    for check in report.checks:
        mark = "✓" if check["ok"] else ("!" if check["level"] == "warning" else "×")
        print(f"  {mark} {check['detail']}")
        if not check["ok"] and check.get("hint"):
            for line in str(check["hint"]).splitlines():
                print(f"      {line}")
    print()
    if report.errors:
        print(f"结论：FAIL —— {len(report.errors)} 个 error"
              + (f"，{len(report.warnings)} 个 warning" if report.warnings else ""))
        print("  这份 composition 不能进审阅页的活舞台；先按上面的提示改 src/，"
              "再重跑本检查。")
    else:
        print("结论：PASS —— 可以 build_review"
              + (f"（{len(report.warnings)} 个 warning 不拦路）" if report.warnings else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="静态断言 composition 是否符合审阅页活舞台的契约（不启动浏览器）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码：0 无 error；1 有 error；2 找不到 composition。")
    ap.add_argument("project", help="项目根（也可以是 edit/ 或 composition/）")
    ap.add_argument("--composition", default=None,
                    help="composition 目录（默认 composition/，其次 recompose.json 记录的目录）")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = ap.parse_args(argv)

    project = Path(args.project).expanduser()
    if not project.exists():
        print(f"✗ 项目不存在：{project}", file=sys.stderr)
        return 2
    _root, comp = resolve_composition(project, args.composition)
    if not (comp / "index.html").is_file():
        print(f"✗ 找不到 composition：{comp / 'index.html'}", file=sys.stderr)
        print("  用 --composition 指定目录，或在项目里建 composition/", file=sys.stderr)
        return 2
    report = inspect(project, args.composition)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main())

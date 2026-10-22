#!/usr/bin/env python3
"""build_review.py — 一键构建 Video Craft 统一视听审阅控制台与数据契约。

支持三种剪辑任务形态：
  1. composite (复合双通道)：人物口播 + 演示动画 + 底部单行字幕
  2. speaker_only (纯口播剪辑)：人物出镜裁切 + 逐字剪接面板 + 字幕核对
  3. animation_only (纯演示动画)：16:9 演示动画全屏舞台 + 导引配音/TTS + 逐幕动效检查

扫描项目资产（edl.json, timeline.json, subtitles.srt, SVG 场景图, 音视频底片），
编译出统一契约 <project>/review/review_data.json，并装配 <project>/review/index.html 与 review-surface.json。

用法：
    python3 helpers/build_review.py <project_dir_or_edit_dir> [--mode {auto,composite,speaker_only,animation_only}]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

from lib.planners_modules import resolve_module
from review_surface import write_surface, validate_surface
import review_copy
import review_slices
import recompose_plan

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "visual" / "scripts"))
from snapshot_input import resolve_snapshot  # noqa: E402


_FILE_DIGEST_CACHE: dict = {}


def snapshot_file(path: Path, root: Path) -> dict:
    stat = path.stat()
    item = {"path": path.relative_to(root).as_posix(), "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns}
    # Content identity for every file, media included: path+size+mtime is not an
    # identity (same-size, same-mtime replacement kept the manifest unchanged in
    # the v3 audit). Stream large media instead of reading it whole.
    key = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    cached = _FILE_DIGEST_CACHE.get(key)
    if cached is None:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        cached = digest.hexdigest()
        _FILE_DIGEST_CACHE[key] = cached
    item["sha256"] = cached
    return item


def find_scene_files(project_root: Path, edit_dir: Path) -> dict:
    dirs = [project_root / "visual_screens" / "_internal" / "02_svg_source",
            project_root / "composition" / "pages",
            project_root / "scenes", project_root / "deliverable" / "scenes",
            project_root / "input" / "scenes", edit_dir / "scenes", project_root / "previs"]
    pointer = project_root / ".pages"
    if pointer.is_file():
        pages = Path(pointer.read_text(encoding="utf-8").strip())
        pages = pages if pages.is_absolute() else project_root / pages
        dirs.insert(0, pages / "_internal" / "02_svg_source")
    files = {}
    for directory in dirs:
        for path in sorted(directory.glob("*.svg")):
            files.setdefault(path.stem, path.resolve())
    return files


def parse_srt(srt_text: str) -> list[dict]:
    """解析 SRT 字幕为结构化 cue 列表。统一实现见 `helpers/_timecode.py`（合并地图 M1）。"""
    from _timecode import flatten as _flatten, parse_srt_text as _parse_srt_text
    return [{
        "id": cue["index"],
        "start": round(cue["startMs"] / 1000, 3),
        "end": round(cue["endMs"] / 1000, 3),
        "startMs": cue["startMs"],
        "endMs": cue["endMs"],
        "text": _flatten(cue, " "),
    } for cue in _parse_srt_text(srt_text)]


def resolve_project_paths(target: Path) -> tuple[Path, Path]:
    """统一实现见 `helpers/_paths.py`（合并地图 M3）。"""
    from _paths import resolve
    return resolve(target)


def import_snapshot_scenes(project_root: Path) -> dict[str, dict] | None:
    """Import an external workbench snapshot into project-local review assets.

    A snapshot may live outside the video project.  The importer is still the
    authority for validating and copying its pinned assets; this helper only
    adapts the imported page for the review surface, whose asset bridge is
    rooted at the video project.
    """
    snapshot = resolve_snapshot(project_root)
    if not snapshot:
        return None

    # 遗留适配器只在"确实要导入旧快照"时加载：live 路径（recompose）不碰它，
    # 也不在模块导入期把它拉进 sys.modules。
    from import_svg_page import import_page, _inline_image_hrefs

    result = {}
    for key in snapshot.order:
        imported = import_page(
            key,
            page_dir=snapshot.root / "scenes",
            asset_root=snapshot.root,
            project=project_root,
        )
        # The composition importer first rewrites source hrefs to
        # assets/pages/<key>/..., then the review page needs a path relative to
        # review/index.html. Keep the second substitution so svgAssets can map
        # the exact href present in the inlined SVG to a project-local asset.
        rendered, review_substitutions = _inline_image_hrefs(
            imported.inlined,
            {entry["after"]: "../composition/" + entry["after"]
             for entry in imported.substitutions},
        )
        result[key] = {
            "svg": rendered,
            "assets": {
                entry["after"]: entry["after"].removeprefix("../")
                for entry in review_substitutions
            },
        }
    return result


def find_svg_scenes(project_root: Path, edit_dir: Path) -> dict[str, str]:
    """寻找并加载项目中所有的 SVG 场景。"""
    snapshot_scenes = import_snapshot_scenes(project_root)
    if snapshot_scenes is not None:
        return {key: value["svg"] for key, value in snapshot_scenes.items()}
    return {key: path.read_text(encoding="utf-8")
            for key, path in find_scene_files(project_root, edit_dir).items()}


REVIEW_MEDIA_NAME = "media.json"
DEFAULT_REVIEW_COPY_MB = 80.0

# Last-resort filename guesses. Kept only because projects predate media.json;
# every use is reported, because guessing is how a full-length 720p copy named
# `anim_preview.mp4` got picked as the "演示动画" track on the 图拉斯 project.
_MEDIA_GUESSES = {
    "speakerVideo": ["cut.mp4", "cut_subbed.mp4", "base_preview.mp4",
                     "成品/01_口播视频_剪辑成片.mp4", "preview.mp4"],
    "previewVideo": ["成品/03_演示动画.mp4", "screen_final.mp4", "anim_preview.mp4"],
    "compositeVideo": ["final.mp4", "screen_final.mp4", "preview.mp4"],
    "guideAudio": ["guide_audio.mp3", "guide_audio.mp3", "audio.wav",
                   "input/audio.mp3", "input/audio.wav"],
}


def _resolve_media_entry(entry, project_root: Path, edit_dir: Path) -> str | None:
    """Resolve one explicit media entry to a project-root-relative path."""
    if not entry:
        return None
    raw = Path(str(entry))
    for base in ((project_root, edit_dir) if not raw.is_absolute() else (Path("/"),)):
        cand = raw if raw.is_absolute() else (base / raw)
        if cand.is_file():
            return os.path.relpath(cand.resolve(), project_root)
    return None


LIVE_STAGE_STATE = "edit/_engineering/live-stage.json"


def _server_alive(url: str, timeout: float = 1.5) -> bool:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, OSError):
        return False


def _resolve_live_stage(project_root: Path, notes: list, *,
                        expected: bool = False) -> dict | None:
    """The live composition stage — the engineering state, played, with no render.

    `live_stage.py` already proved the address is the bare composition route (the
    studio's own 200-for-anything SPA makes a status code worthless). What is left
    to check here is that the server is **alive right now**: the state file very
    easily outlives the session that wrote it, and pointing the page at a dead
    address costs the author an iframe that never loads with no explanation.
    """
    state = project_root / LIVE_STAGE_STATE
    if not state.is_file():
        # 只有**本该有**活舞台的工程（有 composition）才值得为缺地址出声；
        # 没有 composition 的工程本来就走静态舞台/成片，那不是降级。
        if expected:
            notes.append(f"没有 {LIVE_STAGE_STATE} —— 拿不到活舞台地址，"
                         "这一次审的不是当前 composition。"
                         "要工程态审阅就先跑 helpers/live_stage.py <project>")
        return None
    try:
        doc = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        notes.append(f"{LIVE_STAGE_STATE} 读不出来 —— 这一次不进活舞台，"
                     "重跑 helpers/live_stage.py <project> 可重建")
        return None
    url, server = doc.get("stageUrl"), doc.get("serverUrl")
    if not (doc.get("ok") and url and server):
        notes.append(f"{LIVE_STAGE_STATE} 内容不完整（缺 ok/stageUrl/serverUrl）—— "
                     "这一次不进活舞台，重跑 helpers/live_stage.py <project> 可重建")
        return None
    if not _server_alive(server):
        notes.append(f"活舞台服务 {server} 现在没有响应（{LIVE_STAGE_STATE} 是上一次会话留下的）"
                     "—— 页面会退回静态舞台或合成成片。要看活的 composition，"
                     "先跑 helpers/live_stage.py <project>")
        return None
    return {"url": url, "serverUrl": server, "projectId": doc.get("projectId"),
            "compositionDir": doc.get("composition") or "composition"}


def resolve_review_media(project_root: Path, edit_dir: Path, *,
                         allow_review_copy: bool = True,
                         max_mb: float = DEFAULT_REVIEW_COPY_MB) -> tuple[dict, list[str]]:
    """Decide which media the console shows, and say how it decided.

    Explicit beats guessing: `review/media.json` names the files:
        {"compositeVideo": "edit/final.mp4", "speakerVideo": null, ...}
    Without it we fall back to filename candidates and report that we guessed.

    The composite then goes through the 审阅副本 rule: the review host transfers
    whole files, so a master bigger than `max_mb` is re-encoded once to a
    time-preserving, native-resolution copy and THAT is what the page loads.
    """
    # Normalise both roots first: on macOS a temp/project path can reach the same
    # directory through a symlink (/var vs /private/var), and relpath against the
    # unresolved form then yields "../../.." instead of a usable project path.
    project_root = Path(project_root).resolve()
    edit_dir = Path(edit_dir).resolve()
    notes: list[str] = []
    declared: dict = {}
    declared_at: Path | None = None
    for base in (project_root / "review", edit_dir / "review"):
        f = base / REVIEW_MEDIA_NAME
        if f.is_file():
            declared_at = f
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
                declared = payload if isinstance(payload, dict) else {}
            except json.JSONDecodeError:
                notes.append(f"{f.name} 解析失败，退回按文件名猜媒体")
            break

    media: dict[str, str | None] = {k: None for k in _MEDIA_GUESSES}
    media["transcriptSurface"] = None
    media["layersBaked"] = True

    # 活 composition：审阅时直接演工程态的源，不渲任何东西。入口由
    # helpers/live_stage.py 起服务时写进 edit/_engineering/live-stage.json；
    # 这里只验证它**现在还活着**——状态文件很容易是上一条会话留下的，
    # 指过去只会让页面挂一个连不上的 iframe。
    has_composition = (project_root / "composition" / "index.html").is_file()
    media["liveStage"] = _resolve_live_stage(project_root, notes, expected=has_composition)

    # 有 composition 却没有活舞台：降级本身可以接受，**无声**降级不行。
    # 实测踩到：预览服务没起时跑 build_review，界面照样生成、watch 清单从 19 条缩到 10 条，
    # 而且 review_data 里那一整段（含 player_bundle() 的内联）被跳过 —— 官方播放器根本没进页面，
    # 只有一条 mediaNote 记着。作者对着一个「看起来正常、审的不是当前合成」的页面提意见。
    if media["liveStage"] is None and has_composition:
        notes.append("**这一版审阅没有活舞台**：页面会退回静态舞台/成片，审的不是当前 "
                     "composition。要看工程态：先跑 helpers/live_stage.py <project>，再重建审阅。")
        print("  ! 这个工程有 composition，但没有活舞台 —— 这一版审的不是当前合成，"
              "先跑 helpers/live_stage.py 再重建（详见 review_data.json 的 mediaNotes）")

    if declared_at is not None and declared:
        for key in _MEDIA_GUESSES:
            resolved = _resolve_media_entry(declared.get(key), project_root, edit_dir)
            media[key] = resolved
            if declared.get(key) and resolved is None:
                notes.append(f"{declared_at.name} 声明了 {key}={declared[key]!r}，"
                             "但该文件不存在——这一轨将为空")
        # A declared base means "composite the layers live over the CUT". Playing a
        # film that already has the layers baked in while also stacking those layers
        # would double them, so the two modes are mutually exclusive and explicit.
        base = _resolve_media_entry(declared.get("baseVideo"), project_root, edit_dir)
        if base:
            media["compositeVideo"] = base
            media["layersBaked"] = False
            media["baseVideo"] = base
            notes.append("媒体用的是底片（未烘焙层）+ 页面实时叠层；"
                         "成片里的烘焙结果不在这一页上重复叠加")
    else:
        for key, names in _MEDIA_GUESSES.items():
            for name in names:
                cand = project_root / name
                if not cand.is_file():
                    cand = edit_dir / name
                if cand.is_file():
                    media[key] = os.path.relpath(cand.resolve(), project_root)
                    break
        if any(media[k] for k in ("speakerVideo", "previewVideo", "compositeVideo")):
            notes.append("没有 review/media.json，媒体是按文件名猜的；"
                         "写一份显式声明可避免猜错（例如把全长副本当成演示动画）")

    for cand in (edit_dir / "edl_preview.html", project_root / "edl_preview.html"):
        if cand.is_file():
            media["transcriptSurface"] = os.path.relpath(cand.resolve(), project_root)
            break

    # ---- 审阅副本 ----
    composite = media.get("compositeVideo")
    if allow_review_copy and composite:
        src = (project_root / composite).resolve()
        if review_copy.needs_copy(src, max_mb):
            out = src.with_suffix("").with_name(src.stem + ".review.mp4")
            fresh = out.is_file() and out.stat().st_mtime >= src.stat().st_mtime
            if fresh:
                media["compositeVideo"] = os.path.relpath(out.resolve(), project_root)
                notes.append(f"复合片用审阅副本 {out.name}"
                             f"（{out.stat().st_size / 1e6:.0f}MB，源 "
                             f"{src.stat().st_size / 1e6:.0f}MB）")
            else:
                print(f"    · 复合片 {src.name} 有 {src.stat().st_size / 1e6:.0f}MB，"
                      f"正在生成审阅副本（保留时间与原生分辨率）…", flush=True)
                record = review_copy.make(src, out, max_mb=max_mb)
                media["compositeVideo"] = os.path.relpath(Path(record["path"]),
                                                          project_root)
                notes.append(f"已生成审阅副本 {out.name}"
                             f"（{record['source_mb']}MB → {record['size_mb']}MB）")
    return media, notes


def review_build_id(project_root: Path, edit_dir: Path) -> str:
    """A short fingerprint of everything the review page shows.

    The page uses it to decide which feedback is still pending: a record carries the
    build it was written against, so once the surface is rebuilt the older ones are
    known to be about a version that no longer exists. Hashing (path, size, mtime) of
    the reviewed inputs is enough — the point is "did this change", not integrity.
    """
    import hashlib
    project_root = project_root.resolve()
    edit_dir = edit_dir.resolve()
    watched = [
        edit_dir / "edl.json",
        edit_dir / "captions.json",
        edit_dir / "timeline" / "timeline.json",
        edit_dir / "review" / "media.json",
        project_root / "review" / "media.json",
    ]
    try:
        edl = json.loads((edit_dir / "edl.json").read_text(encoding="utf-8"))
        for overlay in edl.get("overlays") or []:
            raw = str(overlay.get("file") or "")
            if raw:
                watched.append(Path(raw) if Path(raw).is_absolute() else edit_dir / raw)
    except Exception:                                          # noqa: BLE001
        pass
    try:
        media_file = edit_dir / "review" / "media.json"
        if media_file.is_file():
            for value in json.loads(media_file.read_text(encoding="utf-8")).values():
                if isinstance(value, str) and value:
                    watched.append(edit_dir / value)
    except Exception:                                          # noqa: BLE001
        pass

    parts: list[str] = []
    for path in watched:
        try:
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}")
        except OSError:
            continue
    parts.append(f"duration:{int((timeline_data_span(edit_dir)) * 1000)}")
    return hashlib.sha256("|".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]


def timeline_data_span(edit_dir: Path) -> float:
    path = edit_dir / "timeline" / "timeline.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        steps = [s for ch in data.get("chapters", []) for s in ch.get("steps", [])]
        if steps:
            return (steps[-1].get("endMs", 0) - steps[0].get("startMs", 0)) / 1000.0
    except Exception:                                          # noqa: BLE001
        pass
    return 0.0


def _overlay_layers(project_root: Path, edit_dir: Path, edl_data: dict | None) -> list[dict]:
    """The EDL's visual overlays, addressed as page-compositeable layers.

    Until now an overlay was only a *feedback anchor*: `build_review` gave it a
    `visual:<tag>` unitId so a comment could point at it, and the template never
    read it (grep for `overlayKind` in review-page-template.html: zero hits). The
    page showed one baked composite and nothing else.

    Emitting the file + window here is what lets the page composite the layer
    itself — the first half of "preview the animation without rendering the film".
    A layer whose file lives outside the project cannot be reached through the
    asset bridge and is marked so, rather than silently failing to load.
    """
    layers: list[dict] = []
    for index, overlay in enumerate((edl_data or {}).get("overlays") or []):
        raw = str(overlay.get("file") or "")
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = (edit_dir / path).resolve()
        tag = str(overlay.get("tag") or path.stem or f"overlay-{index + 1:02d}")
        try:
            rel = path.relative_to(project_root.resolve()).as_posix()
            inside = True
        except ValueError:
            rel, inside = raw, False
        # A browser cannot composite MOV/ProRes alpha at all, so a layer is only
        # previewable if the same source was also exported to WebM VP9 + alpha
        # (encode_transparent.py --codec webm). Point at that when it exists.
        sibling = path.with_suffix(".webm")
        preview_rel = None
        if sibling.is_file():
            try:
                preview_rel = sibling.relative_to(project_root.resolve()).as_posix()
            except ValueError:
                preview_rel = None
        start_ms = int(round(float(overlay.get("start_in_output",
                                                overlay.get("start", 0))) * 1000))
        duration_ms = int(round(float(overlay.get("duration", 0)) * 1000))
        layers.append({
            "unitId": f"visual:{tag}",
            "tag": tag,
            "file": rel,
            "inProject": inside,
            "startMs": start_ms,
            "endMs": start_ms + duration_ms,
            "durationMs": duration_ms,
            "kind": overlay.get("kind", "alpha"),
            "previewFile": preview_rel,
            "browserCompositable": preview_rel is not None,
        })
    return sorted(layers, key=lambda x: x["startMs"])


def build_density(project_root: Path, beats: list, captions: list) -> dict:
    """Recompose mode: one density row per caption line, grouped by beat.

    The page only shows the density drawer when this is enabled; page mode returns
    {"enabled": False} and the template keeps its current UI unchanged.
    """
    if not recompose_plan.enabled(project_root):
        return {"enabled": False, "mode": "page"}
    lines_doc = recompose_plan.read_json(project_root / recompose_plan.LINES_REL, {}) or {}
    lines = lines_doc.get("lines") or []
    source = lines_doc.get("source") or ""
    if not lines:
        return {"enabled": False, "mode": "recompose",
                "reason": "缺 recompose/lines.json；先跑 recompose_plan.py init"}
    by_beat = {}
    for line in lines:
        by_beat.setdefault(str(line.get("beatId") or ""), []).append({
            "id": line.get("id"),
            "startMs": int(line.get("startMs") or 0),
            "endMs": int(line.get("endMs") or 0),
            "text": str(line.get("text") or ""),
            "state": line.get("state") if line.get("state") in recompose_plan.STATES else "auto",
            "proposal": line.get("proposal") if line.get("proposal") in recompose_plan.RESOLVED else "still",
            "note": str(line.get("note") or ""),
        })
    out_beats = []
    for beat in beats:
        bid = str(beat.get("id") or "")
        rows = by_beat.get(bid) or []
        # timeline.json 的章节不携带 startMs / endMs（它们只在 steps 上），
        # 所以这里必须从 steps 推；直接读章级字段会让每个 beat 的区间恒为 0:00–0:00。
        steps = beat.get("steps") or []
        starts = [int(st.get("startMs") or 0) for st in steps]
        ends = [int(st.get("endMs") or 0) for st in steps]
        start_ms = beat.get("startMs")
        if start_ms is None:
            start_ms = min(starts) if starts else 0
        end_ms = beat.get("endMs")
        if end_ms is None:
            end_ms = max(ends) if ends else 0
        out_beats.append({
            "id": bid,
            "title": beat.get("title") or "",
            "startMs": int(start_ms),
            "endMs": int(end_ms),
            "lines": rows,
        })
    return {
        "enabled": True,
        "mode": "recompose",
        "source": source,
        "states": list(recompose_plan.STATES),
        "beats": out_beats,
        "lineCount": len(lines),
    }


def build_review_data(project_root: Path, edit_dir: Path, requested_mode: str = "auto",
                      *, allow_review_copy: bool = True,
                      slices: str = "auto") -> dict:
    """搜集、对齐并构造统一审阅数据契约。"""
    # 1. 查找 timeline.json
    timeline_paths = [
        project_root / "timeline" / "timeline.json",
        edit_dir / "timeline" / "timeline.json",
        edit_dir / "timeline.json",
        project_root / "timeline.json"
    ]
    timeline_data = None
    timeline_path = None
    for tp in timeline_paths:
        if tp.is_file():
            timeline_data = json.loads(tp.read_text(encoding="utf-8"))
            timeline_path = tp
            break

    # 2. 查找 edl.json
    edl_data = None
    edl_paths = [edit_dir / "edl.json", project_root / "edl.json"]
    for ep in edl_paths:
        if ep.is_file():
            try:
                edl_data = json.loads(ep.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    # 3. 查找 subtitles.srt
    captions = []
    srt_paths = [
        edit_dir / "subtitles.srt",
        project_root / "成品" / "02_字幕文件.srt",
        project_root / "subtitles.srt"
    ]
    for sp in srt_paths:
        if sp.is_file():
            try:
                captions = parse_srt(sp.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    # 如果没有 srt，查找 captions.json
    cap_json_paths = [edit_dir / "captions.json", project_root / "captions.json"]
    if not captions:
        for cjp in cap_json_paths:
            if cjp.is_file():
                try:
                    raw_cues = json.loads(cjp.read_text(encoding="utf-8"))
                    if isinstance(raw_cues, list):
                        for i, c in enumerate(raw_cues):
                            captions.append({
                                "id": c.get("id", i + 1),
                                "start": round(c.get("startMs", 0) / 1000.0, 3),
                                "end": round(c.get("endMs", 0) / 1000.0, 3),
                                "startMs": c.get("startMs", 0),
                                "endMs": c.get("endMs", 0),
                                "text": c.get("text", "")
                            })
                    break
                except Exception:
                    pass

    # 4. 查找 SVG 场景
    workbench_snapshot = resolve_snapshot(project_root)
    snapshot_scenes = import_snapshot_scenes(project_root) if workbench_snapshot else None
    svg_map = ({key: value["svg"] for key, value in snapshot_scenes.items()}
               if snapshot_scenes is not None else find_svg_scenes(project_root, edit_dir))

    # 5. 查找媒体文件
    review_dir = project_root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    media, media_notes = resolve_review_media(
        project_root, edit_dir, allow_review_copy=allow_review_copy)
    media["layers"] = _overlay_layers(project_root, edit_dir, edl_data)
    media["slices"] = None
    _step_list = [s for ch in (timeline_data or {}).get("chapters", [])
                  for s in ch.get("steps", [])]
    if media.get("compositeVideo") and _step_list:
        composite_path = (project_root / media["compositeVideo"]).resolve()
        want_slices = (slices == "on"
                       or (slices == "auto" and composite_path.is_file()
                           and composite_path.stat().st_size > 40_000_000))
        if want_slices:
            try:
                _manifest = review_slices.build_slices(
                    project_root, composite_rel=media["compositeVideo"],
                    steps=_step_list)
                media["slices"] = _manifest["slices"]
                media_notes.append(
                    f"已按步切片 {_manifest['sliceCount']} 个"
                    f"（最大关键帧提前量 "
                    f"{max(s['keyframeLeadMs'] for s in _manifest['slices'])}ms）"
                    "——页面只需加载当前窗口")
            except Exception as exc:                       # noqa: BLE001
                media_notes.append(f"按步切片失败，页面将整片加载：{exc}")

    # Which host should carry the review media. The sidebar bridge hands the whole
    # file over, so past a few hundred MB the honest answer is "not the sidebar".
    media["hostAdvice"] = None
    if media.get("compositeVideo"):
        _cpath = (project_root / media["compositeVideo"]).resolve()
        _size = _cpath.stat().st_size if _cpath.is_file() else 0
        if not media.get("slices") and _size > 200_000_000:
            media["hostAdvice"] = "local"
            media_notes.append(
                f"复合片 {_size / 1e6:.0f}MB 远超侧栏适合的范围，且没有按步切片"
                "——改用本地宿主起审阅（review_surface.py 不带 --surface-only），"
                "或让审阅副本/切片先生成")
    speaker_video_rel = media.get("speakerVideo")
    preview_video_rel = media.get("previewVideo")
    composite_video_rel = media.get("compositeVideo")
    transcript_rel = media.get("transcriptSurface")
    guide_audio_rel = media.get("guideAudio")
    for note in media_notes:
        print(f"    · {note}")

    # 6. 计算模式
    has_speaker = speaker_video_rel is not None or (edl_data and edl_data.get("ranges"))
    has_visual = bool(svg_map) or preview_video_rel is not None or (timeline_data and timeline_data.get("chapters"))

    if requested_mode in ("composite", "speaker_only", "animation_only"):
        final_mode = requested_mode
    else:
        if has_speaker and has_visual:
            final_mode = "composite"
        elif has_visual and not has_speaker:
            final_mode = "animation_only"
        else:
            final_mode = "speaker_only"

    # 7. 计算时长与章节结构
    total_duration_ms = 0
    if timeline_data and "totalDurationMs" in timeline_data:
        total_duration_ms = timeline_data["totalDurationMs"]
    elif captions:
        total_duration_ms = int(captions[-1]["end"] * 1000)
    elif edl_data and "ranges" in edl_data:
        total_duration_ms = int(sum((r.get("end", 0) - r.get("start", 0)) / r.get("speed", 1)
                                    for r in edl_data["ranges"]) * 1000)

    # 构造统一 beats 视图。`timeline.json` 是时间脊柱；视觉段的显示 id
    # 不能再按当前页面排序临时编号，否则一个 overlay 增删就会把反馈指到
    # 另一段。稳定 unitId 由来源 id 派生，页面和收件器都只使用它。
    beats = []
    if timeline_data and "chapters" in timeline_data:
        for ch in timeline_data["chapters"]:
            ch_steps = []
            for st in ch.get("steps", []):
                fallback_id = f"{ch.get('id')}-{st.get('step', 0)}"
                step_obj = {
                    "id": st.get("id", fallback_id),
                    "unitId": st.get("unitId") or (
                        f"visual:{st.get('sourcePageKey')}"
                        if st.get("sourcePageKey") else f"speech:{st.get('id', fallback_id)}"
                    ),
                    "bindingSource": "timeline",
                    "step": st.get("step", 0),
                    "startMs": st.get("startMs", 0),
                    "endMs": st.get("endMs", 0),
                    "durationMs": st.get("durationMs", st.get("endMs", 0) - st.get("startMs", 0)),
                    "caption": st.get("caption", ""),
                    "screenIntent": st.get("screenIntent", ""),
                    "visualModel": st.get("visualModel", ""),
                    "modelStructure": st.get("modelStructure", ""),
                    "onScreenTextRule": st.get("onScreenTextRule", ""),
                    "sourcePageKey": st.get("sourcePageKey", ch.get("id")),
                    "cueRange": st.get("cueRange", st.get("srtRange", [0, 0]))
                }
                ch_steps.append(step_obj)
            beats.append({
                "id": ch.get("id", "beat-0"),
                "title": ch.get("title", ch.get("id")),
                "steps": ch_steps
            })
    elif edl_data and "ranges" in edl_data:
        # 没有 timeline.json 时从 edl.json 合成基础 step
        cur_ms = 0
        edl_steps = []
        for i, r in enumerate(edl_data["ranges"]):
            dur_ms = int(round((r.get("end", 0) - r.get("start", 0)) / r.get("speed", 1) * 1000))
            edl_steps.append({
                "id": f"cut-{i+1:02d}",
                "unitId": f"speech:cut-{i+1:02d}",
                "bindingSource": "edl",
                "step": i + 1,
                "startMs": cur_ms,
                "endMs": cur_ms + dur_ms,
                "durationMs": dur_ms,
                "caption": r.get("quote", ""),
                "screenIntent": r.get("reason", "EDL 剪辑段落"),
                "visualModel": "口播实拍",
                "modelStructure": r.get("beat", ""),
                "onScreenTextRule": "",
                "sourcePageKey": None,
                "cueRange": [i, i + 1]
            })
            cur_ms += dur_ms
        beats.append({
            "id": "beat-edl",
            "title": "EDL 剪接决策序列",
            "steps": edl_steps
        })

    if not beats and captions:
        beats = [{"id": "captions", "title": "口播", "steps": [
            {"id": f"cue-{c['id']}", "step": i, "startMs": c["startMs"],
             "unitId": f"speech:cue-{c['id']}", "bindingSource": "captions",
             "endMs": c["endMs"], "durationMs": c["endMs"] - c["startMs"],
             "caption": c["text"], "cueRange": [i, i]} for i, c in enumerate(captions)]}]
    scene_assets = {}
    watched = []
    for path in [timeline_path, *edl_paths, *srt_paths, *cap_json_paths]:
        if path and path.is_file():
            watched.append(path)
    scene_files = find_scene_files(project_root, edit_dir) if not workbench_snapshot else {}
    if workbench_snapshot:
        # The source SVGs may be outside project_root.  Their identity and
        # provenance remain bound by workbenchSnapshot; only copied assets are
        # watched here because those are the bytes this review page serves.
        for key in workbench_snapshot.order:
            scene_assets[key] = dict(snapshot_scenes[key]["assets"])
            watched.extend(project_root / rel for rel in scene_assets[key].values())
    for key, path in scene_files.items():
        try:
            path.relative_to(project_root)
        except ValueError:
            raise ValueError(f"SVG 在审阅目录之外：{path}；先用 import_svg_page.py --emit 导入项目")
        watched.append(path)
        scene_assets[key] = {}
        tree = ET.fromstring(svg_map[key])
        for node in tree.iter():
            if node.tag.rsplit("}", 1)[-1] != "image":
                continue
            href = node.get("href") or node.get("{http://www.w3.org/1999/xlink}href") or ""
            if href.startswith(("data:", "#")):
                continue
            asset = (path.parent / href).resolve()
            try:
                rel = asset.relative_to(project_root).as_posix()
            except ValueError:
                raise ValueError(f"SVG 图片越出项目：{asset}；先导入图片资产")
            if not asset.is_file():
                raise ValueError(f"SVG 图片不存在：{asset}")
            scene_assets[key][href] = rel
            watched.append(asset)
    for rel in [speaker_video_rel, preview_video_rel, composite_video_rel, guide_audio_rel]:
        if rel:
            watched.append(project_root / rel)
    watched = sorted(set(watched))
    manifest = [snapshot_file(path, project_root) for path in watched]
    snapshot = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    # 将 EDL 覆盖层也挂回同一条时间脊柱。overlay 本身有自己的稳定 tag，
    # 同时记录它落在哪个口播段，供页面定位和 Agent 返修时核对上下文。
    cut_steps = [s for beat in beats for s in beat.get("steps", [])
                 if str(s.get("id", "")).startswith("cut-")]
    overlay_units = []
    for index, overlay in enumerate((edl_data or {}).get("overlays") or []):
        tag = str(overlay.get("tag") or Path(str(overlay.get("file", ""))).stem or f"overlay-{index + 1:02d}")
        start_ms = int(round(float(overlay.get("start_in_output", overlay.get("start", 0))) * 1000))
        duration_ms = int(round(float(overlay.get("duration", 0)) * 1000))
        end_ms = start_ms + duration_ms
        parent = next((s for s in cut_steps if int(s.get("startMs", 0)) <= start_ms < int(s.get("endMs", 0))), None)
        parent_chapter = next((b["id"] for b in beats if parent in b.get("steps", [])), None) if parent else None
        overlay_units.append({
            "unitId": f"visual:{tag}",
            "kind": "visual",
            "sourceId": tag,
            "startMs": start_ms,
            "endMs": end_ms,
            "parentUnitId": parent.get("unitId") if parent else None,
            "chapterId": parent_chapter,
            "file": overlay.get("file"),
            "overlayKind": overlay.get("kind", "alpha"),
        })
    binding_units = []
    for beat in beats:
        for step in beat.get("steps", []):
            binding_units.append({
                "unitId": step["unitId"], "kind": "speech" if step["unitId"].startswith("speech:") else "visual",
                "sourceId": step["id"], "startMs": step.get("startMs", 0), "endMs": step.get("endMs", 0),
                "chapterId": beat["id"], "parentUnitId": None,
            })
    # A visual page and its rendered overlay can describe the same stable unit.
    # Keep one binding record per unitId; merge the overlay transport facts into
    # the page record instead of creating two records with different chapters.
    by_unit = {item["unitId"]: item for item in binding_units}
    for overlay_unit in overlay_units:
        existing = by_unit.get(overlay_unit["unitId"])
        if existing is None:
            by_unit[overlay_unit["unitId"]] = overlay_unit
            continue
        for key in ("file", "overlayKind", "parentUnitId"):
            if overlay_unit.get(key) is not None:
                existing[key] = overlay_unit[key]
        existing["overlayChapterId"] = overlay_unit.get("chapterId")
    binding_units = list(by_unit.values())
    media_sizes = audit_media_sizes(project_root, media, scene_assets)
    review_data = {
        "version": "2.0.0",
        "project": project_root.name,
        "snapshot": snapshot,
        "binding": {"version": "video-craft-binding/1.0.0", "source": "timeline/timeline.json", "units": binding_units},
        "sourceManifest": manifest,
        "timelinePath": timeline_path.relative_to(project_root).as_posix() if timeline_path else None,
        "svgAssets": scene_assets,
        "mode": final_mode,
        "aspectRatio": "16:9",
        "totalDurationMs": total_duration_ms,
        "media": {
            "speakerVideo": speaker_video_rel,
            "previewVideo": preview_video_rel,
            "compositeVideo": composite_video_rel,
            # 活 composition 的入口（审阅页据此直接演工程态的源）。这份白名单是手写的，
            # 新字段不会自己进来 —— 加字段时这里和 resolve_review_media 要同时改。
            "liveStage": media.get("liveStage"),
            "transcriptSurface": (os.path.relpath(edit_dir / "edl_review_surface.json", project_root)
                                  if transcript_rel else None),
            "guideAudio": guide_audio_rel,
            "layers": media.get("layers") or [],
            "layersBaked": media.get("layersBaked", True),
            "slices": media.get("slices"),
            "hostAdvice": media.get("hostAdvice"),
            # What each channel actually costs the page to fetch. The review host
            # transfers whole files (it does not stream), so this is load time and
            # peak memory, not trivia — and it is the only place the page can see
            # it before it commits to downloading.
            "sizes": media_sizes,
        },
        "buildId": review_build_id(project_root, edit_dir),
        # How the media above was decided: explicit media.json, guessed filenames,
        # or an auto-generated 审阅副本. Surfaced so a wrong pick is visible on the
        # page instead of silently reviewed.
        "mediaNotes": media_notes,
        "timeline": timeline_data or {
            "source": "edl",
            "totalChapters": len(beats),
            "totalSteps": sum(len(b["steps"]) for b in beats),
            "totalDurationMs": total_duration_ms,
            "chapters": beats
        },
        "beats": beats,
        "captions": captions,
        "svgs": svg_map,
        "workbenchSnapshot": workbench_snapshot.binding() if workbench_snapshot else None,
        "edl": edl_data or {},
        "buildMode": ("recompose" if recompose_plan.enabled(project_root) else "page"),
        "density": build_density(project_root, beats, captions)
    }
    return review_data


def player_bundle():
    """Use the installed CLI's matching official player, inline for opaque hosts."""
    import hashlib
    import shutil
    executable = shutil.which("hyperframes")
    if not executable:
        raise ValueError("Live preview requires the installed HyperFrames CLI/player")
    package = Path(executable).resolve().parent.parent
    bundle = package / "dist/hyperframes-player.global.js"
    metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
    source = bundle.read_text(encoding="utf-8")
    if "hyperframes-player" not in source:
        raise ValueError("Invalid HyperFrames player bundle")
    return source, {"version": metadata["version"], "sha256": hashlib.sha256(source.encode()).hexdigest()}


# The live stage's asset budget. `review-page-template.html` turns every entry in
# `liveStage.composition.assets` into a base64 data URL inside the player's srcdoc
# (a parent's `blob:null` URL is unusable from the player's own opaque-origin
# iframe, so that conversion is forced). The map's TOTAL size — not the
# composition's — is therefore what the review page must chew through before
# `hyperframes-player` reports ready, against an 8-second watchdog.
#
# Measured 2026-10-15 on a 313s project: 19.0 MB of media became a 25.4 MB srcdoc,
# the watchdog fired, and the stage showed "预览暂时无法连接。请确认预览服务正在运行"
# while the page's data, bridge and sidebars all worked — the message blamed a
# service that was fine. Fitted with review copies the same project is 6.5 MB and
# loads. Anything over the per-asset budget becomes a review copy: same duration,
# same native pixels, higher CRF; audio sidecars drop to mono.
LIVE_STAGE_ASSET_MB = 4.0
# Ceiling for the whole map, so many small assets cannot add up to the same jam.
LIVE_STAGE_TOTAL_MB = 12.0
LIVE_STAGE_PROXY_DIR = "review/proxies"

# Above this, a media entry stops being a page asset and becomes a hazard. The
# review host hands whole files to the page: measured 1.19 GB (a talking-head
# master named as `speakerVideo`) would be read by the host process, transferred
# by structured clone and held as a Blob — three copies of 1.19 GB, unconditionally,
# because the page attaches that element on init regardless of which stage the
# reviewer is looking at. The visual review has no use for the master anyway.
MEDIA_WARN_MB = 200.0


def audit_media_sizes(project_root: Path, media: dict, scene_assets: dict) -> dict:
    """{rel: {mb, oversized}} for every file the review page will fetch.

    Every channel at once on purpose: the declared media, the per-screen SVG
    pictures and the alpha layers all travel the same unbounded path, and auditing
    them one at a time is how one of them ends up uncovered.
    """
    rels = [media.get(key) for key in
            ("speakerVideo", "previewVideo", "compositeVideo", "guideAudio")]
    # `svgAssets` is {page_key: {href: rel}} — two levels, so flatten one.
    for hrefs in (scene_assets or {}).values():
        if isinstance(hrefs, dict):
            rels += list(hrefs.values())
        else:
            rels.append(hrefs)
    rels += [layer.get("previewFile") for layer in (media.get("layers") or [])
             if isinstance(layer, dict)]
    sizes = {}
    for rel in rels:
        if not isinstance(rel, str) or not rel or rel in sizes:
            continue
        path = project_root / rel
        if not path.is_file():
            continue
        mb = path.stat().st_size / 1e6
        sizes[rel] = {"mb": round(mb, 1), "oversized": mb > MEDIA_WARN_MB}
    return sizes


MEDIA_TAG_RE = re.compile(r"<(video|audio)\b([^>]*)>", re.S | re.I)
ASSET_TOKEN_RE = re.compile(r"__VC_ASSET_\d+__")


def silent_asset_tokens(html: str) -> set[str]:
    """Tokens the composition plays muted, so a review copy may drop their audio.

    The transport rewrites media src to `__VC_ASSET_n__` tokens, so the compiled
    HTML is where "is this video muted?" is still visible. On the 2026-10-21 XHS
    master the person track carried its own copy of the narration (191 kbps,
    5.9MB) while the composition also had a separate `<audio>` element — the
    duplicate alone exceeded the 4MB live-stage budget. A token used by an
    `<audio>` element is never treated as silent.
    """
    silent: set[str] = set()
    audible: set[str] = set()
    for tag, attrs in MEDIA_TAG_RE.findall(html or ""):
        token = ASSET_TOKEN_RE.search(attrs)
        if not token:
            continue
        name = token.group(0)
        if tag.lower() == "audio":
            audible.add(name)
            continue
        has_audio = re.search(r"data-has-audio\s*=\s*[\"'](true|false)[\"']", attrs, re.I)
        if re.search(r"\bmuted\b", attrs, re.I) or (has_audio and has_audio.group(1).lower() == "false"):
            silent.add(name)
    return silent - audible


def fit_live_stage_assets(project_root: Path, review_data: dict) -> None:
    """Swap over-budget live-stage assets for review copies, in place.

    Mutates `liveStage.composition.assets`, appends to `mediaNotes`, and registers
    each proxy in `sourceManifest`. That last part is not bookkeeping: the review
    host serves what the surface watches, so a proxy that is not in the manifest
    is a 404 on the page even though the file sits right there — which turns a
    size problem into a "media unreadable" problem.
    """
    import review_copy

    live = review_data.get("media", {}).get("liveStage") or {}
    composition = live.get("composition") or {}
    assets = composition.get("assets") or {}
    if not assets:
        return
    notes = review_data.setdefault("mediaNotes", [])
    silent_tokens = silent_asset_tokens(composition.get("html") or "")
    project_root = project_root.resolve()
    proxy_dir = project_root / LIVE_STAGE_PROXY_DIR
    known = {item["path"] for item in review_data.get("sourceManifest", [])}
    budget_bytes = LIVE_STAGE_ASSET_MB * 1_000_000
    total = 0
    fittings = []

    for token, rel in list(assets.items()):
        src = project_root / rel
        if not src.is_file():
            continue
        if src.stat().st_size > budget_bytes:
            proxy_dir.mkdir(parents=True, exist_ok=True)
            out = proxy_dir / (src.stem + ".review" + src.suffix)
            # Reuse a fresh proxy: re-encoding an 11 MB screen track on every
            # rebuild would make iterating on the composition slower than the
            # render it exists to avoid.
            # mtime + size are not enough: a muxer timeout leaves a truncated
            # file that looks fresh forever, and the page then plays the film
            # with no sound and no error (2026-10-17, the author heard a silent
            # review). Decodability is the property that matters.
            src_duration = review_copy.media_duration(src) or 0.0
            record = None
            source_shape = review_copy.media_size(src)
            keep_audio = token not in silent_tokens
            # Best effort: if even the floor of the ladder cannot fit, the result
            # is still the smallest copy this tool can make. Without accepting it,
            # every rebuild would re-encode for minutes and still land over budget
            # (2026-10-21: 368s 720x1280 master → 4.9MB at 0.35x, 4MB budget).
            out_shape = review_copy.media_size(out) if out.is_file() else None
            floor = (review_copy.scaled_size(source_shape[0], source_shape[1],
                                             review_copy.DOWNSCALE_STEPS[-1])
                     if source_shape else None)
            best_effort = bool(out_shape and floor and out_shape == tuple(floor)
                               and (keep_audio or not review_copy.has_audio(out)))
            fresh = (out.is_file() and out.stat().st_mtime >= src.stat().st_mtime
                     and (out.stat().st_size <= budget_bytes or best_effort)
                     and review_copy.is_fresh_copy(out, src_duration))
            if out.is_file() and not fresh and out.stat().st_mtime >= src.stat().st_mtime:
                print(f"  ⚠ 审阅副本 {out.name} 已过期/不可读，重建")
            if not fresh:
                try:
                    # gop=None on purpose: nothing slices this copy, and forcing a
                    # keyframe per second took the same CRF 29 encode from 2.6 MB
                    # to 10.0 MB. `review_slices` output keeps the default gop.
                    # A composition-muted video does not need its audio: it is
                    # usually a duplicate of the narration already carried by an
                    # <audio> element, and at 191 kbps that duplicate alone fits
                    # no 4MB budget.
                    record = review_copy.make(src, out, max_mb=LIVE_STAGE_ASSET_MB,
                                              gop=None,
                                              keep_audio=keep_audio)
                except SystemExit as exc:
                    # A half-written copy must not survive: the next build would
                    # call it fresh by mtime and hand it over again.
                    out.unlink(missing_ok=True)
                    notes.append(f"活舞台资产 {rel} 压不进预算，保持原样：{exc}")
                    total += src.stat().st_size
                    continue
            if record is None or record.get("action") == "made":
                new_rel = out.resolve().relative_to(project_root).as_posix()
                assets[token] = new_rel
                src = out
                fittings.append((rel, new_rel, src.stat().st_size, record,
                                 source_shape))
                if new_rel not in known:
                    review_data["sourceManifest"].append(
                        snapshot_file(out, project_root))
                    known.add(new_rel)
        total += src.stat().st_size

    composition["assetBytes"] = total
    # The page scales its watchdog off this instead of a fixed 8s, which was only
    # ever right for a small map.
    live["budgetMs"] = int(25000 + max(0.0, total / 1e6 - 4.0) * 1500)

    if fittings:
        for old, new, size, record, source_shape in fittings:
            # `record` is None when a fresh proxy from an earlier build was reused;
            # in that case read the shape back off the file so the note still says
            # whether the picture was stepped down (the page shows these verbatim).
            if record and record.get("scaled"):
                out_shape = (record.get("width"), record.get("height"))
            else:
                out_shape = review_copy.media_size(project_root / new)
            was_scaled = bool(source_shape and out_shape
                              and tuple(out_shape) != tuple(source_shape))
            if was_scaled:
                note = (f"活舞台资产 {Path(old).name} → 审阅副本 "
                        f"{size / 1e6:.1f}MB（{new}，时长不变；原生 "
                        f"{source_shape[0]}×{source_shape[1]} → {out_shape[0]}×{out_shape[1]}，"
                        f"原生像素压不进 {LIVE_STAGE_ASSET_MB:.0f}MB 预算才降分辨率）")
            else:
                note = (f"活舞台资产 {Path(old).name} → 审阅副本 "
                        f"{size / 1e6:.1f}MB（{new}，时长与原生像素不变）")
            if record and record.get("audioDropped"):
                note += "；composition 里这条 video 是 muted，副本已去音轨"
            under = size <= LIVE_STAGE_ASSET_MB * 1_000_000
            if not under:
                note += (f"；⚠ 仍超 {LIVE_STAGE_ASSET_MB:.0f}MB 单件预算，页面仍会整份搬"
                         "（考虑 review_slices.py 只取当前窗口）")
            notes.append(note)
    if total > LIVE_STAGE_TOTAL_MB * 1_000_000:
        notes.append(f"活舞台资产合计仍有 {total / 1e6:.1f}MB > "
                     f"{LIVE_STAGE_TOTAL_MB:.0f}MB：审阅页首次加载会明显变慢，"
                     f"考虑减少同屏资产或先切片")


def write_review_files(project_root: Path, review_data: dict) -> tuple[Path, Path]:
    """生成 review/review_data.json 与 review/index.html。"""
    review_dir = project_root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    player_script = ""
    if review_data.get("media", {}).get("liveStage"):
        # Report capabilities where the compile actually happens; a font dump or a
        # missing libass shows up here first, and only this call site can see it.
        try:
            import probe_env
            for note in probe_env.build(project_root).get("notes", []):
                print(f"  ! [probe] {note}")
        except Exception:  # noqa: BLE001 - probe must never block review
            pass
        from live_preview import compile_preview
        live = review_data["media"]["liveStage"]
        live["composition"] = compile_preview(
            project_root, live["url"],
            composition_dir=project_root / live.get("compositionDir", "composition"))
        # Budget the map before it reaches the page: an over-budget map is an
        # 8-second watchdog expiry that reports itself as a dead preview service.
        fit_live_stage_assets(project_root, review_data)
        review_data["snapshot"] = hashlib.sha256((review_data["snapshot"] + live["composition"]["sourceHash"]).encode()).hexdigest()[:20]
        existing = {item["path"] for item in review_data["sourceManifest"]}
        for path in sorted((project_root / live.get("compositionDir", "composition")).rglob("*")):
            if path.is_file() and not any(part in {"node_modules", ".hyperframes", "renders", ".git"} for part in path.parts):
                rel = path.relative_to(project_root).as_posix()
                if rel not in existing and (path.suffix in {".html", ".js", ".css", ".json"} or rel in live["composition"]["assets"].values()):
                    review_data["sourceManifest"].append(snapshot_file(path, project_root))
        source, provenance = player_bundle()
        review_data["media"]["liveStage"]["player"] = provenance
        # An HTML parser ends script blocks even inside JavaScript string literals.
        source = source.replace("</script", "<\\/script")
        player_script = '<script id="hyperframes-player-runtime">' + source + '</script>\n'

    # 1. 写入 review_data.json
    data_path = review_dir / "review_data.json"
    data_path.write_text(json.dumps(review_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. 拷贝模板并注入 review/index.html
    skill_root = Path(__file__).resolve().parents[1]
    template_path = skill_root / "visual" / "assets" / "review-page-template.html"
    index_path = review_dir / "index.html"

    template_content = template_path.read_text(encoding="utf-8")
    core = resolve_module("planners-review-core")
    sys.path.insert(0, str(core / "scripts"))
    from inline_review_tokens import inline, check
    tokens = (core / "assets" / "dsh-tokens.css").read_text(encoding="utf-8")
    template_content, _ = inline(template_content, tokens)
    check(template_content, tokens)
    
    # 注入内联审阅数据（确保在 file:// 协议与审阅宿主下均能秒级加载，且保留 {{REVIEW_BRIDGE}} 独立行）
    inline_script = (
        "\n  <script id=\"inlined-review-data\">\n"
        f"    window.__REVIEW_DATA__ = {json.dumps(review_data, ensure_ascii=False).replace('<', chr(92) + 'u003c')};\n"
        "    window.__INLINE_SVGS__ = window.__REVIEW_DATA__.svgs || {};\n"
        "    window.__INLINE_TIMELINE__ = window.__REVIEW_DATA__.timeline || null;\n"
        "    window.__SPEAKER_VIDEO_URL__ = window.__REVIEW_DATA__.media?.speakerVideo || null;\n"
        "    window.__COMPOSITE_VIDEO_URL__ = window.__REVIEW_DATA__.media?.compositeVideo || null;\n"
        "  </script>\n"
    )
    if "</head>" in template_content:
        template_content = template_content.replace("</head>", f"{inline_script}{player_script}</head>", 1)

    index_path.write_text(template_content, encoding="utf-8")

    # 3. 确保 review-surface.json 存在
    write_surface(project_root)
    validate_surface(project_root)

    return data_path, index_path


def main():
    parser = argparse.ArgumentParser(description="一键构建 Video Craft 统一视听审阅控制台与数据契约")
    parser.add_argument("project", help="项目根目录或 edit 目录")
    parser.add_argument("--slices", choices=["auto", "on", "off"], default="auto",
                        help="按步切片供页面只加载当前窗口（auto=复合片超过 40MB 时）")
    parser.add_argument("--no-review-copy", action="store_true",
                        help="不要自动生成审阅副本（默认复合片超过 80MB 时生成）")
    parser.add_argument("--mode", choices=["auto", "composite", "speaker_only", "animation_only"],
                        default="auto", help="审阅模式（默认 auto 自动识别）")
    parser.add_argument("--allow-static", action="store_true",
                        help="允许在没有活舞台时仍构建（默认拒绝：有 composition 却审成片是流程错误）")
    parser.add_argument("--allow-page", action="store_true",
                        help="仅旧项目/测试：允许构建已退休的 page 十步审阅页")
    args = parser.parse_args()

    project_root, edit_dir = resolve_project_paths(Path(args.project))
    if not project_root.exists():
        print(f"Error: 找不到项目目录 {project_root}", file=sys.stderr)
        sys.exit(1)

    print(f"==> 正在分析项目: {project_root.name}")
    print(f"    - 项目根路径: {project_root}")
    print(f"    - 工作区路径: {edit_dir}")
    print(f"    - 请求模式: {args.mode}")

    data = build_review_data(project_root, edit_dir, args.mode,
                             allow_review_copy=not args.no_review_copy,
                             slices=args.slices)

    if data["buildMode"] == "page" and not args.allow_page:
        print("✗ 旧十步审阅页（page 模式）已退休。审阅页只保留 recompose 布局：", file=sys.stderr)
        print("  左侧大预览 + 横向 Beat + 右侧逐句调整/历史反馈。", file=sys.stderr)
        print(f"  先跑：python3 helpers/recompose_plan.py init {project_root}", file=sys.stderr)
        sys.exit(2)

    # 有 composition 却没有活舞台 = 审的不是当前合成。静默退回成片态是流程错误：
    # 作者会对着一个“看起来正常”的页面提意见。默认拒绝，只留显式降级。
    has_composition = (project_root / "composition" / "index.html").is_file()
    if has_composition and not data["media"].get("liveStage") and not args.allow_static:
        print("✗ 这个工程有 composition，但活舞台没有就绪——这一版审的不是工程态。", file=sys.stderr)
        print("  先跑：python3 helpers/review.py <项目>（或先 helpers/live_stage.py <项目> 再重建）", file=sys.stderr)
        print("  确实只要静态页/成片态时，显式加 --allow-static。", file=sys.stderr)
        sys.exit(2)

    data_path, index_path = write_review_files(project_root, data)

    print(f"✓ 审阅数据契约构建完成: {data_path}")
    print(f"    - 识别形态: {data['mode']}")
    print(f"    - 总时长: {round(data['totalDurationMs'] / 1000.0, 2)}s")
    print(f"    - 章节数: {len(data['beats'])} Beats")
    print(f"    - 字幕条数: {len(data['captions'])} 条")
    print(f"    - SVG 场景数: {len(data['svgs'])} 个")
    print(f"✓ 统一审阅控制台已就绪: {index_path}")
    print(f"    - 下一步: python3 helpers/review_surface.py \"{project_root}\" --surface-only；"
          "有 review_open 时传返回的 surface；无插件时去掉 --surface-only")


if __name__ == "__main__":
    main()

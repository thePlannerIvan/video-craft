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
import json
import os
import re
import shutil
import sys
from pathlib import Path


def parse_srt(srt_text: str) -> list[dict]:
    """解析 SRT 字幕为结构化 cue 列表。"""
    cues = []
    pattern = re.compile(
        r'(\d+)\s*\r?\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\r?\n(.*?)(?=\r?\n\r?\n|\Z)',
        re.DOTALL
    )
    def to_seconds(t_str: str) -> float:
        t_str = t_str.replace(',', '.')
        parts = t_str.split(':')
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

    for match in pattern.finditer(srt_text):
        idx = int(match.group(1))
        start_sec = to_seconds(match.group(2))
        end_sec = to_seconds(match.group(3))
        text = ' '.join(match.group(4).strip().splitlines())
        cues.append({
            "id": idx,
            "start": round(start_sec, 3),
            "end": round(end_sec, 3),
            "startMs": int(round(start_sec * 1000)),
            "endMs": int(round(end_sec * 1000)),
            "text": text
        })
    return cues


def resolve_project_paths(target: Path) -> tuple[Path, Path]:
    """根据传入路径识别 project_root 与 edit_dir。"""
    target = target.resolve()
    if target.name == "edit":
        project_root = target.parent
        edit_dir = target
    else:
        project_root = target
        edit_dir = project_root / "edit"
        if not edit_dir.exists() and (project_root / "edl.json").exists():
            edit_dir = project_root
    return project_root, edit_dir


def find_svg_scenes(project_root: Path, edit_dir: Path) -> dict[str, str]:
    """寻找并加载项目中所有的 SVG 场景。"""
    svg_map: dict[str, str] = {}
    search_dirs = [
        project_root / "visual_screens" / "_internal" / "02_svg_source",
        project_root / "scenes",
        project_root / "deliverable" / "scenes",
        project_root / "input" / "scenes",
        edit_dir / "scenes",
        project_root / "previs",
    ]
    
    # 检查 .pages 指针
    pages_pointer = project_root / ".pages"
    if pages_pointer.is_file():
        pointer_line = pages_pointer.read_text(encoding="utf-8").strip()
        if pointer_line:
            p_dir = Path(pointer_line)
            if not p_dir.is_absolute():
                p_dir = project_root / p_dir
            search_dirs.insert(0, p_dir / "visual_screens" / "_internal" / "02_svg_source")
            search_dirs.insert(0, p_dir / "scenes")

    for s_dir in search_dirs:
        if s_dir.is_dir():
            for svg_file in sorted(s_dir.glob("*.svg")):
                key = svg_file.stem
                if key not in svg_map:
                    try:
                        svg_map[key] = svg_file.read_text(encoding="utf-8")
                    except Exception:
                        pass
    return svg_map


def build_review_data(project_root: Path, edit_dir: Path, requested_mode: str = "auto") -> dict:
    """搜集、对齐并构造统一审阅数据契约。"""
    # 1. 查找 timeline.json
    timeline_paths = [
        edit_dir / "timeline" / "timeline.json",
        project_root / "timeline" / "timeline.json",
        edit_dir / "timeline.json",
        project_root / "timeline.json"
    ]
    timeline_data = None
    for tp in timeline_paths:
        if tp.is_file():
            try:
                timeline_data = json.loads(tp.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

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
    if not captions:
        cap_json_paths = [edit_dir / "captions.json", project_root / "captions.json"]
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
    svg_map = find_svg_scenes(project_root, edit_dir)

    # 5. 查找媒体文件
    review_dir = project_root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    # 候选口播视频
    speaker_candidates = [
        edit_dir / "cut.mp4",
        edit_dir / "cut_subbed.mp4",
        edit_dir / "base_preview.mp4",
        project_root / "成品" / "01_口播视频_剪辑成片.mp4",
        edit_dir / "preview.mp4"
    ]
    speaker_video_rel = None
    for cand in speaker_candidates:
        if cand.is_file():
            speaker_video_rel = os.path.relpath(cand, review_dir)
            break

    # 候选动画预览视频
    anim_candidates = [
        project_root / "成品" / "03_演示动画.mp4",
        edit_dir / "screen_final.mp4",
        edit_dir / "anim_preview.mp4"
    ]
    preview_video_rel = None
    for cand in anim_candidates:
        if cand.is_file():
            preview_video_rel = os.path.relpath(cand, review_dir)
            break

    # 候选导引配音
    audio_candidates = [
        project_root / "guide_audio.mp3",
        edit_dir / "guide_audio.mp3",
        edit_dir / "audio.wav"
    ]
    guide_audio_rel = None
    for cand in audio_candidates:
        if cand.is_file():
            guide_audio_rel = os.path.relpath(cand, review_dir)
            break

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
        total_duration_ms = int(sum((r.get("end", 0) - r.get("start", 0)) for r in edl_data["ranges"]) * 1000)

    # 构造统一 beats 视图
    beats = []
    if timeline_data and "chapters" in timeline_data:
        for ch in timeline_data["chapters"]:
            ch_steps = []
            for st in ch.get("steps", []):
                step_obj = {
                    "id": st.get("id", f"{ch.get('id')}-{st.get('step', 0)}"),
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
            dur_ms = int(round((r.get("end", 0) - r.get("start", 0)) * 1000))
            edl_steps.append({
                "id": f"cut-{i+1:02d}",
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

    review_data = {
        "version": "2.0.0",
        "project": project_root.name,
        "mode": final_mode,
        "aspectRatio": "16:9",
        "totalDurationMs": total_duration_ms,
        "media": {
            "speakerVideo": speaker_video_rel,
            "previewVideo": preview_video_rel,
            "guideAudio": guide_audio_rel
        },
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
        "edl": edl_data or {}
    }
    return review_data


def write_review_files(project_root: Path, review_data: dict) -> tuple[Path, Path]:
    """生成 review/review_data.json 与 review/index.html。"""
    review_dir = project_root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    # 1. 写入 review_data.json
    data_path = review_dir / "review_data.json"
    data_path.write_text(json.dumps(review_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. 拷贝模板并注入 review/index.html
    skill_root = Path(__file__).resolve().parents[1]
    template_path = skill_root / "visual" / "assets" / "review-page-template.html"
    index_path = review_dir / "index.html"

    template_content = template_path.read_text(encoding="utf-8")
    
    # 注入内联审阅数据（确保在 file:// 协议与审阅宿主下均能秒级加载，且保留 {{REVIEW_BRIDGE}} 独立行）
    inline_script = (
        "\n  <script id=\"inlined-review-data\">\n"
        f"    window.__REVIEW_DATA__ = {json.dumps(review_data, ensure_ascii=False)};\n"
        "    window.__INLINE_SVGS__ = window.__REVIEW_DATA__.svgs || {};\n"
        "    window.__INLINE_TIMELINE__ = window.__REVIEW_DATA__.timeline || null;\n"
        "    window.__SPEAKER_VIDEO_URL__ = window.__REVIEW_DATA__.media?.speakerVideo || null;\n"
        "  </script>\n"
    )
    if "</head>" in template_content:
        template_content = template_content.replace("</head>", f"{inline_script}</head>", 1)

    index_path.write_text(template_content, encoding="utf-8")

    # 3. 确保 review-surface.json 存在
    surface_path = review_dir / "review-surface.json"
    surface_doc = {
        "version": 1,
        "id": "video-craft/visual",
        "title": f"Video Craft · {project_root.name}",
        "dir": str(project_root),
        "entry": "review/index.html",
        "feedback": "review/review-submissions.json",
        "wake": {
            "text": "{unit} 有一条审阅意见；已追加至 feedback/*.jsonl。"
        },
        "watch": ["../timeline/timeline.json"],
        "capabilities": ["feedback", "timeline", "visual_preview"]
    }
    surface_path.write_text(json.dumps(surface_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    return data_path, index_path


def main():
    parser = argparse.ArgumentParser(description="一键构建 Video Craft 统一视听审阅控制台与数据契约")
    parser.add_argument("project", help="项目根目录或 edit 目录")
    parser.add_argument("--mode", choices=["auto", "composite", "speaker_only", "animation_only"],
                        default="auto", help="审阅模式（默认 auto 自动识别）")
    args = parser.parse_args()

    project_root, edit_dir = resolve_project_paths(Path(args.project))
    if not project_root.exists():
        print(f"Error: 找不到项目目录 {project_root}", file=sys.stderr)
        sys.exit(1)

    print(f"==> 正在分析项目: {project_root.name}")
    print(f"    - 项目根路径: {project_root}")
    print(f"    - 工作区路径: {edit_dir}")
    print(f"    - 请求模式: {args.mode}")

    data = build_review_data(project_root, edit_dir, args.mode)
    data_path, index_path = write_review_files(project_root, data)

    print(f"✓ 审阅数据契约构建完成: {data_path}")
    print(f"    - 识别形态: {data['mode']}")
    print(f"    - 总时长: {round(data['totalDurationMs'] / 1000.0, 2)}s")
    print(f"    - 章节数: {len(data['beats'])} Beats")
    print(f"    - 字幕条数: {len(data['captions'])} 条")
    print(f"    - SVG 场景数: {len(data['svgs'])} 个")
    print(f"✓ 统一审阅控制台已就绪: {index_path}")
    print(f"    - 下一步: 运行 `python3 helpers/serve_review.py {project_root} --open` 打开审阅")


if __name__ == "__main__":
    main()

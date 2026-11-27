#!/usr/bin/env python3
"""`交付` —— 画面层 + 人物 + 声音 + 字幕 → 默认分轨三件套（或显式合流成片）+ 核验报告。

默认分轨三件套（包含真人口播与画面层时）
------------------------------------------
1. `<片名>_人物成片.mp4`：无损流式复制高码率人物视频（优先 `edit/cut.mp4`）+ 立体声 AAC 音轨；
2. `<片名>_画面成片.mp4`：纯画面成片（无声景则 0 音轨，有声景附单独音效轨；含实机演示清晰文字拼合）；
3. `<片名>_字幕.srt`：经过剪映/PR 导入空隙保护（句间间隙 ≥30ms）的外挂字幕（源 `edit/subtitles.srt` 保持不动）。

无视觉层时仅输出人物成片 + 字幕；无人物轨（`--no-person`）输出全幅成片 + 字幕；
显式合流（`--composite` / `--mode composite` / `--burn-subtitles`）输出单轨视听成片 + 字幕。

接口
----
    python3 helpers/deliver.py <project> --render              # 默认分轨三件套交付
    python3 helpers/deliver.py <project> --visuals <mp4>       # 已有画面层，跳过渲染
    python3 helpers/deliver.py <project> --composite           # 显式合流输出单轨成片
    python3 helpers/deliver.py <project> --approve-in-chat --approval-note "..." # 作者对话明确授权导出后留档放行
    python3 helpers/deliver.py <project> --no-person           # 纯画面 + 旁白：画面层全幅交付
    python3 helpers/deliver.py <project> --json

前置：`render_gate.py` 必须放行（浏览器人工提交，或作者在对话中明确指示导出后 via `--approve-in-chat` 记录实时源码指纹放行）。
默认**不渲染**：缺画面层或画面层比 composition 旧时直接拒绝，要渲染必须显式 `--render`
（那是交付动作，不是审阅动作）。`--skip-gate` 只对测试进程（`DSH_TEST=1`）开放。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
INTERNAL = HELPERS / "_internal"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(INTERNAL))

BLACK_LUMA = 6.0          # 低于它视为全黑
BAND_LUMA = 24.0          # 字幕区里出现高于它的内容 → 会被字幕压住
_LEGACY_PAGE_SUFFIXES = {".md", ".svg", ".json"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_MOTION_KINDS = {"motion", "model", "card-deck", "xhs"}
_FOOTAGE_KINDS = {"footage", "video"}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _ffprobe(path: Path, *args: str) -> dict:
    proc = _run(["ffprobe", "-v", "error", "-print_format", "json", *args, str(path)])
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def _streams(path: Path) -> tuple[dict, dict]:
    info = _ffprobe(path, "-show_streams", "-show_format")
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    return video, audio


def _duration(path: Path) -> float:
    info = _ffprobe(path, "-show_format")
    try:
        return float(info.get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _frame_luma(path: Path, at: float, crop: tuple[int, int, int, int] | None = None) -> float | None:
    """取一帧，返回区域平均亮度（0–255）。crop=(w,h,x,y)。"""
    stats = _frame_luma_stats(path, at, crop)
    return stats[0] if stats is not None else None


def _frame_luma_stats(path: Path, at: float, crop: tuple[int, int, int, int] | None = None) -> tuple[float, int] | None:
    """取一帧，返回 (区域平均亮度, 峰值亮度 0–255)。crop=(w,h,x,y)。"""
    try:
        from PIL import Image
        import io
    except Exception:
        return None
    filter_arg = []
    if crop:
        w, h, x, y = crop
        filter_arg = ["-vf", f"crop={w}:{h}:{x}:{y}"]
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(path),
         *filter_arg, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    with Image.open(io.BytesIO(proc.stdout)) as im:
        grey = im.convert("L").resize((120, 68))
        data = list(grey.getdata())
    return (sum(data) / len(data)), int(max(data))


def _pick(project: Path, explicit: Path | None, candidates: list[Path]) -> Path | None:
    if explicit:
        return explicit if explicit.is_file() else None
    for item in candidates:
        if item.is_file():
            return item
    return None


def _render_env(composition: Path) -> tuple[bool, int, str]:
    """渲染环境判据：工具链坏了才拦，内存偏紧就降 worker 继续。

    `check_render_env.py` 对 8GB 机器要求 >= 4GB 可用内存，否则退 1。但 deliver 用的
    本来就是 `--workers 1`（它自己建议的安全值），只是机器上有别的进程时可用内存会长期
    低于门槛 —— 于是照文档「缺一不渲」会让人根本交不出片。所以：font/node/npx/composition
    这些真问题拦；只有 workers 一条红时按建议值渲染并记 note。
    """
    proc = _run([sys.executable, str(INTERNAL / "check_render_env.py"), str(composition), "--json"])
    try:
        data = json.loads((proc.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict) or type(data.get("ok")) is not bool or not data.get("workers"):
        return False, 1, "check_render_env 报告无效；修复环境探测后重试"
    workers = max(1, int(data.get("workers") or 1))
    if data.get('ok') is True and proc.returncode == 0:
        return True, workers, f"check_render_env 退 0（workers={workers}）"
    if data.get('ok') is True:
        return False, workers, f'check_render_env 退出 {proc.returncode}，报告与退出码矛盾'
    plain = _run([sys.executable, str(INTERNAL / "check_render_env.py"), str(composition)])
    lines = [ln.strip() for ln in (plain.stdout or "").splitlines() if ln.strip().startswith("x")]
    blocked = [ln for ln in lines if "workers:" not in ln]
    if blocked or not lines:
        return False, workers, "；".join(blocked[:2])
    mem = data.get("memory") or {}
    avail = mem.get("availableGb")
    return True, workers, (f"内存偏紧（可用 {avail} GB < 门槛），按建议 --workers {workers} 渲染")


def _has_legacy_pages(project: Path) -> bool:
    """Return True only when legacy pages/ or .pages actually contains page definitions."""
    pages_dir = project / "pages"
    if pages_dir.is_dir():
        for entry in pages_dir.rglob("*"):
            if entry.is_file() and not entry.name.startswith(".") and entry.suffix.lower() in _LEGACY_PAGE_SUFFIXES:
                return True
    dot_pages = project / ".pages"
    if dot_pages.is_file():
        return bool(dot_pages.read_text(encoding="utf-8", errors="ignore").strip())
    if dot_pages.is_dir():
        for entry in dot_pages.rglob("*"):
            if entry.is_file() and not entry.name.startswith(".") and entry.suffix.lower() in _LEGACY_PAGE_SUFFIXES:
                return True
    return False


def _find_storyboard(project: Path) -> Path | None:
    for cand in (project / "storyboard.json", project / "edit" / "storyboard.json"):
        if cand.is_file():
            return cand
    return None


def _preflight(project: Path, check, note) -> tuple[bool, int]:
    """Mechanical timing-lock checks, before any production encoder starts."""
    import probe_env
    env = probe_env.build(project)
    ffmpeg_ok = env.get("ffmpeg", {}).get("present") and bool(shutil.which("ffprobe"))
    if not check("编码能力", bool(ffmpeg_ok), "probe_env：需要 ffmpeg/ffprobe"):
        return False, 1
    sb_path = _find_storyboard(project)
    has_storyboard = sb_path is not None
    has_visual_plan = (project / "visual-plan.json").is_file()
    if has_storyboard or has_visual_plan:
        proc = _run([sys.executable, str(HELPERS / "film.py"), "verify", str(project), "--json"])
        label = "统一分镜" if has_storyboard else "视觉分拍表"
        if not check(label, proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]):
            return False, 1
    if has_storyboard and sb_path is not None and not _has_legacy_pages(project):
        try:
            sb_doc = json.loads(sb_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            sb_doc = {}
        shots = sb_doc.get("shots") or [] if isinstance(sb_doc, dict) else []
        caps = sb_doc.get("capabilities") or [] if isinstance(sb_doc, dict) else []
        has_motion_shot = "motion" in caps or any(
            isinstance(s, dict) and (
                s.get("kind") in ("motion", "model", "card-deck", "xhs")
                or s.get("engine") in ("remotion", "hyperframes")
            )
            for s in shots
        )
        if has_motion_shot:
            ld_proc = _run([sys.executable, str(HELPERS / "film.py"), "lookdev", str(project), "--verify", "--json"])
            if not check("Look-Dev 样镜定调", ld_proc.returncode == 0, (ld_proc.stdout + ld_proc.stderr)[-2000:]):
                return False, 1

    import remotion_stage
    motion_engine, rem_dir = remotion_stage.detect_motion_engine(project)
    if motion_engine == "remotion" and rem_dir is not None:
        import remotion_runtime
        rt = remotion_runtime.inspect_runtime()
        browser_bin, browser_source = remotion_runtime.resolve_browser_executable()
        rt_ok = bool(rt.get("ok")) or (
            browser_bin is not None
            and all(c.get("ok") for c in (rt.get("checks") or []) if c.get("name") != "headless_browser")
        )
        detail = (
            f"ready ({rt.get('runtimeHome')}, browser={browser_source})"
            if rt_ok
            else (rt.get("fixCommand") or f"not ready ({rt.get('runtimeHome')})")
        )
        if not check("Remotion 运行壳", rt_ok, detail):
            return False, 1
        for gate_only, label in (
            ("typecheck", "Remotion 类型检查"),
            ("sync", "Remotion 分镜对账"),
            ("stills", "Remotion 分镜静帧"),
        ):
            gproc = _run([sys.executable, str(INTERNAL / "remotion_gates.py"), str(project), "--only", gate_only, "--json"])
            gdetail = (gproc.stdout + gproc.stderr)[-2000:]
            try:
                gdoc = json.loads(gproc.stdout or "{}")
                if gdoc.get("errors"):
                    gdetail = "；".join(str(e) for e in gdoc["errors"][:3])
            except ValueError:
                pass
            if not check(label, gproc.returncode == 0, "ok" if gproc.returncode == 0 else gdetail):
                return False, 1
        if has_visual_plan or has_storyboard:
            qproc = _run([sys.executable, str(INTERNAL / "check_visual_quality.py"), str(project), "--json"])
            if not check("构建期画面体检", qproc.returncode == 0, (qproc.stdout + qproc.stderr)[-2000:]):
                return False, 1
        return True, 1

    composition = project / "composition"
    has_comp = (composition / "index.html").is_file()
    if not has_comp:
        if has_visual_plan or has_storyboard:
            qproc = _run([sys.executable, str(INTERNAL / "check_visual_quality.py"), str(project), "--json"])
            if not check("构建期画面体检", qproc.returncode == 0, (qproc.stdout + qproc.stderr)[-2000:]):
                return False, 1
        note("已有独立画面素材：没有 composition 源，不适用 film/动效检查；来源仍须经 render_gate")
        return True, 1
    env_ok, workers, detail = _render_env(composition)
    if not check("渲染环境", env_ok, detail):
        return False, workers
    if "内存偏紧" in detail:
        note(detail)
    from _paths import timeline_file
    timeline = timeline_file(project / "edit")
    data = json.loads(timeline.read_text(encoding="utf-8")) if timeline else {}
    references = any(s.get("sourcePageKey") for ch in data.get("chapters", []) for s in ch.get("steps", []))
    if not has_storyboard and not has_visual_plan and (references or _has_legacy_pages(project)):
        proc = _run([sys.executable, str(HELPERS / "film.py"), "verify", str(project), "--json"])
        if not check("原页拆解", proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]):
            return False, workers
    proc = _run(["hyperframes", "check", str(composition), "--json"])
    if not check("HyperFrames check", proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]):
        return False, workers
    qproc = _run([sys.executable, str(INTERNAL / "check_visual_quality.py"), str(project), "--json"])
    if not check("构建期画面体检", qproc.returncode == 0, (qproc.stdout + qproc.stderr)[-2000:]):
        return False, workers
    scripts = [composition / "index.html", *composition.rglob("*.js")]
    has_gsap = any("gsap" in p.read_text(encoding="utf-8", errors="ignore")
                   for p in scripts if not any(x in p.parts for x in ("node_modules", "_render", ".hyperframes")))
    if has_gsap:
        proc = _run([sys.executable, str(INTERNAL / "check_motion_targets.py"), str(project),
                     "--strict-transform", "--json"])
        if not check("动效目标", proc.returncode == 0 and "SKIP" not in proc.stdout,
                     (proc.stdout + proc.stderr)[-2000:]):
            return False, workers
    return True, workers


def _load_demo_segments(project: Path) -> list[dict]:
    plan_path = project / "visual-plan.json"
    if not plan_path.is_file():
        return []
    try:
        doc = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for idx, seg in enumerate(doc.get("segments") or []):
        if seg.get("tier") != "demo-footage":
            continue
        demo = seg.get("demo")
        if not isinstance(demo, dict) or not demo.get("source"):
            continue
        raw_src = Path(str(demo["source"])).expanduser()
        src = (raw_src if raw_src.is_absolute() else (project / raw_src)).resolve()
        if not src.is_file():
            continue
        t0 = float(seg.get("startMs", 0)) / 1000.0
        t1 = float(seg.get("endMs", 0)) / 1000.0
        in_sec = float(demo.get("inSec", 0.0))
        out_sec = float(demo.get("outSec", in_sec + max(0.05, t1 - t0)))
        speed = float(demo.get("speed", 1.0))
        if t1 <= t0 or out_sec <= in_sec or speed <= 0:
            continue
        box = None
        raw_box = demo.get("box")
        if isinstance(raw_box, dict) and all(k in raw_box for k in ("x", "y", "w", "h")):
            try:
                bx, by, bw, bh = int(raw_box["x"]), int(raw_box["y"]), int(raw_box["w"]), int(raw_box["h"])
                if bw >= 2 and bh >= 2:
                    box = {"x": bx, "y": by, "w": bw, "h": bh}
            except (TypeError, ValueError):
                box = None
        overlay = None
        if demo.get("overlay"):
            raw_ov = Path(str(demo["overlay"])).expanduser()
            ov_path = (raw_ov if raw_ov.is_absolute() else (project / raw_ov)).resolve()
            if ov_path.is_file():
                overlay = ov_path
        out.append({
            "id": str(seg.get("id") or f"demo-{idx + 1:02d}"),
            "source": src,
            "t0": t0,
            "t1": t1,
            "inSec": in_sec,
            "outSec": out_sec,
            "srcDur": out_sec - in_sec,
            "speed": speed,
            "box": box,
            "overlay": overlay,
        })
    return out


def _splice_demo_segments(project: Path, visual_path: Path, demo_segs: list[dict], geo: dict,
                          out: Path, name: str, person_path: Path | None,
                          vis_dur: float, *, visual_dest: Path | None = None,
                          emit_person_track: bool = False) -> tuple[Path, Path | None, dict]:
    """Splice HD demo recordings cleanly into video-only visual track with screen-text encoding."""
    fps = int(round(float(geo["fps"])))
    if person_path is None:
        default_box = {"x": 0, "y": 0, "w": int(geo["width"]), "h": int(geo["caption"]["y"])}
    else:
        default_box = geo["stage"]

    visual_track = visual_dest or (out / f"{name}_画面成片.mp4")
    visual_track.parent.mkdir(parents=True, exist_ok=True)
    inputs = ["-i", str(visual_path)]
    filters = [f"[0:v]fps={fps},format=yuv420p,setsar=1[v0]"]
    prev = "v0"
    next_input_idx = 1
    for k, seg in enumerate(demo_segs):
        tbox = seg.get("box") or default_box
        sx, sy = max(0, int(tbox["x"])), max(0, int(tbox["y"]))
        sw = max(2, int(tbox["w"]) - (int(tbox["w"]) % 2))
        sh = max(2, int(tbox["h"]) - (int(tbox["h"]) % 2))

        idx = next_input_idx
        next_input_idx += 1
        inputs.extend(["-ss", f"{seg['inSec']:.3f}", "-t", f"{seg['srcDur']:.3f}", "-i", str(seg["source"])])
        clip_out = max(0.05, seg["t1"] - seg["t0"])
        filters.append(
            f"[{idx}:v]fps={fps},"
            f"scale={sw}:{sh}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=#11131a,"
            f"setpts=(PTS-STARTPTS)/{seg['speed']:.6f},"
            f"trim=start=0:duration={clip_out:.3f},"
            f"setpts=PTS+({seg['t0']:.3f})/TB,setsar=1[demo_base{k}]"
        )
        demo_label = f"demo_base{k}"
        if seg.get("overlay"):
            ov_path: Path = seg["overlay"]
            ov_idx = next_input_idx
            next_input_idx += 1
            if ov_path.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"}:
                inputs.extend(["-loop", "1", "-t", f"{clip_out:.3f}", "-i", str(ov_path)])
            else:
                if ov_path.suffix.lower() == ".webm":
                    inputs.extend(["-c:v", "libvpx-vp9"])
                inputs.extend(["-t", f"{clip_out:.3f}", "-i", str(ov_path)])
            filters.append(
                f"[{ov_idx}:v]fps={fps},format=rgba,"
                f"scale={sw}:{sh}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
                f"setpts=PTS-STARTPTS+({seg['t0']:.3f})/TB,setsar=1[ov{k}]"
            )
            filters.append(f"[{demo_label}][ov{k}]overlay=0:0:eof_action=pass:repeatlast=0:format=auto[demo{k}]")
            demo_label = f"demo{k}"

        nxt = f"v{k + 1}"
        filters.append(
            f"[{prev}][{demo_label}]overlay={sx}:{sy}:"
            f"enable='between(t,{seg['t0']:.3f},{seg['t1']:.3f})':eof_action=pass:shortest=0[{nxt}]"
        )
        prev = nxt

    encoder_flags = ["-c:v", "libx264", "-preset", "medium", "-crf", "16",
                     "-x264-params", "deblock=-1,-1:aq-mode=2", "-pix_fmt", "yuv420p", "-r", str(fps)]
    with tempfile.NamedTemporaryFile(dir="/tmp", prefix="vc_visual_", suffix=".mp4", delete=False) as tf:
        tmp_visual = Path(tf.name)
    cmd = [
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", f"[{prev}]", "-an",
        *encoder_flags,
        "-t", f"{vis_dur:.3f}", "-movflags", "+faststart",
        str(tmp_visual),
    ]
    try:
        proc = _run(cmd)
        if proc.returncode != 0 or not tmp_visual.is_file() or tmp_visual.stat().st_size == 0:
            raise RuntimeError((proc.stderr or proc.stdout or "demo splice ffmpeg failed")[-400:])
        shutil.move(str(tmp_visual), str(visual_track))
    finally:
        if tmp_visual.exists():
            tmp_visual.unlink(missing_ok=True)

    person_track = None
    if emit_person_track and person_path is not None and person_path.is_file():
        slot = geo["person"]
        pw, ph = int(slot["w"]), int(slot["h"])
        person_track = out / f"{name}_人物轨.mp4"
        with tempfile.NamedTemporaryFile(dir="/tmp", prefix="vc_person_", suffix=".mp4", delete=False) as tfp:
            tmp_person = Path(tfp.name)
        p_cmd = [
            "ffmpeg", "-y", "-v", "error", "-i", str(person_path),
            "-vf", f"scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},setsar=1",
            "-map", "0:v", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
            "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{vis_dur:.3f}", "-movflags", "+faststart", str(tmp_person),
        ]
        try:
            p_proc = _run(p_cmd)
            if p_proc.returncode != 0 or not tmp_person.is_file() or tmp_person.stat().st_size == 0:
                raise RuntimeError((p_proc.stderr or p_proc.stdout or "person track export failed")[-400:])
            shutil.move(str(tmp_person), str(person_track))
        finally:
            if tmp_person.exists():
                tmp_person.unlink(missing_ok=True)

    info = {
        "count": len(demo_segs),
        "visual_track": str(visual_track),
        "person_track": str(person_track) if person_track else None,
        "screen_text_protection": True,
        "encoder_flags": "crf=16 deblock=-1,-1 aq-mode=2 flags=lanczos",
        "segments": [{"id": s["id"], "t0": s["t0"], "t1": s["t1"], "source": str(s["source"])}
                     for s in demo_segs],
    }
    return visual_track, person_track, info


def _load_storyboard(project: Path) -> tuple[Path | None, dict | None]:
    sb_path = _find_storyboard(project)
    if sb_path is None:
        return None, None
    try:
        doc = json.loads(sb_path.read_text(encoding="utf-8"))
        return (sb_path, doc) if isinstance(doc, dict) else (sb_path, None)
    except (OSError, json.JSONDecodeError):
        return sb_path, None


def _default_motion_engine(project: Path | None) -> str:
    if project is None:
        return "remotion"
    import remotion_stage
    eng, _ = remotion_stage.detect_motion_engine(project)
    return eng or "remotion"


def _shot_engine(shot: dict, default_motion_engine: str | None = None) -> str:
    raw = shot.get("engine")
    if raw in ("ffmpeg-cut", "remotion", "hyperframes"):
        return str(raw)
    motion_eng = default_motion_engine or "remotion"
    if shot.get("overlay") is True:
        return motion_eng
    return motion_eng if shot.get("kind") in _MOTION_KINDS else "ffmpeg-cut"


def _resolve_storyboard_asset(project: Path, sb_dir: Path, raw: str) -> Path:
    p = Path(str(raw)).expanduser()
    if p.is_absolute():
        return p.resolve()
    for base in (
        project,
        sb_dir,
        project / "material",
        project / "material" / "clips",
        project / "materials",
        project / "materials" / "clips",
        project / "素材",
        project / "素材" / "clips",
        project / "assets",
        project / "composition" / "assets",
    ):
        cand = (base / p).resolve()
        if cand.exists():
            return cand
    return (project / p).resolve()


def _find_shot_rendered_clip(project: Path, sb_dir: Path, shot: dict) -> Path | None:
    for key in ("renderedClip", "renderPath", "video", "clip"):
        raw = shot.get(key)
        if isinstance(raw, str) and raw.strip():
            cand = _resolve_storyboard_asset(project, sb_dir, raw.strip())
            if cand.is_file():
                return cand
    sid = str(shot.get("id") or "").strip()
    if sid:
        for base_dir in (project / "remotion" / "_render", project / "composition" / "_render"):
            cand = base_dir / f"{sid}.mp4"
            if cand.is_file():
                return cand
    return None


def _storyboard_needs_visual_base(project: Path, sb_path: Path, sb_doc: dict) -> bool:
    sb_dir = sb_path.parent
    default_motion = _default_motion_engine(project)
    for shot in sb_doc.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        if _shot_engine(shot, default_motion) in ("remotion", "hyperframes") and _find_shot_rendered_clip(project, sb_dir, shot) is None:
            return True
    return False


def _parse_box(raw_box: object, fallback: dict[str, int]) -> dict[str, int]:
    if isinstance(raw_box, dict) and all(k in raw_box for k in ("x", "y", "w", "h")):
        try:
            bx = max(0, int(raw_box["x"]))
            by = max(0, int(raw_box["y"]))
            bw = max(2, int(raw_box["w"]) - (int(raw_box["w"]) % 2))
            bh = max(2, int(raw_box["h"]) - (int(raw_box["h"]) % 2))
            return {"x": bx, "y": by, "w": bw, "h": bh}
        except (TypeError, ValueError):
            pass
    sx = max(0, int(fallback["x"]))
    sy = max(0, int(fallback["y"]))
    sw = max(2, int(fallback["w"]) - (int(fallback["w"]) % 2))
    sh = max(2, int(fallback["h"]) - (int(fallback["h"]) % 2))
    return {"x": sx, "y": sy, "w": sw, "h": sh}


def _storyboard_timeline_spans(
    sb_doc: dict,
    visual_dur: float,
    *,
    default_motion_engine: str | None = None,
) -> list[dict]:
    """Normalize storyboard shots into contiguous non-overlapping timeline spans."""
    shots = sorted(
        (s for s in (sb_doc.get("shots") or []) if isinstance(s, dict)),
        key=lambda s: float(s.get("startSec", 0.0)),
    )
    total_dur = max(
        float(sb_doc.get("totalSec") or 0.0),
        max((float(s.get("endSec", 0.0)) for s in shots), default=0.0),
        visual_dur,
    )
    spans: list[dict] = []
    cursor = 0.0
    gap_idx = 0
    for shot in shots:
        t0 = max(cursor, float(shot.get("startSec", 0.0)))
        t1 = float(shot.get("endSec", 0.0))
        if t1 <= t0:
            continue
        if t0 - cursor > 0.002:
            gap_idx += 1
            spans.append({"id": f"gap-{gap_idx:02d}", "kind": "talk-only", "engine": "ffmpeg-cut",
                          "t0": cursor, "t1": t0, "shot": {}})
        spans.append({"id": str(shot.get("id") or f"seg-{len(spans) + 1:02d}"),
                      "kind": str(shot.get("kind") or "talk-only"),
                      "engine": _shot_engine(shot, default_motion_engine), "t0": t0, "t1": t1, "shot": shot})
        cursor = t1
    if total_dur - cursor > 0.002:
        gap_idx += 1
        spans.append({"id": f"gap-{gap_idx:02d}", "kind": "talk-only", "engine": "ffmpeg-cut",
                      "t0": cursor, "t1": total_dur, "shot": {}})
    return spans


def _encode_storyboard_segment(project: Path, sb_dir: Path, span: dict, n_frames: int,
                               geo: dict, default_box: dict[str, int],
                               visual_path: Path | None, visual_dur: float,
                               base_img: Path | None, overlay_img: Path | None,
                               seg_out: Path) -> None:
    """Cut/render one timeline span to uniform H.264 segment MP4 for lossless concat."""
    fps = int(round(float(geo["fps"])))
    cw, ch = int(geo["width"]), int(geo["height"])
    shot = span["shot"]
    kind = span["kind"]
    engine = span["engine"]
    t0, t1 = span["t0"], span["t1"]
    seg_dur = t1 - t0

    enc_flags = [
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-x264-params", "deblock=-1,-1:aq-mode=2",
        "-pix_fmt", "yuv420p", "-r", str(fps), "-video_track_timescale", "90000",
    ]
    if kind == "screen-demo":
        enc_flags.extend(["-tune", "stillimage"])

    # Determine source + filter graph
    inputs: list[str] = []
    filters: list[str] = []

    if engine in ("remotion", "hyperframes"):
        per_shot = _find_shot_rendered_clip(project, sb_dir, shot)
        if per_shot is not None:
            src_in = float(shot.get("clipIn") or shot.get("inSec") or 0.0)
            inputs.extend(["-ss", f"{src_in:.3f}", "-i", str(per_shot)])
        elif visual_path is not None and visual_path.is_file():
            inputs.extend(["-ss", f"{t0:.3f}", "-i", str(visual_path)])
        else:
            raise RuntimeError(f"{span['id']} ({kind}) 缺少 {engine} 渲染画面")
        filters.append(
            f"[0:v]fps={fps},scale={cw}:{ch}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=#11131a,"
            f"tpad=stop_mode=clone:stop_duration=2,setsar=1[vout]"
        )
    elif kind in _FOOTAGE_KINDS or kind == "screen-demo":
        demo = shot.get("demo") if isinstance(shot.get("demo"), dict) else {}
        raw_src = demo.get("source") or shot.get("clip") or shot.get("material") or shot.get("source")
        if not isinstance(raw_src, str) or not raw_src.strip():
            raise RuntimeError(f"{span['id']} ({kind}) 缺少源素材路径")
        src = _resolve_storyboard_asset(project, sb_dir, raw_src.strip())
        if not src.is_file():
            raise RuntimeError(f"{span['id']} ({kind}) 找不到源素材：{src}")

        box = _parse_box(demo.get("box") or shot.get("box"), default_box)
        sx, sy, sw, sh = box["x"], box["y"], box["w"], box["h"]
        is_image = src.suffix.lower() in _IMAGE_SUFFIXES or shot.get("mediaKind") == "photo"
        speed = float(demo.get("speed") or shot.get("speed") or 1.0)
        if speed <= 0:
            speed = 1.0

        # Input 0: background canvas (base.png if present else #11131a)
        if base_img is not None:
            inputs.extend(["-loop", "1", "-t", f"{seg_dur + 1.0:.3f}", "-i", str(base_img)])
            filters.append(f"[0:v]fps={fps},scale={cw}:{ch},setsar=1[bg]")
        else:
            inputs.extend(["-f", "lavfi", "-i", f"color=c=0x11131a:s={cw}x{ch}:r={fps}:d={seg_dur + 1.0:.3f}"])
            filters.append("[0:v]setsar=1[bg]")

        # Input 1: HD footage / screen-demo / photo
        if is_image:
            inputs.extend(["-loop", "1", "-t", f"{seg_dur + 1.0:.3f}", "-i", str(src)])
            src_filter = (
                f"[1:v]fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=#11131a,setsar=1[fg0]"
            )
        else:
            raw_in = demo.get("inSec") if demo.get("inSec") is not None else (
                shot.get("clipIn") if shot.get("clipIn") is not None else shot.get("in", shot.get("inSec", 0.0))
            )
            in_sec = max(0.0, float(raw_in or 0.0))
            raw_out = demo.get("outSec") if demo.get("outSec") is not None else (
                shot.get("clipOut") if shot.get("clipOut") is not None else shot.get("out", shot.get("outSec"))
            )
            src_dur = max(0.05, float(raw_out) - in_sec) if raw_out is not None else max(0.05, seg_dur * speed)
            inputs.extend(["-ss", f"{in_sec:.3f}", "-t", f"{src_dur + 0.5:.3f}", "-i", str(src)])
            src_filter = (
                f"[1:v]fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=#11131a,"
                f"setpts=(PTS-STARTPTS)/{speed:.6f},"
                f"tpad=stop_mode=clone:stop_duration=2,setsar=1[fg0]"
            )
        filters.append(src_filter)
        fg_label = "fg0"
        next_idx = 2

        ov_raw = demo.get("overlay") or (shot.get("overlay") if isinstance(shot.get("overlay"), str) else None)
        if ov_raw:
            ov_path = _resolve_storyboard_asset(project, sb_dir, str(ov_raw))
            if ov_path.is_file():
                if ov_path.suffix.lower() in _IMAGE_SUFFIXES:
                    inputs.extend(["-loop", "1", "-t", f"{seg_dur + 1.0:.3f}", "-i", str(ov_path)])
                else:
                    if ov_path.suffix.lower() == ".webm":
                        inputs.extend(["-c:v", "libvpx-vp9"])
                    inputs.extend(["-t", f"{seg_dur + 1.0:.3f}", "-i", str(ov_path)])
                filters.append(
                    f"[{next_idx}:v]fps={fps},format=rgba,"
                    f"scale={sw}:{sh}:force_original_aspect_ratio=decrease:flags=lanczos,"
                    f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,setsar=1[ov0]"
                )
                filters.append(f"[{fg_label}][ov0]overlay=0:0:eof_action=pass:format=auto[fg1]")
                fg_label = "fg1"
                next_idx += 1

        filters.append(f"[bg][{fg_label}]overlay={sx}:{sy}:eof_action=pass[comp0]")
        out_label = "comp0"
        if overlay_img is not None:
            inputs.extend(["-loop", "1", "-t", f"{seg_dur + 1.0:.3f}", "-i", str(overlay_img)])
            filters.append(f"[{next_idx}:v]fps={fps},format=rgba,scale={cw}:{ch},setsar=1[fov]")
            filters.append(f"[{out_label}][fov]overlay=0:0:eof_action=pass:format=auto[vout]")
        else:
            filters.append(f"[{out_label}]null[vout]")
    else:
        # talk-only / gap
        if visual_path is not None and visual_path.is_file() and visual_dur >= t1 - 0.1:
            inputs.extend(["-ss", f"{t0:.3f}", "-i", str(visual_path)])
            filters.append(
                f"[0:v]fps={fps},scale={cw}:{ch}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=#11131a,"
                f"tpad=stop_mode=clone:stop_duration=2,setsar=1[vout]"
            )
        elif base_img is not None:
            inputs.extend(["-loop", "1", "-t", f"{seg_dur + 1.0:.3f}", "-i", str(base_img)])
            filters.append(f"[0:v]fps={fps},scale={cw}:{ch},setsar=1[vout]")
        else:
            inputs.extend(["-f", "lavfi", "-i", f"color=c=0x11131a:s={cw}x{ch}:r={fps}:d={seg_dur + 1.0:.3f}"])
            filters.append("[0:v]setsar=1[vout]")

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-an",
        "-frames:v", str(n_frames),
        *enc_flags,
        str(seg_out),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not seg_out.is_file() or seg_out.stat().st_size == 0:
        raise RuntimeError(f"分段 {span['id']} 编码失败：{(proc.stderr or proc.stdout)[-400:]}")


def _splice_storyboard_segments(project: Path, sb_path: Path, sb_doc: dict,
                                visual_path: Path | None, geo: dict,
                                out: Path, name: str, person_path: Path | None,
                                *, visual_dest: Path | None = None) -> tuple[Path, dict]:
    """Assemble visual track by routing ffmpeg-cut segments directly and splicing HyperFrames segments."""
    fps = int(round(float(geo["fps"])))
    cw, ch = int(geo["width"]), int(geo["height"])
    cap_y = int(geo["caption"]["y"]) if (int(geo["caption"]["h"]) > 0 and int(geo["caption"]["y"]) >= ch // 2) else ch
    full_stage_box = {"x": 0, "y": 0, "w": cw, "h": cap_y}
    if person_path is None:
        default_box = full_stage_box
    else:
        st = geo["stage"]
        default_box = st if (int(st.get("w", 0)) >= 2 and int(st.get("h", 0)) >= 2) else full_stage_box

    base_img = project / "material" / "frame" / "base.png"
    overlay_img = project / "material" / "frame" / "overlay.png"
    base_img = base_img if base_img.is_file() else None
    overlay_img = overlay_img if overlay_img.is_file() else None

    visual_dur = _duration(visual_path) if (visual_path is not None and visual_path.is_file()) else 0.0
    spans = _storyboard_timeline_spans(
        sb_doc,
        visual_dur,
        default_motion_engine=_default_motion_engine(project),
    )
    if not spans:
        raise RuntimeError("storyboard.json 没有可用片段")

    visual_track = visual_dest or (out / f"{name}_画面成片.mp4")
    visual_track.parent.mkdir(parents=True, exist_ok=True)
    sb_dir = sb_path.parent

    engine_counts = {"ffmpeg-cut": 0, "hyperframes": 0}
    has_screen_demo = any(sp["kind"] == "screen-demo" for sp in spans)
    seg_records: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="vc-sb-segs-", dir="/tmp") as td:
        td_path = Path(td)
        seg_files: list[Path] = []
        for idx, sp in enumerate(spans):
            f0 = int(round(sp["t0"] * fps))
            f1 = int(round(sp["t1"] * fps))
            n_frames = max(1, f1 - f0)
            seg_file = td_path / f"seg_{idx:03d}.mp4"
            _encode_storyboard_segment(
                project, sb_dir, sp, n_frames, geo, default_box,
                visual_path, visual_dur, base_img, overlay_img, seg_file,
            )
            seg_files.append(seg_file)
            engine_counts[sp["engine"]] = engine_counts.get(sp["engine"], 0) + 1
            seg_records.append({
                "id": sp["id"], "kind": sp["kind"], "engine": sp["engine"],
                "t0": round(sp["t0"], 3), "t1": round(sp["t1"], 3), "frames": n_frames,
            })

        list_file = td_path / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{str(p).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for p in seg_files) + "\n",
            encoding="utf-8",
        )
        tmp_out = td_path / "visual_assembled.mp4"
        concat_proc = _run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart", str(tmp_out),
        ])
        if concat_proc.returncode != 0 or not tmp_out.is_file() or tmp_out.stat().st_size == 0:
            raise RuntimeError(f"分段拼合失败：{(concat_proc.stderr or concat_proc.stdout)[-400:]}")
        shutil.move(str(tmp_out), str(visual_track))

    info = {
        "count": len(spans),
        "engine_counts": engine_counts,
        "screen_text_protection": has_screen_demo,
        "visual_track": str(visual_track),
        "total_frames": sum(r["frames"] for r in seg_records),
        "segments": seg_records,
    }
    return visual_track, info


def _export_soundscape_wav(src: Path, dest: Path) -> bool:
    """Co-export 48kHz stereo 16-bit PCM WAV via /tmp staging then atomic move."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _, a = _streams(src)
    is_pcm16_48k_stereo = (
        src.suffix.lower() == ".wav"
        and a.get("codec_name") == "pcm_s16le"
        and int(float(a.get("sample_rate") or 0)) == 48000
        and a.get("channels") == 2
    )
    with tempfile.TemporaryDirectory(prefix="vc-sd-wav-", dir="/tmp") as td:
        tmp_wav = Path(td) / dest.name
        if is_pcm16_48k_stereo:
            shutil.copy2(src, tmp_wav)
        else:
            proc = _run([
                "ffmpeg", "-y", "-v", "error", "-i", str(src),
                "-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(tmp_wav),
            ])
            if proc.returncode != 0 or not tmp_wav.is_file():
                return False
        shutil.move(str(tmp_wav), str(dest))
    return dest.is_file() and dest.stat().st_size > 0


def _render_is_stale(project: Path, visual: Path) -> bool:
    """Missing provenance is unproven, even when file timestamps look current."""
    from state_fingerprint import entry, source_entries
    try:
        proof = json.loads(visual.with_suffix(visual.suffix + '.sources.json').read_text(encoding='utf-8'))
        return not (proof.get('version') == 1 and proof.get('origin') in ('composition-render', 'manual-confirmation')
                    and proof.get('sources') == source_entries(project)
                    and proof.get('visual') == entry(visual))
    except (OSError, ValueError, TypeError):
        return True


def _record_visual_source(project: Path, visual: Path, origin: str, sources: dict | None = None) -> None:
    from state_fingerprint import entry, source_entries
    proof = {'version': 1, 'origin': origin, 'sources': source_entries(project) if sources is None else sources,
             'visual': entry(visual)}
    visual.with_suffix(visual.suffix + '.sources.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _parse_fps(video_stream: dict) -> float:
    raw = video_stream.get("r_frame_rate") or "0/1"
    try:
        num, den = str(raw).split("/", 1)
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _has_empty_capabilities(text: str) -> bool:
    """Return True if metadata declares `capabilities` with zero visual overlays (base-only)."""
    import re
    lines = text.splitlines()
    for idx, raw in enumerate(lines):
        m = re.match(r"^\s*capabilities\s*:\s*(.*)$", raw)
        if not m:
            continue
        rest = m.group(1).strip()
        if rest in ("[]", "none", "None", "~", "null"):
            return True
        if rest:
            return False
        # Block list: look ahead for `- <cap>` entries
        for follow in lines[idx + 1:]:
            s = follow.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("- "):
                return False
            if follow.startswith((" ", "\t")):
                continue
            break
        return True
    return False


def _is_pure_talking_project(project: Path) -> bool:
    """Detect base-only (no visual capabilities) or legacy pure-talking projects."""
    import re
    import remotion_stage
    has_visual_infra = (
        (project / "remotion").is_dir()
        or remotion_stage.detect_motion_engine(project)[0] == "remotion"
        or (project / "composition").is_dir()
        or (project / "recompose.json").is_file()
        or (project / "visual-plan.json").is_file()
        or _find_storyboard(project) is not None
        or _has_legacy_pages(project)
    )
    if has_visual_infra:
        return False
    for rel in ("project.yaml", "edit/project.md", "production-plan.md"):
        doc_path = project / rel
        if doc_path.is_file():
            text = doc_path.read_text(encoding="utf-8", errors="ignore")
            if _has_empty_capabilities(text) or re.search(r"\bpure-talking\b", text):
                return True
    return False


def _stage_ffmpeg_replace(cmd_prefix: list[str], dest: Path) -> subprocess.CompletedProcess:
    """Run ffmpeg into local /tmp (never cloud-synced target dirs) then move into dest on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="craft-deliver-") as td:
        tmp_path = Path(td) / f"{dest.stem}.tmp{dest.suffix or '.mp4'}"
        proc = _run([*cmd_prefix, str(tmp_path)])
        if proc.returncode == 0 and tmp_path.is_file():
            shutil.move(str(tmp_path), str(dest))
        return proc


def _check_caption_safe(visual_file: Path, dur_v: float, geo: dict, check) -> None:
    band = geo["caption"]
    crop = (int(band["w"]), int(band["h"]), int(band["x"]), int(band["y"]))
    if crop[0] <= 0 or crop[1] <= 0:
        check("字幕安全区无内容", True, "无字幕安全区")
        return
    intrusions = []
    for at in (dur_v * 0.25, dur_v * 0.5, dur_v * 0.75):
        luma = _frame_luma(visual_file, at, crop)
        if luma is not None and luma > BAND_LUMA:
            intrusions.append((round(at, 1), round(luma, 1)))
    check("字幕安全区无内容", not intrusions,
          "空" if not intrusions else f"这些时刻有内容会被字幕压住：{intrusions[:4]}")


def _check_non_black_frames(video_file: Path, dur: float, check) -> None:
    for label, at in (("首帧", 0.4), ("中帧", dur / 2), ("尾帧", max(0.0, dur - 0.6))):
        luma = _frame_luma(video_file, at)
        check(f"{label}非全黑", luma is None or luma >= BLACK_LUMA,
              f"mean_luma={None if luma is None else round(luma, 1)} @ {at:.1f}s")


def _stream_spec(path: Path) -> dict:
    v, a = _streams(path)
    return {
        "path": str(path),
        "duration_s": round(_duration(path), 3),
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": round(_parse_fps(v), 3) if v else None,
        "video_codec": v.get("codec_name"),
        "audio_codec": a.get("codec_name") if a else None,
        "audio_channels": a.get("channels") if a else None,
        "audio_sample_rate": int(float(a["sample_rate"])) if a and a.get("sample_rate") else None,
    }


def _check_visual_non_black(visual_file: Path, dur_v: float, geo: dict, check) -> None:
    """Check split visual track has non-empty drawn strokes/content (supports dark vector backdrops)."""
    stage = geo.get("stage") or {"x": 0, "y": 0, "w": int(geo["width"]), "h": int(geo["height"])}
    crop = (int(stage["w"]), int(stage["h"]), int(stage["x"]), int(stage["y"]))
    for label, at in (("画面中帧", dur_v / 2), ("画面尾帧", max(0.0, dur_v - 0.6))):
        stats = _frame_luma_stats(visual_file, at, crop)
        ok = stats is None or stats[1] >= 40 or stats[0] >= BLACK_LUMA
        detail = (
            "skipped" if stats is None
            else f"max_luma={stats[1]}, mean_luma={round(stats[0], 1)} @ {at:.1f}s"
        )
        check(f"{label}非全黑", ok, detail)


def _check_video_specs(path: Path, geo: dict, check, *, require_audio: bool,
                       silent_visual: bool = False) -> tuple[dict, dict, float]:
    v, a = _streams(path)
    check("分辨率", (v.get("width"), v.get("height")) == (geo["width"], geo["height"]),
          f"{v.get('width')}×{v.get('height')} 期望 {geo['width']}×{geo['height']}")
    fps = _parse_fps(v)
    check("帧率", abs(fps - geo["fps"]) < 0.01, f"{fps:.2f} 期望 {geo['fps']}")
    dur = _duration(path)
    if silent_visual:
        check("画面成片无音轨", bool(v) and not a,
              "0 音轨（纯画面）" if (v and not a) else f"异常音轨或无视频：{a}")
    elif require_audio:
        audio_ch = a.get("channels")
        check("成片有音轨", bool(a) and (audio_ch in (None, 2)),
              f"{a.get('codec_name', '无')} {audio_ch or ''}ch")
    return v, a, dur


def _subtitle_staging(srt_path: Path | None, burn: bool):
    if not burn or not (srt_path and srt_path.is_file()):
        return None, None
    td = tempfile.TemporaryDirectory(prefix="craft-subtitles-")
    staged_srt = Path(td.name) / "captions.srt"
    shutil.copyfile(srt_path, staged_srt)
    return td, f"subtitles=filename='{staged_srt.as_posix()}'"


def _mux_person_track(person_path: Path, audio_path: Path, dest: Path, max_dur: float, check,
                      *, srt_path: Path | None = None, burn: bool = False, fps: int = 30) -> bool:
    """Copy high-bitrate person video and mux stereo AAC audio capped to max_dur (burns SRT if requested)."""
    sub_tmp, sub_filter = _subtitle_staging(srt_path, burn)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(person_path), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0"]
    if sub_filter:
        cmd += ["-vf", sub_filter, "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(fps)]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
    if max_dur > 0:
        cmd += ["-t", f"{max_dur:.3f}"]
    try:
        proc = _stage_ffmpeg_replace(cmd, dest)
    finally:
        if sub_tmp is not None:
            sub_tmp.cleanup()
    return check("人物成片封装", proc.returncode == 0 and dest.is_file(),
                 (proc.stderr or "ok")[-300:] if proc.returncode != 0 else dest.name)


def _finalize_report(project: Path, edit_dir: Path, out: Path, name: str, report: dict, *,
                     delivery_mode: str, primary_video: Path, deliverables: dict,
                     spec_targets: dict[str, Path], inputs: dict[str, Path | None],
                     srt_out: Path, audio_path: Path, srt_path: Path | None,
                     as_json: bool, note, headline: str) -> int:
    """Run verify_delivery, record deliverable specs/identities, write JSON report, and emit summary."""
    report["composition_ok"] = all(c["ok"] for c in report["checks"])
    report["delivery_verdict"] = _delivery_verdict(edit_dir, primary_video, audio_path, srt_path)
    report["delivery_ok"] = report["delivery_verdict"]["ok"]
    note("交付核验（verify_delivery）：" + ("通过" if report["delivery_ok"] else
         "失败：" + "；".join(report["delivery_verdict"]["hard"][:3])))

    from state_fingerprint import source_entries, entry
    report["delivery_mode"] = delivery_mode
    report["deliverables"] = deliverables
    report["deliverable_specs"] = {k: _stream_spec(p) for k, p in spec_targets.items()}
    report["source_fingerprint"] = source_entries(project)
    report["output_identity"] = entry(primary_video)
    report["deliverable_identities"] = {
        k: entry(Path(v)) for k, v in deliverables.items() if v and Path(v).is_file()
    }
    report["input_identities"] = {key: entry(path) for key, path in inputs.items() if path}
    report["output"] = str(primary_video)
    report["subtitles"] = str(srt_out) if srt_out.is_file() else None
    report["ok"] = report["composition_ok"] and report["delivery_ok"]
    (out / f"{name}_核验报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["ok"]:
        from state_fingerprint import capture
        (out / "delivery.json").write_text(
            json.dumps(capture(project), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not as_json:
        print(f"\n{'✓' if report['ok'] else '✗'} {headline}")
        print(f"  核验报告：{out / f'{name}_核验报告.json'}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["ok"] else 1


def _needs_gap_fix(srt_path: Path, min_gap_ms: int = 30) -> bool:
    from _timecode import parse_srt_file
    cues = parse_srt_file(srt_path)
    return any(
        cues[i + 1]["startMs"] - cues[i]["endMs"] < min_gap_ms
        for i in range(len(cues) - 1)
    )


def _export_delivered_srt(srt_path: Path | None, srt_out: Path, edit_dir: Path,
                          project: Path, dur: float, burn: bool, check, note) -> int | None:
    """Export delivered SRT through import-gap protection while keeping source SRT untouched."""
    if not (srt_path and srt_path.is_file()):
        note("没有字幕源；如需字幕请 --srt")
        return None
    import export_deliverables
    if srt_path.resolve() != srt_out.resolve():
        fixed_count = export_deliverables.fix_srt_gaps(srt_path, srt_out)
    elif _needs_gap_fix(srt_out):
        fixed_count = export_deliverables.fix_srt_gaps(srt_path, srt_out)
    else:
        fixed_count = 0

    from _cutmap import (DURATION_TOLERANCE_S, compare_srt,
                         expected_film_duration_s, load as load_cut_map,
                         paths as cut_paths, validate as validate_cut_map,
                         verify_srt_pair)
    from _timecode import parse_srt_file

    cut_map, cut_problems = load_cut_map(edit_dir)
    if cut_map is not None:
        cut_problems += validate_cut_map(cut_map, project)

    src_cues = parse_srt_file(srt_path)
    out_cues = parse_srt_file(srt_out) if srt_out.is_file() else []
    overrun = bool(out_cues) and out_cues[-1]["endMs"] / 1000 > dur + 0.05

    gap_problems: list[str] = []
    if len(src_cues) != len(out_cues):
        gap_problems.append(f"交付字幕条数不一致：{len(src_cues)} -> {len(out_cues)}")
    else:
        for idx, (sc, oc) in enumerate(zip(src_cues, out_cues), start=1):
            st = "\n".join(sc.get("lines") or []).strip()
            ot = "\n".join(oc.get("lines") or []).strip()
            if st != ot:
                gap_problems.append(f"交付字幕第 {idx} 条文字被改动")
                break
            if abs(oc["startMs"] - sc["startMs"]) > 2 or oc["endMs"] <= oc["startMs"]:
                gap_problems.append(f"交付字幕第 {idx} 条起点或时长异常")
                break
        if not gap_problems:
            for idx in range(len(out_cues) - 1):
                if out_cues[idx + 1]["startMs"] - out_cues[idx]["startMs"] >= 40:
                    gap = out_cues[idx + 1]["startMs"] - out_cues[idx]["endMs"]
                    if gap < 30:
                        gap_problems.append(f"交付字幕第 {idx + 1} 条空隙 {gap}ms < 30ms")
                        break

    if cut_problems:
        check("字幕时间轴", False, "；".join(cut_problems[:2]))
    elif cut_map is not None:
        resolved = cut_paths(cut_map, project)
        pair = verify_srt_pair(resolved["srt_source"], srt_path, cut_map, film_duration_s=dur)
        expected = expected_film_duration_s(cut_map)
        same_film = expected is not None and abs(dur - expected) <= DURATION_TOLERANCE_S
        all_problems = list(pair) + gap_problems
        detail = (
            f"{srt_out.name} 是按 cut-map 复算并修正空隙的剪后字幕，成片 {dur:.3f}s 与 cut-map 一致"
            if not all_problems and same_film else
            "；".join((all_problems or [f"成片 {dur:.3f}s 与 cut-map 推算的 {expected:.3f}s 不一致"])[:2])
        )
        check("字幕时间轴", not all_problems and same_film, detail)
    else:
        master = edit_dir / "subtitles.srt"
        problems = compare_srt(srt_path, master) if master.is_file() else []
        problems = list(problems) + gap_problems
        detail = (
            "；".join(problems[:2]) if problems else
            (f"字幕末条 {out_cues[-1]['endMs'] / 1000:.3f}s 超出成片 {dur:.3f}s" if overrun else
             "与流水线字幕同一条时间轴（已做剪映/PR 安全空隙处理）")
        )
        check("字幕时间轴", not problems and not overrun, detail)
    check("字幕交付", True, f"外挂 {srt_out.name}（烧录={burn}，导入空隙修正 {fixed_count} 处）")
    return fixed_count


def _delivery_verdict(edit_dir: Path, target: Path, media: Path | None = None,
                      srt: Path | None = None) -> dict:
    """Keep strict criteria in verify_delivery; validate its transport contract."""
    result = {"ok": False, "status": "not-run", "hard": [],
              "owner": "verify_delivery.py", "next": "修复来源/时间依据后重新核验，不要 capture 指纹"}
    if not (edit_dir / "edl.json").is_file():
        from _paths import timeline_file
        timeline = timeline_file(edit_dir)
        doc = json.loads(timeline.read_text(encoding='utf-8')) if timeline else {}
        if doc.get('timeSource') != 'srt-import':
            result["hard"] = ["未完成严格核验：缺少 EDL 或 srt-import 时间轴；补选现有音频并导入外部字幕"]
            return result
    try:
        extra = (['--media', str(media)] if media else []) + (['--srt', str(srt)] if srt else [])
        proc = subprocess.run([sys.executable, str(INTERNAL / "verify_delivery.py"),
                               str(edit_dir), "--video", str(target), "--json", *extra],
                              capture_output=True, text=True)
        result.update(status="failed", code=proc.returncode)
        # The legacy verifier prints diagnostics before its final JSON object.
        decoder = json.JSONDecoder()
        payload = None
        output = proc.stdout or ""
        for start in range(len(output)):
            if output[start] != "{" or (start and output[start - 1] != "\n"):
                continue
            try:
                candidate, end = decoder.raw_decode(output[start:])
            except ValueError:
                continue
            if not output[start + end:].strip():
                payload = candidate
                break
        valid = (isinstance(payload, dict) and type(payload.get("ok")) is bool
                 and isinstance(payload.get("hard"), list)
                 and isinstance(payload.get("warn"), list)
                 and all(isinstance(x, str) for x in payload["hard"]))
        if not valid:
            result["hard"] = ["严格核验报告不可解析或缺少 ok/hard/warn 字段"]
        else:
            result["hard"] = payload["hard"]
            result["report"] = payload
            result["ok"] = proc.returncode == 0 and payload["ok"] and not payload["hard"]
            if not result["ok"] and not result["hard"]:
                result["hard"] = [f"严格核验未通过（exit={proc.returncode}, ok={payload['ok']}）"]
        if proc.stderr:
            result["stderr"] = proc.stderr[-2000:]
        if result["ok"]:
            result.update(status="passed", next="包装后核验交付副本，再 capture 新指纹")
    except (OSError, subprocess.SubprocessError) as exc:
        result.update(status="error", hard=[f"严格核验进程异常：{exc}"])
    return result


def deliver(project: Path, visuals: Path | None, person: Path | None, audio: Path | None,
            srt: Path | None, out_dir: Path | None, burn: bool, skip_gate: bool,
            as_json: bool, no_person: bool = False, render: bool = False,
            visuals_confirm_current: bool = False,
            mode: str = "split", composite: bool = False,
            approve_in_chat: bool = False,
            approval_note: str | None = None,
            visual_audio: Path | None = None) -> int:
    from _geometry import resolve_project_frame
    geo = resolve_project_frame(project)
    edit_dir = project / "edit"
    out = (out_dir or project / "成品")
    out.mkdir(parents=True, exist_ok=True)
    name = project.name
    report: dict = {"project": str(project), "geometry": geo, "checks": [], "notes": [],
                    "ok": False, "composition_ok": False, "delivery_ok": False,
                    "delivery_verdict": {"ok": False, "status": "not-run"}}

    def stop() -> int:
        (out / f"{name}_核验报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if as_json:
            print(json.dumps(report, ensure_ascii=False, indent=1))
        return 1

    def note(text: str) -> None:
        report["notes"].append(text)
        if not as_json:
            print(f"  · {text}")

    def check(name_: str, ok: bool, detail: str) -> bool:
        report["checks"].append({"name": name_, "ok": bool(ok), "detail": detail})
        if not as_json:
            print(f"{'✓' if ok else '✗'} {name_} — {detail}")
        return ok

    # 0) 时间轴来源：按当前剪辑指纹认渲染记录；认不出就标注，不静默
    try:
        from _edl import measured_total_ms as _measured_total
        _ms, _how, _tag = _measured_total(project / "edit", project / "edit" / "edl.json")
    except Exception:  # noqa: BLE001 - 报告要出，不能因探测失败卡住
        _ms, _how, _tag = None, "unavailable", None
    if _how == "no-digest":
        note(f"时间轴用的是推定渲染记录（{_tag}，无剪辑指纹）：字幕按同一策略对齐，画面时间点请复核")
    elif _how != "digest":
        note(f"时间轴按名义时长：没有与当前剪辑匹配的渲染记录（{_how}）；字幕优先，画面时间点可能偏移")

    # 0) 渲染闸门
    if not skip_gate:
        if approve_in_chat:
            import render_gate
            gate_report = render_gate.record_chat_approval(project, approval_note)
            if not gate_report.get("ok"):
                reasons = "；".join(gate_report.get("reasons") or ["渲染闸门拒绝放行"])
                check("渲染闸门", False, reasons)
                return stop()
            detail = "；".join(gate_report.get("notes") or []) or "会话授权覆盖当前快照（chat-approval 已留档）"
            check("渲染闸门", True, detail)
            note("渲染闸门已记录会话授权（chat-approval）")
        else:
            code, = (_run([sys.executable, str(INTERNAL / "render_gate.py"), str(project)]).returncode,)
            if code != 0:
                if not check("渲染闸门", False, "没有人审覆盖当前快照（先 review.py 交给人审；夹具用 --skip-gate）"):
                    return stop()
            else:
                check("渲染闸门", True, "有人审覆盖当前快照")

    try:
        preflight_ok, workers = _preflight(project, check, note)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        check("交付前置", False, f"{type(exc).__name__}: {exc}；修复对应工具/来源后再交付")
        return stop()
    if not preflight_ok:
        return stop()

    # 1) 三路素材（优先高码率 edit/cut.mp4）
    person_path = _pick(project, person, [
        project / "edit/cut.mp4",
        project / "composition/assets/person.mp4",
        project / "edit/_engineering/person_master.mp4",
        project / "edit/_engineering/cut.mp4",
    ])
    audio_path = _pick(project, audio, [project / "composition/assets/audio.m4a",
                                        project / "edit/_engineering/review_audio.m4a"])
    srt_path = _pick(project, srt, [project / "edit/subtitles.srt",
                                    project / "成品" / f"{name}_字幕.srt"])
    if visual_audio is not None:
        va_resolved = visual_audio.expanduser().resolve()
        if not check("画面声景", va_resolved.is_file(), str(va_resolved)):
            return stop()
        visual_audio_path: Path | None = va_resolved
    else:
        visual_audio_path = _pick(project, None, [
            project / "edit/_engineering/soundscape.wav",
            project / "edit/soundscape.wav",
        ])
    if burn:
        import probe_env
        if not check("烧录字幕能力", bool(srt_path) and probe_env.ffmpeg_capabilities()["filters"].get("subtitles", False),
                     "烧录需要有效 SRT 和 libass subtitles 滤镜；不支持时可显式改用默认外挂"):
            return stop()
    if no_person:
        if person_path is not None:
            note(f"声明无人物轨：忽略 {person_path.name}，画面层全幅交付")
        person_path = None
    elif not check("人物素材", person_path is not None,
                   str(person_path or "缺（用 --person 指；纯画面 + 旁白的片子加 --no-person）")):
        return stop()
    if not check("声音素材", audio_path is not None, str(audio_path or "缺（用 --audio 指）")):
        return stop()
    from _paths import timeline_file
    try:
        current_timeline = timeline_file(edit_dir)
        time_doc = json.loads(current_timeline.read_text(encoding='utf-8')) if current_timeline else {}
        if time_doc.get('timeSource') == 'srt-import':
            from import_srt_timeline import source_problems
            problems = source_problems(project, time_doc, media=audio_path, srt=srt_path)
            if not check('外部音频与字幕来源', not problems, '；'.join(problems) if problems else '当前媒体、字幕、alignment 与 timeline 一致'):
                return stop()
    except (OSError, ValueError, TypeError) as exc:
        check('当前时间依据', False, str(exc))
        return stop()

    pure_talking = (
        not no_person
        and person_path is not None
        and visuals is None
        and not render
        and _is_pure_talking_project(project)
    )
    if no_person:
        effective_mode = "no-person"
    elif pure_talking:
        effective_mode = "pure-talking"
    elif composite or mode == "composite" or burn:
        if burn and not (composite or mode == "composite"):
            note("烧录字幕（--burn-subtitles）需要单轨成片：自动切换为合流输出")
        effective_mode = "composite"
    else:
        effective_mode = "split"

    srt_out = out / f"{name}_字幕.srt"

    if effective_mode == "pure-talking":
        note("无视觉层交付：不拆分空画面轨，仅交付人物成片与字幕")
        person_out = out / f"{name}_人物成片.mp4"
        expected_dur = (_ms / 1000.0) if (_ms and _ms > 0) else _duration(audio_path)
        if not _mux_person_track(person_path, audio_path, person_out, expected_dur, check,
                                  srt_path=srt_path, burn=burn, fps=geo["fps"]):
            return stop()
        pv, pa = _streams(person_out)
        if not check("人物成片可读", bool(pv), f"{pv.get('width')}×{pv.get('height')}"):
            return stop()
        dur_p = _duration(person_out)
        if expected_dur > 0:
            check("时长", abs(dur_p - expected_dur) <= 0.5, f"{dur_p:.2f}s（音频/时间轴 {expected_dur:.2f}s）")
        audio_ch = pa.get("channels")
        check("成片有音轨", bool(pa) and (audio_ch in (None, 2)),
              f"{pa.get('codec_name', '无')} {audio_ch or ''}ch")
        _check_non_black_frames(person_out, dur_p, check)
        _export_delivered_srt(srt_path, srt_out, edit_dir, project, dur_p, burn, check, note)
        return _finalize_report(
            project, edit_dir, out, name, report,
            delivery_mode="pure-talking",
            primary_video=person_out,
            deliverables={"person": str(person_out), "subtitles": str(srt_out) if srt_out.is_file() else None},
            spec_targets={"person": person_out},
            inputs={"audio": audio_path, "person": person_path, "srt": srt_path},
            srt_out=srt_out, audio_path=audio_path, srt_path=srt_path,
            as_json=as_json, note=note, headline=f"人物成片：{person_out}",
        )

    # 2) 画面层：已有就用，没有就渲（storyboard.json 若无待渲动效段且无底片时可直拼）
    import remotion_stage
    motion_engine, remotion_dir = remotion_stage.detect_motion_engine(project)
    sb_path, sb_doc = _load_storyboard(project)
    needs_visual_base = (
        sb_doc is None
        or sb_path is None
        or _storyboard_needs_visual_base(project, sb_path, sb_doc)
    )
    visual_candidates: list[Path] = []
    if motion_engine == "remotion" and remotion_dir is not None:
        visual_candidates.append(remotion_dir / "_render" / "visuals.mp4")
    else:
        visual_candidates.append(project / "remotion/_render/visuals.mp4")
    visual_candidates.append(project / "composition/_render/visuals.mp4")
    visual_path = _pick(project, visuals, visual_candidates)
    if visual_path is not None and visuals_confirm_current:
        _record_visual_source(project, visual_path, 'manual-confirmation')
        note('执行者明确确认现有画面层属于当前来源；已记录人工确认及文件内容身份')
    if visual_path is not None and _render_is_stale(project, visual_path):
        if not render:
            detail = (f"{visual_path.name} 来源缺记录或已过期。重渲用 --render；"
                      "旧缓存/外部画面经人工核对属于当前版后，用 --visuals-confirm-current 补记一次来源")
            check("画面层", False, detail)
            report["ok"] = False
            return stop()
        note(f"画面层比工程源旧（{visual_path.name}），按 --render 重新渲染")
        visual_path = None
    if visual_path is None and needs_visual_base:
        if not render:
            detail = ("没有画面层。工程态审阅不需要它；要出成片请显式加 --render，并先过 render_gate")
            check("画面层", False, detail)
            report["ok"] = False
            return stop()
        from state_fingerprint import source_entries
        rendering_sources = source_entries(project)
        if motion_engine == "remotion" and remotion_dir is not None:
            import remotion_gates
            render_target = remotion_dir / "_render" / "visuals.mp4"
            render_target.parent.mkdir(parents=True, exist_ok=True)
            try:
                visual_path = remotion_gates.render_remotion(project, remotion_dir, render_target)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                check("画面层渲染", False, str(exc)[-600:])
                return stop()
        else:
            (project / "composition/_render").mkdir(parents=True, exist_ok=True)
            # --workers 1：多 worker 截图通道会在长片的后半段静默丢内容
            # （2026-11-04 品牌屋：4 worker 渲染 78s 之后整栋画面不画，退出码仍为 0；见 GOTCHAS #79）。
            # 单 worker 慢一倍，但交付只渲这一次；一致性由下面的 check_render_fidelity 核。
            render_proc = _run(["hyperframes", "render", str(project / "composition"),
                                "-o", str(project / "composition/_render/visuals.mp4"),
                                "--workers", "1", "-q", "looks"])
            visual_path = project / "composition/_render/visuals.mp4"
            if render_proc.returncode != 0 or not visual_path.is_file():
                check("画面层渲染", False, (render_proc.stderr or render_proc.stdout or "")[-400:])
                return stop()
        if rendering_sources != source_entries(project):
            check('画面层来源', False, '渲染期间来源改变；核对当前版本后重新渲染')
            return stop()
        _record_visual_source(project, visual_path, 'composition-render', rendering_sources)
    if visual_path is not None:
        v_video, _ = _streams(visual_path)
        if not check("画面层可读", bool(v_video), f"{visual_path.name} {v_video.get('width')}×{v_video.get('height')}"):
            return stop()

        # 画面层真的等于 composition 吗？渲染通道会静默丢内容（GOTCHAS #79），
        # 运动/黑帧/分辨率都量不出来：抽 12 个时间点和 composition 的快照逐帧比结构。
        if motion_engine != "remotion" and (project / "composition" / "hyperframes.json").is_file():
            fid = _run([sys.executable, str(INTERNAL / "check_render_fidelity.py"), str(project),
                        "--video", str(visual_path), "--samples", "12", "--json"])
            fid_report: dict = {}
            try:
                fid_report = json.loads(fid.stdout)
            except json.JSONDecodeError:
                fid_report = {}
            failed_t = fid_report.get("failed") or []
            if fid.returncode == 0 and fid_report.get("ok"):
                check("画面层与 composition 一致", True,
                      f"{len(fid_report.get('samples') or [])} 个采样一致")
            elif fid.returncode == 1:
                if not check("画面层与 composition 一致", False,
                             f"{len(failed_t)} 个采样对不上：{failed_t[:6]}"
                             f"（--workers 1 重渲后仍不一致，才是 composition 的问题）"):
                    return stop()
            else:
                # 检查跑不起来（没有可用的 snapshot 通道）与「跑通了但内容不一致」不是一件事
                note(f"画面一致性检查未能执行：{(fid.stderr or '')[-200:].strip() or '未知原因'}")
        elif motion_engine == "remotion":
            note("Remotion 工程：跳过 HyperFrames 逐帧快照对比，由 Remotion 门禁与静帧抽检覆盖")
        else:
            note("composition 不是 HyperFrames 工程（无 hyperframes.json）：跳过画面一致性检查")
    else:
        note("storyboard.json 按段直拼模式：无需整片动效 visuals.mp4 底片")

    raw_visual_path = visual_path
    demo_tmp_dir = None
    try:
        # 2b) 按段分流拼合：优先使用统一执行分镜 storyboard.json，否则回退旧 visual-plan.json 实机演示拼合
        if sb_doc is not None and sb_path is not None:
            if effective_mode == "split" and visual_audio_path is None:
                splice_dest = out / f"{name}_画面成片.mp4"
            else:
                demo_tmp_dir = tempfile.TemporaryDirectory(prefix="craft-sb-visual-")
                splice_dest = Path(demo_tmp_dir.name) / f"{name}_画面成片.mp4"
            try:
                spliced_visual, splice_info = _splice_storyboard_segments(
                    project, sb_path, sb_doc, visual_path, geo, out, name,
                    person_path=None if no_person else person_path,
                    visual_dest=splice_dest,
                )
            except RuntimeError as exc:
                check("分镜分段拼合", False, str(exc))
                return stop()
            visual_path = spliced_visual
            report["segment_splice"] = splice_info
            eng_summary = ", ".join(f"{k}={v}" for k, v in splice_info["engine_counts"].items())
            check("分镜分段拼合", True, f"{splice_info['count']} 段按引擎分流拼合（{eng_summary}）")
        else:
            demo_segs = _load_demo_segments(project)
            if demo_segs:
                vis_dur_base = _duration(visual_path)
                if vis_dur_base <= 0:
                    vis_dur_base = max(s["t1"] for s in demo_segs)
                if effective_mode == "split" and visual_audio_path is None:
                    splice_dest = out / f"{name}_画面成片.mp4"
                else:
                    demo_tmp_dir = tempfile.TemporaryDirectory(prefix="craft-demo-visual-")
                    splice_dest = Path(demo_tmp_dir.name) / f"{name}_画面成片.mp4"
                try:
                    spliced_visual, _, splice_info = _splice_demo_segments(
                        project, visual_path, demo_segs, geo, out, name,
                        person_path=None if no_person else person_path,
                        vis_dur=vis_dur_base,
                        visual_dest=splice_dest,
                        emit_person_track=False,
                    )
                except RuntimeError as exc:
                    check("实机演示同轨拼合", False, str(exc))
                    return stop()
                visual_path = spliced_visual
                report["demo_splice"] = splice_info
                check("实机演示同轨拼合", True,
                      f"{splice_info['count']} 段高清原录屏已并入 {Path(splice_info['visual_track']).name}（屏幕清晰文字编码）")

        if effective_mode == "split":
            # 3A) 默认分轨三件套交付：高码率人物成片（含声） + 画面成片（有声景时 -c:v copy 封装 + 同出 wav；无声景保持 0 音轨） + 导入空隙保护字幕
            person_out = out / f"{name}_人物成片.mp4"
            visual_out = out / f"{name}_画面成片.mp4"
            vis_dur = _duration(visual_path)
            if not _mux_person_track(person_path, audio_path, person_out, vis_dur, check):
                return stop()

            soundscape_out: Path | None = None
            if visual_audio_path is not None:
                v_cmd = [
                    "ffmpeg", "-y", "-v", "error",
                    "-i", str(visual_path),
                    "-i", str(visual_audio_path),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                    "-movflags", "+faststart",
                ]
                if vis_dur > 0:
                    v_cmd += ["-t", f"{vis_dur:.3f}"]
                proc_v = _stage_ffmpeg_replace(v_cmd, visual_out)
                if not check("画面成片封装", proc_v.returncode == 0 and visual_out.is_file(),
                             (proc_v.stderr or "ok")[-300:] if proc_v.returncode != 0 else f"{visual_out.name}（-c:v copy + 声景）"):
                    return stop()
                soundscape_out = out / f"{name}_画面音效轨.wav"
                if not check("画面音效轨导出", _export_soundscape_wav(visual_audio_path, soundscape_out), soundscape_out.name):
                    return stop()
            elif visual_path.resolve() != visual_out.resolve():
                v_cmd = [
                    "ffmpeg", "-y", "-v", "error",
                    "-i", str(visual_path),
                    "-map", "0:v:0", "-c:v", "copy", "-an",
                    "-movflags", "+faststart",
                ]
                proc_v = _stage_ffmpeg_replace(v_cmd, visual_out)
                if not check("画面成片封装", proc_v.returncode == 0 and visual_out.is_file(),
                             (proc_v.stderr or "ok")[-300:] if proc_v.returncode != 0 else visual_out.name):
                    return stop()
            else:
                check("画面成片封装", visual_out.is_file(), visual_out.name)

            # 4A) 核验分轨产物
            if visual_audio_path is not None:
                vv, va, dur_v = _check_video_specs(visual_out, geo, check, require_audio=True, silent_visual=False)
                va_sr = int(float(va.get("sample_rate") or 0)) if va else 0
                va_ch = va.get("channels") if va else None
                check("画面声景音轨", bool(va) and va_sr == 48000 and va_ch == 2,
                      f"{va.get('codec_name', '无')} {va_sr}Hz {va_ch or 0}ch")
            else:
                vv, va, dur_v = _check_video_specs(visual_out, geo, check, require_audio=False, silent_visual=True)
            dur_p = _duration(person_out)
            pv, pa = _streams(person_out)
            check("人物成片可读", bool(pv), f"{pv.get('width')}×{pv.get('height')} {pv.get('codec_name', '')}")
            check("时长", dur_p > 0 and dur_v > 0 and abs(dur_p - dur_v) <= 0.5,
                  f"人物 {dur_p:.2f}s / 画面 {dur_v:.2f}s（差 {dur_p - dur_v:+.2f}s）")
            audio_ch = pa.get("channels")
            check("成片有音轨", bool(pa) and (audio_ch in (None, 2)),
                  f"{pa.get('codec_name', '无')} {audio_ch or ''}ch")
            _check_non_black_frames(person_out, dur_p, check)
            _check_visual_non_black(visual_out, dur_v, geo, check)
            _check_caption_safe(visual_out, dur_v, geo, check)
            _export_delivered_srt(srt_path, srt_out, edit_dir, project, dur_p, burn, check, note)
            split_deliverables: dict[str, str | None] = {
                "person": str(person_out),
                "visuals": str(visual_out),
                "subtitles": str(srt_out) if srt_out.is_file() else None,
            }
            split_specs: dict[str, Path] = {"person": person_out, "visuals": visual_out}
            split_inputs: dict[str, Path | None] = {
                "visuals": raw_visual_path, "audio": audio_path, "person": person_path, "srt": srt_path,
            }
            if soundscape_out is not None:
                split_deliverables["visual_audio"] = str(soundscape_out)
                split_inputs["visual_audio"] = visual_audio_path
            return _finalize_report(
                project, edit_dir, out, name, report,
                delivery_mode="split",
                primary_video=person_out,
                deliverables=split_deliverables,
                spec_targets=split_specs,
                inputs=split_inputs,
                srt_out=srt_out, audio_path=audio_path, srt_path=srt_path,
                as_json=as_json, note=note, headline=f"分轨交付：{person_out.name} + {visual_out.name}",
            )

        # 3B) 显式合流（--composite / --mode composite）或无人物（--no-person）：合成单轨成片
        slot = geo["person"]
        pw, ph, px, py = int(slot["w"]), int(slot["h"]), int(slot["x"]), int(slot["y"])
        target = out / f"{name}_成片.mp4"
        vis_dur = _duration(visual_path)
        tail = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
                "-r", str(geo["fps"]), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart"]
        if vis_dur > 0:
            tail += ["-t", f"{vis_dur:.3f}"]
        subtitle_tmp, subtitle_filter = _subtitle_staging(srt_path, burn)
        if person_path is None:
            note("无人物轨：画面层全幅交付，personSlot 区域保持画面层原样")
            if visual_audio_path is not None:
                note("无人物合流模式已混入画面声景轨（-14 LUFS 限幅保护）")
                fc = (f"[0:v]{subtitle_filter}[v];" if subtitle_filter else "") + (
                    "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[va];"
                    "[2:a]aformat=sample_rates=48000:channel_layouts=stereo[sa];"
                    "[va][sa]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                    "alimiter=limit=0.891[aout]"
                )
                cmd_prefix = ["ffmpeg", "-y", "-v", "error", "-i", str(visual_path),
                              "-i", str(audio_path), "-i", str(visual_audio_path),
                              "-filter_complex", fc,
                              "-map", "[v]" if subtitle_filter else "0:v", "-map", "[aout]"] + tail
            else:
                cmd_prefix = ["ffmpeg", "-y", "-v", "error", "-i", str(visual_path), "-i", str(audio_path),
                              "-map", "0:v", "-map", "1:a"]
                if subtitle_filter:
                    cmd_prefix += ["-vf", subtitle_filter]
                cmd_prefix += tail
        else:
            vf = (f"[1:v]scale={pw}:{ph}:force_original_aspect_ratio=increase,"
                  f"crop={pw}:{ph},setsar=1[person];"
                  f"[0:v][person]overlay={px}:{py}:format=auto[composed]")
            vf += f";[composed]{subtitle_filter or 'null'}[v]"
            if visual_audio_path is not None:
                note("合流模式已混入画面声景轨（-14 LUFS 限幅保护）")
                vf += (
                    ";[2:a]aformat=sample_rates=48000:channel_layouts=stereo[va];"
                    "[3:a]aformat=sample_rates=48000:channel_layouts=stereo[sa];"
                    "[va][sa]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                    "alimiter=limit=0.891[aout]"
                )
                cmd_prefix = ["ffmpeg", "-y", "-v", "error", "-i", str(visual_path), "-i", str(person_path),
                              "-i", str(audio_path), "-i", str(visual_audio_path),
                              "-filter_complex", vf, "-map", "[v]", "-map", "[aout]"] + tail
            else:
                cmd_prefix = ["ffmpeg", "-y", "-v", "error", "-i", str(visual_path), "-i", str(person_path),
                              "-i", str(audio_path), "-filter_complex", vf, "-map", "[v]", "-map", "2:a"] + tail
        try:
            proc = _stage_ffmpeg_replace(cmd_prefix, target)
        finally:
            if subtitle_tmp is not None:
                subtitle_tmp.cleanup()
        if not check("合成", proc.returncode == 0 and target.is_file(),
                     (proc.stderr or "ok")[-300:] if proc.returncode != 0 else target.name):
            return stop()

        # 4B) 核验单轨成片
        dur_v = _duration(visual_path)
        _v, _a, dur = _check_video_specs(target, geo, check, require_audio=True)
        check("时长", abs(dur - dur_v) <= 0.5, f"{dur:.2f}s（画面层 {dur_v:.2f}s）")
        _check_non_black_frames(target, dur, check)
        _check_caption_safe(visual_path, dur_v, geo, check)
        _export_delivered_srt(srt_path, srt_out, edit_dir, project, dur, burn, check, note)

        comp_inputs: dict[str, Path | None] = {
            "visuals": raw_visual_path, "audio": audio_path, "person": person_path, "srt": srt_path,
        }
        if visual_audio_path is not None:
            comp_inputs["visual_audio"] = visual_audio_path
        return _finalize_report(
            project, edit_dir, out, name, report,
            delivery_mode=effective_mode,
            primary_video=target,
            deliverables={"video": str(target), "subtitles": str(srt_out) if srt_out.is_file() else None},
            spec_targets={"video": target},
            inputs=comp_inputs,
            srt_out=srt_out, audio_path=audio_path, srt_path=srt_path,
            as_json=as_json, note=note, headline=f"成片：{target}",
        )
    finally:
        if demo_tmp_dir is not None:
            demo_tmp_dir.cleanup()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--visuals", type=Path, help="已有画面层 mp4（跳过渲染）")
    parser.add_argument('--visuals-confirm-current', action='store_true',
                        help='明确人工确认现有画面层属于当前来源；旧缓存/外部画面补记来源，不代替审阅闸门')
    parser.add_argument("--person", type=Path, help="人物素材")
    parser.add_argument("--audio", type=Path, help="声音")
    parser.add_argument("--visual-audio", type=Path, default=None,
                        help="画面声景音轨 WAV（分轨模式下无损封装进画面成片并同出 画面音效轨.wav；默认自动探测 edit/_engineering/soundscape.wav）")
    parser.add_argument("--srt", type=Path, help="字幕（默认外挂）")
    parser.add_argument("--out", type=Path, help="输出目录（默认 <project>/成品）")
    parser.add_argument("--burn-subtitles", dest="burn", action="store_true",
                        help="烧录字幕（需要 ffmpeg 带 libass；有真人轨时自动切为合流模式）")
    parser.add_argument("--no-person", action="store_true",
                        help="纯画面 + 旁白：不贴人物，画面层全幅交付")
    parser.add_argument("--mode", choices=("split", "composite"), default="split",
                        help="交付模式：split（默认：人物成片 + 无声画面成片 + 空隙字幕三件套）或 composite（单轨合成）")
    parser.add_argument("--composite", action="store_true",
                        help="显式合流开关：等效 --mode composite，把人物与画面合成单轨成片")
    parser.add_argument("--render", action="store_true",
                        help="显式渲染画面层（交付动作；默认不渲染，缺画面层时拒绝）")
    parser.add_argument("--approve-in-chat", action="store_true",
                        help="仅在作者于当前对话明确指示导出时使用：必须配 --approval-note 传入作者明确导出原话，核验审阅快照存在后写入含实时源码指纹的会话授权审计记录并放行")
    parser.add_argument("--approval-note", default=None,
                        help="配合 --approve-in-chat 时必填：记录作者在当前对话中明确指示导出成片的原话依据（禁止留空或使用通用占位符）")
    parser.add_argument("--skip-gate", action="store_true", help="测试夹具用：跳过 render_gate")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.approval_note is not None and not args.approve_in_chat:
        parser.error("--approval-note 只能配合 --approve-in-chat 使用")
    if args.skip_gate and args.approve_in_chat:
        parser.error("--skip-gate 不能与 --approve-in-chat 同时使用")
    if args.skip_gate and os.environ.get("DSH_TEST") != "1":
        parser.error("--skip-gate 只允许测试夹具（DSH_TEST=1）；正式流程必须过 render_gate")
    return deliver(args.project.expanduser().resolve(), args.visuals, args.person, args.audio,
                   args.srt, args.out, args.burn, args.skip_gate, args.json, args.no_person,
                   args.render, args.visuals_confirm_current,
                   mode=args.mode, composite=args.composite,
                   approve_in_chat=args.approve_in_chat, approval_note=args.approval_note,
                   visual_audio=args.visual_audio)


if __name__ == "__main__":
    raise SystemExit(main())

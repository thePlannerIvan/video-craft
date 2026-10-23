#!/usr/bin/env python3
"""`交付` —— 画面层 + 人物 + 声音 + 字幕 → 成片 + 核验报告。

它替代的是手写 ffmpeg
----------------------
2026-10-21 的三条片用的是真实形态：**composition 只做画面层**（黑底，左侧 500 给人物、
底部 200 给字幕），人物与声音在交付阶段贴回。Skill 里有 `render.py`、`export_video.py`、
`export_deliverables.py`，但没有一个接口负责这件事，交付方只能自己写 ffmpeg overlay ——
那是草稿，不是模块。

接口
----
    python3 helpers/deliver.py <project> --render              # 显式渲染画面层并合成
    python3 helpers/deliver.py <project> --visuals <mp4>       # 已有画面层，跳过渲染
    python3 helpers/deliver.py <project> --person <mp4> --audio <m4a> --srt <srt>
    python3 helpers/deliver.py <project> --no-person      # 纯画面 + 旁白：画面层全幅交付
    python3 helpers/deliver.py <project> --json

它保证
------
1. 人物按 `recompose.json` 的 `personSlot` 贴回（cover 裁切，不挤压）；没有人物轨的片子用
   `--no-person` 全幅交付，并在报告 notes 里写明；
2. 声音接上，且成片**真的有音轨**；
3. 字幕区（`captionSafe`）在画面层里是空的 —— 有内容就报 warning 并指出哪一帧；
4. 逐项核验：分辨率、帧率、时长、音轨、首/中/尾帧非全黑，产出 JSON 报告；
5. 字幕优先外挂（`--burn-subtitles` 需要 ffmpeg 带 libass，没有就明确报错，不静默降级）。

前置：`render_gate.py` 必须放行（有人工提交且源未漂移）。
默认**不渲染**：缺画面层或画面层比 composition 旧时直接拒绝，要渲染必须显式 `--render`
（那是交付动作，不是审阅动作）。`--skip-gate` 只对测试进程（`DSH_TEST=1`）开放。
`composition/_render/visuals.mp4` 比 composition 源旧时**默认拒绝**，显式 `--render` 才重渲
（否则会交付上一版画面，或把审阅变成导出）。
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
sys.path.insert(0, str(HELPERS))

DEFAULT_PERSON_SLOT = {"x": 0, "y": 0, "w": 500, "h": 1080}
DEFAULT_CAPTION_SAFE = {"x": 0, "y": 880, "w": 1920, "h": 200}
BLACK_LUMA = 6.0          # 低于它视为全黑
BAND_LUMA = 24.0          # 字幕区里出现高于它的内容 → 会被字幕压住


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
    return sum(data) / len(data)


def _geometry(project: Path) -> dict:
    cfg = {}
    path = project / "recompose.json"
    if path.is_file():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {}
    canvas = cfg.get("canvas") or {}
    return {
        "width": int(canvas.get("w") or 1920),
        "height": int(canvas.get("h") or 1080),
        "fps": int(canvas.get("fps") or 30),
        "person": cfg.get("personSlot") or dict(DEFAULT_PERSON_SLOT),
        "caption": cfg.get("captionSafe") or dict(DEFAULT_CAPTION_SAFE),
    }


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
    proc = _run([sys.executable, str(HELPERS / "check_render_env.py"), str(composition), "--json"])
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
    plain = _run([sys.executable, str(HELPERS / "check_render_env.py"), str(composition)])
    lines = [ln.strip() for ln in (plain.stdout or "").splitlines() if ln.strip().startswith("x")]
    blocked = [ln for ln in lines if "workers:" not in ln]
    if blocked or not lines:
        return False, workers, "；".join(blocked[:2])
    mem = data.get("memory") or {}
    avail = mem.get("availableGb")
    return True, workers, (f"内存偏紧（可用 {avail} GB < 门槛），按建议 --workers {workers} 渲染")


def _preflight(project: Path, check, note) -> tuple[bool, int]:
    """Mechanical timing-lock checks, before any production encoder starts."""
    import probe_env
    env = probe_env.build(project)
    ffmpeg_ok = env.get("ffmpeg", {}).get("present") and bool(shutil.which("ffprobe"))
    if not check("编码能力", bool(ffmpeg_ok), "probe_env：需要 ffmpeg/ffprobe"):
        return False, 1
    composition = project / "composition"
    if not (composition / "index.html").is_file():
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
    if references or (project / "pages").exists() or (project / ".pages").exists():
        proc = _run([sys.executable, str(HELPERS / "film.py"), "verify", str(project), "--json"])
        if not check("原页拆解", proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]):
            return False, workers
    proc = _run(["hyperframes", "check", str(composition), "--json"])
    if not check("HyperFrames check", proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]):
        return False, workers
    scripts = [composition / "index.html", *composition.rglob("*.js")]
    has_gsap = any("gsap" in p.read_text(encoding="utf-8", errors="ignore")
                   for p in scripts if not any(x in p.parts for x in ("node_modules", "_render", ".hyperframes")))
    if has_gsap:
        proc = _run([sys.executable, str(HELPERS / "check_motion_targets.py"), str(project),
                     "--strict-transform", "--json"])
        if not check("动效目标", proc.returncode == 0 and "SKIP" not in proc.stdout,
                     (proc.stdout + proc.stderr)[-2000:]):
            return False, workers
    return True, workers


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
        proc = subprocess.run([sys.executable, str(HELPERS / "verify_delivery.py"),
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
            visuals_confirm_current: bool = False) -> int:
    geo = _geometry(project)
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
        code, = (_run([sys.executable, str(HELPERS / "render_gate.py"), str(project)]).returncode,)
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

    # 1) 三路素材
    person_path = _pick(project, person, [project / "composition/assets/person.mp4",
                                         project / "edit/_engineering/person_master.mp4"])
    audio_path = _pick(project, audio, [project / "composition/assets/audio.m4a",
                                        project / "edit/_engineering/review_audio.m4a"])
    srt_path = _pick(project, srt, [project / "edit/subtitles.srt",
                                    project / "成品" / f"{name}_字幕.srt"])
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

    # 2) 画面层：已有就用，没有就渲
    visual_path = _pick(project, visuals, [project / "composition/_render/visuals.mp4"])
    if visual_path is not None and visuals_confirm_current:
        _record_visual_source(project, visual_path, 'manual-confirmation')
        note('执行者明确确认现有画面层属于当前来源；已记录人工确认及文件内容身份')
    if visual_path is not None and _render_is_stale(project, visual_path):
        if not render:
            detail = (f"{visual_path.name} 来源缺记录或已过期。重渲用 --render；"
                      "旧缓存/外部画面经人工核对属于当前版后，用 --visuals-confirm-current 补记一次来源")
            check("画面层", False, detail)
            if not as_json:
                print(f"  ✗ {detail}")
            report["ok"] = False
            (out / f"{name}_核验报告.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return stop()
        note(f"画面层比 composition 源旧（{visual_path.name}），按 --render 重新渲染")
        visual_path = None
    if visual_path is None:
        if not render:
            detail = ("没有画面层。工程态审阅不需要它；要出成片请显式加 --render，并先过 render_gate")
            check("画面层", False, detail)
            if not as_json:
                print(f"  ✗ {detail}")
            report["ok"] = False
            (out / f"{name}_核验报告.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return stop()
        (project / "composition/_render").mkdir(parents=True, exist_ok=True)
        from state_fingerprint import source_entries
        rendering_sources = source_entries(project)
        render = _run(["hyperframes", "render", str(project / "composition"),
                       "-o", str(project / "composition/_render/visuals.mp4"),
                       "--workers", str(workers), "-q", "looks"])
        visual_path = project / "composition/_render/visuals.mp4"
        if render.returncode != 0 or not visual_path.is_file():
            check("画面层渲染", False, (render.stderr or render.stdout or "")[-400:])
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return stop()
        if rendering_sources != source_entries(project):
            check('画面层来源', False, '渲染期间来源改变；核对当前版本后重新渲染')
            return stop()
        _record_visual_source(project, visual_path, 'composition-render', rendering_sources)
    v_video, _ = _streams(visual_path)
    if not check("画面层可读", bool(v_video), f"{visual_path.name} {v_video.get('width')}×{v_video.get('height')}"):
        return stop()

    # 3) 合成：人物 cover 贴回 + 声音（无人物轨时画面层全幅交付）
    slot = geo["person"]
    pw, ph, px, py = int(slot["w"]), int(slot["h"]), int(slot["x"]), int(slot["y"])
    target = out / f"{name}_成片.mp4"
    # 画面层是时长主人：人物轨 / 旁白常常比画面层长一点（母版 368.4 vs 画面 367.6），
    # 只写 -shortest 在 filter_complex + overlay 下并不保证截断（2026-10-21 真实素材上
    # 交付出 368.33s，比画面层长 0.7s，核验报红）。这里显式用 -t 钉住。
    vis_dur = _duration(visual_path)
    tail = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
            "-r", str(geo["fps"]), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart"]
    if vis_dur > 0:
        tail += ["-t", f"{vis_dur:.3f}"]
    tail.append(str(target))
    # libavfilter has several escaping layers. A private ASCII filename avoids
    # interpreting punctuation in the user's path; the SRT bytes stay unchanged.
    subtitle_tmp = tempfile.TemporaryDirectory(prefix="craft-subtitles-") if burn else None
    subtitle_filter = None
    if subtitle_tmp is not None:
        staged_srt = Path(subtitle_tmp.name) / "captions.srt"
        shutil.copyfile(srt_path, staged_srt)
        subtitle_filter = f"subtitles=filename='{staged_srt.as_posix()}'"
    if person_path is None:
        note("无人物轨：画面层全幅交付，personSlot 区域保持画面层原样")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(visual_path), "-i", str(audio_path),
               "-map", "0:v", "-map", "1:a"]
        if subtitle_filter:
            cmd += ["-vf", subtitle_filter]
        cmd += tail
    else:
        vf = (f"[1:v]scale={pw}:{ph}:force_original_aspect_ratio=increase,"
              f"crop={pw}:{ph},setsar=1[person];"
              f"[0:v][person]overlay={px}:{py}:format=auto[composed]")
        vf += f";[composed]{subtitle_filter or 'null'}[v]"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(visual_path), "-i", str(person_path),
               "-i", str(audio_path), "-filter_complex", vf, "-map", "[v]", "-map", "2:a"] + tail
    try:
        proc = _run(cmd)
    finally:
        if subtitle_tmp is not None:
            subtitle_tmp.cleanup()
    if not check("合成", proc.returncode == 0 and target.is_file(),
                 (proc.stderr or "ok")[-300:] if proc.returncode != 0 else target.name):
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return stop()

    # 4) 核验
    v, a = _streams(target)
    check("分辨率", (v.get("width"), v.get("height")) == (geo["width"], geo["height"]),
          f"{v.get('width')}×{v.get('height')} 期望 {geo['width']}×{geo['height']}")
    got_fps = v.get("r_frame_rate") or "0/1"
    try:
        num, den = got_fps.split("/")
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    check("帧率", abs(fps - geo["fps"]) < 0.01, f"{fps:.2f} 期望 {geo['fps']}")
    dur_v = _duration(visual_path)
    dur = _duration(target)
    check("时长", abs(dur - dur_v) <= 0.5, f"{dur:.2f}s（画面层 {dur_v:.2f}s）")
    check("成片有音轨", bool(a), f"{a.get('codec_name', '无')} {a.get('channels', '')}ch")

    for label, at in (("首帧", 0.4), ("中帧", dur / 2), ("尾帧", max(0.0, dur - 0.6))):
        luma = _frame_luma(target, at)
        check(f"{label}非全黑", luma is None or luma >= BLACK_LUMA,
              f"mean_luma={None if luma is None else round(luma, 1)} @ {at:.1f}s")

    # 5) 字幕安全区在画面层里必须是空的
    band = geo["caption"]
    crop = (int(band["w"]), int(band["h"]), int(band["x"]), int(band["y"]))
    intrusions = []
    for at in (dur_v * 0.25, dur_v * 0.5, dur_v * 0.75):
        luma = _frame_luma(visual_path, at, crop)
        if luma is not None and luma > BAND_LUMA:
            intrusions.append((round(at, 1), round(luma, 1)))
    check("字幕安全区无内容", not intrusions,
          "空" if not intrusions else f"这些时刻有内容会被字幕压住：{intrusions[:4]}")

    # 6) 字幕：外挂优先；交付的字幕必须与成片同一条时间轴
    srt_out = out / f"{name}_字幕.srt"
    if srt_path and srt_path.is_file():
        if srt_path.resolve() != srt_out.resolve():
            shutil.copyfile(srt_path, srt_out)
        from _cutmap import (DURATION_TOLERANCE_S, compare_srt,
                             expected_film_duration_s, load as load_cut_map,
                             paths as cut_paths, validate as validate_cut_map,
                             verify_srt_pair)
        from _timecode import parse_srt_file
        cut_map, cut_problems = load_cut_map(edit_dir)
        if cut_map is not None:
            cut_problems += validate_cut_map(cut_map, project)
        cues = parse_srt_file(srt_out) if srt_out.is_file() else []
        overrun = bool(cues) and cues[-1]["endMs"] / 1000 > dur + 0.05
        if cut_problems:
            check("字幕时间轴", False, "；".join(cut_problems[:2]))
        elif cut_map is not None:
            # deliver.py 产出的是渲染时间轴成片；二次剪成片由项目的剪片脚本产出，
            # 交付字幕只能按 cut-map 逐条复算（项目剪片后应直接用 verify_delivery 核验）。
            resolved = cut_paths(cut_map, project)
            pair = verify_srt_pair(resolved["srt_source"], srt_out, cut_map,
                                   film_duration_s=dur)
            expected = expected_film_duration_s(cut_map)
            same_film = expected is not None and abs(dur - expected) <= DURATION_TOLERANCE_S
            detail = (f"{srt_out.name} 是按 cut-map 复算的剪后字幕，成片 {dur:.3f}s 与 cut-map 一致"
                      if not pair and same_film else
                      "；".join((pair or [f"成片 {dur:.3f}s 与 cut-map 推算的 {expected:.3f}s 不一致"])[:2]))
            check("字幕时间轴", not pair and same_film, detail)
        else:
            master = edit_dir / "subtitles.srt"
            problems = compare_srt(srt_out, master) if master.is_file() else []
            detail = ("；".join(problems[:2]) if problems else
                      (f"字幕末条 {cues[-1]['endMs'] / 1000:.3f}s 超出成片 {dur:.3f}s" if overrun else
                       "与流水线字幕同一条时间轴"))
            check("字幕时间轴", not problems and not overrun, detail)
        check("字幕交付", True, f"外挂 {srt_out.name}（烧录={burn}）")
    else:
        note("没有字幕源；如需字幕请 --srt")

    # 7) 最终签字：交付核验。判据仍归 verify_delivery（它回答"这一版能不能发"），
    #    deliver 只把它的结论并入报告，不再自己下第二个结论（合并地图 M5-A）。
    report["composition_ok"] = all(c["ok"] for c in report["checks"])
    report["delivery_verdict"] = _delivery_verdict(edit_dir, target, audio_path, srt_path)
    report["delivery_ok"] = report["delivery_verdict"]["ok"]
    note("交付核验（verify_delivery）：" + ("通过" if report["delivery_ok"] else
         "失败：" + "；".join(report["delivery_verdict"]["hard"][:3])))

    from state_fingerprint import source_entries, entry
    report["source_fingerprint"] = source_entries(project)
    report["output_identity"] = entry(target)
    report['input_identities'] = {key: entry(path) for key, path in (
        ('visuals', visual_path), ('audio', audio_path), ('person', person_path), ('srt', srt_path)) if path}
    report["output"] = str(target)
    report["subtitles"] = str(srt_out) if srt_out.is_file() else None
    report["ok"] = report["composition_ok"] and report["delivery_ok"]
    (out / f"{name}_核验报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not as_json:
        print(f"\n{'✓' if report['ok'] else '✗'} 成片：{target}")
        print(f"  核验报告：{out / f'{name}_核验报告.json'}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["ok"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--visuals", type=Path, help="已有画面层 mp4（跳过渲染）")
    parser.add_argument('--visuals-confirm-current', action='store_true',
                        help='明确人工确认现有画面层属于当前来源；旧缓存/外部画面补记来源，不代替审阅闸门')
    parser.add_argument("--person", type=Path, help="人物素材")
    parser.add_argument("--audio", type=Path, help="声音")
    parser.add_argument("--srt", type=Path, help="字幕（默认外挂）")
    parser.add_argument("--out", type=Path, help="输出目录（默认 <project>/成品）")
    parser.add_argument("--burn-subtitles", dest="burn", action="store_true",
                        help="烧录字幕（需要 ffmpeg 带 libass）")
    parser.add_argument("--no-person", action="store_true",
                        help="纯画面 + 旁白：不贴人物，画面层全幅交付")
    parser.add_argument("--render", action="store_true",
                        help="显式渲染画面层（交付动作；默认不渲染，缺画面层时拒绝）")
    parser.add_argument("--skip-gate", action="store_true", help="测试夹具用：跳过 render_gate")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.skip_gate and os.environ.get("DSH_TEST") != "1":
        parser.error("--skip-gate 只允许测试夹具（DSH_TEST=1）；正式流程必须过 render_gate")
    return deliver(args.project.expanduser().resolve(), args.visuals, args.person, args.audio,
                   args.srt, args.out, args.burn, args.skip_gate, args.json, args.no_person,
                   args.render, args.visuals_confirm_current)


if __name__ == "__main__":
    raise SystemExit(main())

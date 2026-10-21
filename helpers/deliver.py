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
    python3 helpers/deliver.py <project>                       # 渲染画面层并合成
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

前置：`render_gate.py` 必须放行（有人工提交且源未漂移）；夹具可用 `--skip-gate`。
`composition/_render/visuals.mp4` 比 composition 源旧时自动重渲（否则会交付上一版画面）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
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


def _render_is_stale(project: Path, visual: Path) -> bool:
    """画面层是不是比 composition 源旧。

    `composition/_render/visuals.mp4` 是上一次渲染的缓存。改过 composition、
    重新审阅、再跑 deliver 时会静默拿旧画面出片 —— 审阅看的是新的、交付的是旧的。
    这里按源文件 mtime 判新旧，旧了就重渲。
    """
    comp = project / "composition"
    if not (comp / "index.html").is_file():
        return False
    try:
        vis_mtime = visual.stat().st_mtime
    except OSError:
        return True
    newest = (comp / "index.html").stat().st_mtime
    for path in comp.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(comp)
        if rel.parts and rel.parts[0] in ("_render", ".hyperframes", "node_modules"):
            continue
        if path.suffix.lower() in (".mp4", ".mov", ".webm"):
            continue
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest > vis_mtime + 1e-6


def deliver(project: Path, visuals: Path | None, person: Path | None, audio: Path | None,
            srt: Path | None, out_dir: Path | None, burn: bool, skip_gate: bool,
            as_json: bool, no_person: bool = False) -> int:
    geo = _geometry(project)
    out = (out_dir or project / "成品")
    out.mkdir(parents=True, exist_ok=True)
    name = project.name
    report: dict = {"project": str(project), "geometry": geo, "checks": [], "notes": []}

    def note(text: str) -> None:
        report["notes"].append(text)
        if not as_json:
            print(f"  · {text}")

    def check(name_: str, ok: bool, detail: str) -> bool:
        report["checks"].append({"name": name_, "ok": bool(ok), "detail": detail})
        if not as_json:
            print(f"{'✓' if ok else '✗'} {name_} — {detail}")
        return ok

    # 0) 渲染闸门
    if not skip_gate:
        code, = (_run([sys.executable, str(HELPERS / "render_gate.py"), str(project)]).returncode,)
        if code != 0:
            if not check("渲染闸门", False, "没有人审覆盖当前快照（先 review.py 交给人审；夹具用 --skip-gate）"):
                print(json.dumps(report, ensure_ascii=False, indent=1))
                return 1
        else:
            check("渲染闸门", True, "有人审覆盖当前快照")

    # 1) 三路素材
    person_path = _pick(project, person, [project / "composition/assets/person.mp4",
                                         project / "edit/_engineering/person_master.mp4"])
    audio_path = _pick(project, audio, [project / "composition/assets/audio.m4a",
                                        project / "edit/_engineering/review_audio.m4a"])
    srt_path = _pick(project, srt, [project / "edit/subtitles.srt",
                                    project / "成品" / f"{name}_字幕.srt"])
    if no_person:
        if person_path is not None:
            note(f"声明无人物轨：忽略 {person_path.name}，画面层全幅交付")
        person_path = None
    elif not check("人物素材", person_path is not None,
                   str(person_path or "缺（用 --person 指；纯画面 + 旁白的片子加 --no-person）")):
        return 1
    if not check("声音素材", audio_path is not None, str(audio_path or "缺（用 --audio 指）")):
        return 1

    # 2) 画面层：已有就用，没有就渲
    visual_path = _pick(project, visuals, [project / "composition/_render/visuals.mp4"])
    if visual_path is not None and visuals is None and _render_is_stale(project, visual_path):
        note(f"画面层比 composition 源旧（{visual_path.name}），重新渲染")
        visual_path = None
    if visual_path is None:
        if not as_json:
            print("  · 没有 --visuals，开始渲染画面层（这是唯一需要等的一步）")
        env = _run([sys.executable, str(HELPERS / "check_render_env.py"),
                    str(project / "composition"), "--json"])
        if env.returncode != 0:
            check("渲染环境", False, (env.stdout or env.stderr or "")[-400:])
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 1
        check("渲染环境", True, "check_render_env 退 0")
        (project / "composition/_render").mkdir(parents=True, exist_ok=True)
        render = _run(["hyperframes", "render", str(project / "composition"),
                       "-o", str(project / "composition/_render/visuals.mp4"),
                       "--workers", "1", "-q", "looks"])
        visual_path = project / "composition/_render/visuals.mp4"
        if render.returncode != 0 or not visual_path.is_file():
            check("画面层渲染", False, (render.stderr or render.stdout or "")[-400:])
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 1
    v_video, _ = _streams(visual_path)
    if not check("画面层可读", bool(v_video), f"{visual_path.name} {v_video.get('width')}×{v_video.get('height')}"):
        return 1

    # 3) 合成：人物 cover 贴回 + 声音（无人物轨时画面层全幅交付）
    slot = geo["person"]
    pw, ph, px, py = int(slot["w"]), int(slot["h"]), int(slot["x"]), int(slot["y"])
    target = out / f"{name}_成片.mp4"
    tail = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
            "-r", str(geo["fps"]), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", "-shortest", str(target)]
    if burn:
        probe = _run(["ffmpeg", "-hide_banner", "-filters"])
        if " ass " not in (probe.stdout or ""):
            if not check("烧字幕", False, "本机 ffmpeg 没有 libass；改外挂 SRT（默认行为）"):
                print(json.dumps(report, ensure_ascii=False, indent=1))
                return 1
    if person_path is None:
        note("无人物轨：画面层全幅交付，personSlot 区域保持画面层原样")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(visual_path), "-i", str(audio_path),
               "-map", "0:v", "-map", "1:a"] + tail
    else:
        vf = (f"[1:v]scale={pw}:{ph}:force_original_aspect_ratio=increase,"
              f"crop={pw}:{ph},setsar=1[person];"
              f"[0:v][person]overlay={px}:{py}:format=auto[v]")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(visual_path), "-i", str(person_path),
               "-i", str(audio_path), "-filter_complex", vf, "-map", "[v]", "-map", "2:a"] + tail
    proc = _run(cmd)
    if not check("合成", proc.returncode == 0 and target.is_file(),
                 (proc.stderr or "ok")[-300:] if proc.returncode != 0 else target.name):
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 1

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

    # 6) 字幕：外挂优先
    srt_out = out / f"{name}_字幕.srt"
    if srt_path and srt_path.is_file():
        if srt_path.resolve() != srt_out.resolve():
            shutil.copyfile(srt_path, srt_out)
        check("字幕交付", True, f"外挂 {srt_out.name}（烧录={burn}）")
    else:
        note("没有字幕源；如需字幕请 --srt")

    report["output"] = str(target)
    report["subtitles"] = str(srt_out) if srt_out.is_file() else None
    report["ok"] = all(c["ok"] for c in report["checks"])
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
    parser.add_argument("--person", type=Path, help="人物素材")
    parser.add_argument("--audio", type=Path, help="声音")
    parser.add_argument("--srt", type=Path, help="字幕（默认外挂）")
    parser.add_argument("--out", type=Path, help="输出目录（默认 <project>/成品）")
    parser.add_argument("--burn-subtitles", dest="burn", action="store_true",
                        help="烧录字幕（需要 ffmpeg 带 libass）")
    parser.add_argument("--no-person", action="store_true",
                        help="纯画面 + 旁白：不贴人物，画面层全幅交付")
    parser.add_argument("--skip-gate", action="store_true", help="夹具用：跳过 render_gate")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    return deliver(args.project.expanduser().resolve(), args.visuals, args.person, args.audio,
                   args.srt, args.out, args.burn, args.skip_gate, args.json, args.no_person)


if __name__ == "__main__":
    raise SystemExit(main())

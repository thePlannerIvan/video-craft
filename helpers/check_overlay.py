#!/usr/bin/env python3
"""Verify that every EDL overlay can actually be composited.

Why this exists
---------------
The overlay seam is the one place where a wrong file does not fail — it produces
a *plausible* wrong video. The failure that motivated this module (2026-09-15):

    A 花字 layer was rendered with `npx hyperframes render --format webm`.
    This machine's ffmpeg is built without libvpx alpha support, so the WebM
    decoded as fully opaque. `render.py` overlaid it happily, and six minutes of
    rendering later the base video was black wherever the overlay should have
    been transparent. Neither render tool warned. The knowledge that WebM alpha
    is broken here was already written down — in a *different* skill.

So the contract is checked, not assumed. `check_overlay.py` is the standalone
gate; `render.py` calls the same function before compositing, so a bad overlay
costs a second instead of a render.

The interface an overlay must honour
------------------------------------
    {file, start_in_output, duration, kind}
      kind = "alpha"   → rides on the base footage; must carry a real alpha plane
      kind = "opaque"  → replaces the frame; must NOT be expected to have alpha

`kind` defaults to "alpha": an opaque file declared alpha is caught loudly,
whereas an alpha file declared opaque would silently punch a hole. Default to
the loud failure.

Overlay anchors go stale — reported, never repaired
---------------------------------------------------
`start_in_output` is hand-written into `edl.json` and read by `render.py`, but no
edit path rewrites it (`edl_edit.py` / `apply_selection.py` only touch `ranges`).
Re-cut the film after the overlays were placed and every anchor still points at
the old timeline: the overlay lands on the wrong content or past the end. That is
reported here and deliberately NOT fixed — clamping a hand-written anchor is a
content decision, not a repair, so this check only ever warns.

Usage:
    python helpers/check_overlay.py <edit_dir> [--json] [--duration-tolerance 0.05]
"""
from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe import alpha_range, pix_fmt_has_alpha, probe_video  # noqa: E402

# One frame at 30fps is 0.033s; the tolerance gives a frame of headroom so a
# container that rounds its duration does not fail the gate.
DEFAULT_DURATION_TOLERANCE = 0.05
# A live alpha plane has pixels below this. 255 means fully opaque; the slack
# absorbs codec ringing on near-transparent edges.
OPAQUE_FLOOR = 250
# ...and a window that is transparent EVERYWHERE is a design mistake, not a
# composite hazard: nothing of the overlay will ever be visible. Only a truly
# empty alpha plane qualifies — [0, 237] is a perfectly normal fade-in.
TRANSPARENT_CEIL = 8
# How far past the film's end an anchor may sit before it is called stale.
ANCHOR_TOLERANCE = 0.05


def output_timeline(edl: dict) -> tuple[list[dict], float]:
    """Where each range lands in the OUTPUT, plus the film's current total.

    Every edit path rewrites `total_duration_s` (`edl_edit.py`,
    `apply_selection.py`, `mirror_edl.py`), so it is the EDL's own statement of
    how long the film is now. When the declared total and the range list
    disagree, the LARGER wins: a shrunken range list must not be able to hide an
    anchor that no longer fits.
    """
    rows: list[dict] = []
    t = 0.0
    for r in edl.get("ranges") or []:
        try:
            start, end = float(r["start"]), float(r["end"])
        except (KeyError, TypeError, ValueError):
            continue
        speed = float(r.get("speed", 1.0) or 1.0)
        dur = max(0.0, (end - start) / speed)
        rows.append({"beat": r.get("beat"), "start": t, "end": t + dur})
        t += dur
    declared = edl.get("total_duration_s")
    total = t
    if isinstance(declared, (int, float)) and not isinstance(declared, bool):
        total = max(t, float(declared))
    return rows, total


def anchor_problems(ov: dict, timeline: list[dict], total: float) -> list[str]:
    """Report-only: does this overlay's hand-written anchor still fit the EDL?

    Never returns a hard problem and never edits anything.
    """
    out: list[str] = []
    name = Path(str(ov.get("file", "?"))).name
    try:
        start = float(ov["start_in_output"])
        dur = float(ov["duration"])
    except (KeyError, TypeError, ValueError):
        out.append(f"{name}: 读不到 start_in_output/duration，无法核对锚点是否陈旧")
        return out

    end = start + dur
    if end > total + ANCHOR_TOLERANCE:
        out.append(
            f"{name}: 锚点陈旧——start_in_output {start:.3f}s + duration {dur:.3f}s "
            f"= {end:.3f}s，超出当前 EDL 的成片总时长 {total:.3f}s（超 {end - total:.3f}s）。"
            "这个锚点是老时间轴上手写的，重剪没有跟着改；"
            "这里只报告，不会自动夹回——请重新锚定 start_in_output。")

    beat = ov.get("beat")
    if beat is not None:
        window = next((b for b in timeline if b["beat"] == beat), None)
        if window is None:
            out.append(f"{name}: 覆盖层声明 beat={beat!r}，当前 EDL 的 ranges 里没有这个 beat"
                       "——锚点无从核对，请确认它是否已被重剪掉。")
        elif not (window["start"] - ANCHOR_TOLERANCE <= start
                  <= window["end"] + ANCHOR_TOLERANCE):
            out.append(
                f"{name}: 锚点陈旧——声明 beat={beat!r} 在成片里位于 "
                f"{window['start']:.3f}–{window['end']:.3f}s，"
                f"但 start_in_output={start:.3f}s 落在它外面；重剪把它挪走了。"
                "这里只报告，不自动改。")
    return out


def _rate_value(rate: str | None) -> float | None:
    if not rate or rate == "0/0":
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/")
            return float(num) / float(den) if float(den) else None
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return None


def locate(file_field: str, edit_dir: Path) -> Path:
    p = Path(file_field)
    return p if p.is_absolute() else (edit_dir / p).resolve()


def verify_overlay(
    path: Path,
    *,
    kind: str = "alpha",
    declared_duration: float | None = None,
    expected_fps: float | None = None,
    expected_size: tuple[int, int] | None = None,
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE,
) -> tuple[list[str], list[str]]:
    """Return (hard problems, warnings) for one overlay file.

    Hard problems mean the composite would be wrong; warnings mean it would be
    surprising. The caller decides whether to stop.
    """
    hard: list[str] = []
    warn: list[str] = []
    info = probe_video(path)
    name = path.name

    if not info["exists"]:
        return [f"{name}: 文件不存在（{path}）"], []
    if not info["has_video"]:
        return [f"{name}: 没有视频流"], []

    if kind == "alpha":
        if not pix_fmt_has_alpha(info["pix_fmt"]):
            hard.append(
                f"{name}: 声明为 alpha 层，但像素格式是 {info['pix_fmt']}，没有 alpha 通道"
                "——合成时会整帧盖住底片（底片会变黑）。"
                "用 png-sequence + encode_transparent.py 出 ProRes 4444 / PNG-in-MOV；"
                "本机 ffmpeg 的 libvpx 没编 alpha，WebM 会静默丢透明。")
        else:
            rng = alpha_range(path)
            if rng is None:
                warn.append(f"{name}: alpha 通道存在，但采样失败，未能证明它真的在用")
            else:
                lo, hi = rng
                if lo >= OPAQUE_FLOOR:
                    hard.append(
                        f"{name}: 有 alpha 通道，但采样帧的 alpha 全在 [{lo},{hi}]"
                        "（=完全不透明）——透明信息已被烘掉，合成后底片会被盖住。")
                elif hi <= TRANSPARENT_CEIL:
                    warn.append(
                        f"{name}: 采样帧的 alpha 全在 [{lo},{hi}]（=整个窗口全透明），"
                        "这段时间可能什么都看不到")
    elif kind == "opaque":
        if pix_fmt_has_alpha(info["pix_fmt"]):
            warn.append(f"{name}: 声明为不透明层，但带 alpha 通道（{info['pix_fmt']}）"
                        "——确认透明区域不会盖住底片")
    else:
        hard.append(f"{name}: 未知的 kind={kind!r}（应为 alpha 或 opaque）")

    if declared_duration is not None and info["duration"] is not None:
        drift = abs(info["duration"] - declared_duration)
        if drift > duration_tolerance:
            hard.append(
                f"{name}: 实际时长 {info['duration']:.3f}s 与 EDL 声明的 "
                f"{declared_duration:.3f}s 相差 {drift:.3f}s（容差 {duration_tolerance}s）"
                "——动画会在窗口中间被切掉或提前结束")

    if expected_fps is not None:
        observed = _rate_value(info["avg_frame_rate"]) or _rate_value(info["r_frame_rate"])
        if observed is None:
            warn.append(f"{name}: 读不到帧率，无法与底片比对")
        elif abs(observed - expected_fps) > 0.01:
            hard.append(
                f"{name}: 帧率 {observed:g} 与底片 {expected_fps:g} 不一致"
                "——合成时会被重采样，动画节奏和帧对齐都会漂")

    if expected_size is not None and info["width"] and info["height"]:
        if (info["width"], info["height"]) != tuple(expected_size):
            hard.append(
                f"{name}: 尺寸 {info['width']}x{info['height']} 与成片画布 "
                f"{expected_size[0]}x{expected_size[1]} 不一致")

    if info["width"] and info["height"] and expected_size is None:
        pass
    return hard, warn


def expected_canvas(edl: dict, edit_dir: Path) -> tuple[int, int] | None:
    """The canvas render.py will scale the base to, from the first source."""
    # An explicit `canvas` wins: a project whose base has no picture declares its
    # own frame size, and probing an audio file for orientation would answer 16:9.
    raw = edl.get("canvas")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return (int(raw[0]), int(raw[1]))
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import render as _render  # local import: see the module docstring
        ranges = edl.get("ranges") or []
        if not ranges:
            return None
        first = _render.resolve_path(edl["sources"][ranges[0]["source"]], edit_dir)
        if not _render.source_has_video(first):
            return (1920, 1080)
        if _render.is_portrait_source(first):
            return (1080, 1920)
        return (1920, 1080)
    except Exception:
        return None


def expected_fps(edl: dict, edit_dir: Path) -> float | None:
    """The rate render.py will use: explicit --fps is not visible here, so this
    is the source-derived rate, which is the default path."""
    declared = edl.get("fps")
    if declared:
        try:
            return float(Fraction(str(declared)))
        except (ValueError, ZeroDivisionError):
            pass
    try:
        import render as _render
        ranges = edl.get("ranges") or []
        if not ranges:
            return None
        first = _render.resolve_path(edl["sources"][ranges[0]["source"]], edit_dir)
        return _render.fps_float(_render.normalize_output_rate(
            _render.probe_source_fps(first) or "24"))
    except Exception:
        return None


def check_edit_dir(edit_dir: Path,
                   duration_tolerance: float = DEFAULT_DURATION_TOLERANCE) -> dict:
    edl_path = edit_dir / "edl.json"
    if not edl_path.exists():
        raise SystemExit(f"no edl.json in {edit_dir}")
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    overlays = edl.get("overlays") or []
    canvas = expected_canvas(edl, edit_dir)
    fps = expected_fps(edl, edit_dir)
    # A real render records its rate; prefer it when present.
    dur_file = edit_dir / "segment_durations.json"
    if dur_file.exists():
        try:
            blob = json.loads(dur_file.read_text(encoding="utf-8"))
            for entry in blob.values():
                if isinstance(entry, dict) and entry.get("fps"):
                    fps = float(entry["fps"])
                    break
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    results = []
    timeline, total = output_timeline(edl)
    for ov in overlays:
        path = locate(ov["file"], edit_dir)
        hard, warn = verify_overlay(
            path,
            kind=str(ov.get("kind", "alpha")),
            declared_duration=ov.get("duration"),
            expected_fps=fps,
            expected_size=canvas,
            duration_tolerance=duration_tolerance,
        )
        # Report-only, and only when there is a timeline to judge against: these
        # never enter `hard`, so they cannot change the exit code.
        stale = anchor_problems(ov, timeline, total) if timeline else []
        results.append({
            "file": ov["file"], "kind": ov.get("kind", "alpha"),
            "start_in_output": ov.get("start_in_output"),
            "declared_duration": ov.get("duration"),
            "hard": hard, "warn": warn, "stale_anchor": stale,
        })
    return {
        "edit_dir": str(edit_dir), "overlays": len(overlays),
        "expected_canvas": canvas, "expected_fps": fps, "results": results,
        "output_total_s": round(total, 3) if timeline else None,
        "hard": [m for r in results for m in r["hard"]],
        "warn": [m for r in results for m in r["warn"]],
        # Report-only: an overlay anchor that no longer fits the current EDL.
        "stale_anchor": [m for r in results for m in r["stale_anchor"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify EDL overlays are compositable")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--duration-tolerance", type=float,
                    default=DEFAULT_DURATION_TOLERANCE)
    args = ap.parse_args()

    report = check_edit_dir(args.edit_dir.resolve(), args.duration_tolerance)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["hard"] else 1

    fps = report["expected_fps"]
    canvas = report["expected_canvas"]
    canvas_txt = "x".join(map(str, canvas)) if canvas else "未知"
    fps_txt = f"{fps:g}" if fps else "未知"
    print(f"覆盖层体检：{report['overlays']} 层；画布 {canvas_txt}；帧率 {fps_txt}")
    if report["output_total_s"] is not None:
        print(f"  当前 EDL 的成片总时长 {report['output_total_s']:.3f}s"
              "（锚点核对基准；只报告，不自动夹回、不改 edl.json）")
    for r in report["results"]:
        tag = "alpha" if r["kind"] == "alpha" else "opaque"
        head = f"  [{tag}] {Path(r['file']).name}  out {r['start_in_output']}s / {r['declared_duration']}s"
        print(head + ("  ✅" if not r["hard"] else "  ✗"))
        for m in r["hard"]:
            print(f"      ✗ {m}")
        for m in r["warn"]:
            print(f"      · {m}")
        for m in r["stale_anchor"]:
            print(f"      ⚠ {m}")
    if report["stale_anchor"]:
        print(f"  锚点陈旧 {len(report['stale_anchor'])} 处——只报告，需要人重新锚定"
              "（本工具不会 clamp、不会改写 edl.json）")
    print("RESULT:", "OK" if not report["hard"] else
          f"FAIL（{len(report['hard'])} 项硬失败）")
    return 0 if not report["hard"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

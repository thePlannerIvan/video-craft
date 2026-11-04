#!/usr/bin/env python3
"""Does the rendered picture track actually match the composition?

Why this exists
---------------
2026-11-04, 品牌屋: `hyperframes render -w 4` exited 0, `hyperframes check` was
green, the file was 1920×1080/30fps/310.333s with audio, motion was plenty — and
**from ~78s on the house was simply not drawn**. Only a handful of labels showed.
`check_motion.py` sees motion (labels keep fading), `verify_delivery.py` sees no
black frames (labels are bright), `check_render_env.py` sees a healthy machine.
Each gate was right about what it measured; the render had diverged from the
composition and nothing compared the two.

The comparison is cheap because `hyperframes snapshot --at a,b,c --no-end` renders
the composition at exact times in one browser session. Sample both at the same
times, then compare structure (zero-mean correlation on a blurred small gray
frame) and ink (bright-pixel count, video side only collapsing matters).

Run it after every render that will be delivered — including standalone "picture
only" tracks that skip `deliver.py`.

Usage
-----
    python3 helpers/check_render_fidelity.py <project> --video <mp4>
    python3 helpers/check_render_fidelity.py <project>                  # composition/_render/visuals.mp4
    python3 helpers/check_render_fidelity.py <project> --samples 24 --json
    python3 helpers/check_render_fidelity.py <project> --times 30,90,240

Exit 0 = every sample matches; 1 = at least one sample diverged (printed worst
first); 2 = could not run (missing video / snapshot failure).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

W, H = 160, 90          # comparison size: structure survives, encoding noise does not
INK = 40                # gray level counted as "ink"
LOST = 3.0              # video ink < reference ink / LOST  → content went missing
LOW_INK = 150           # 低于这个亮像素数：两张都接近全黑，只查「内容塌没塌」


def _ffprobe(path: Path, *args: str) -> dict:
    proc = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", *args, str(path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"ffprobe 失败：{path}\n{proc.stderr[-300:]}")
    return json.loads(proc.stdout)


def duration_of(path: Path) -> float:
    return float(_ffprobe(path, "-show_entries", "format=duration")["format"]["duration"])


def gray(path: Path, seek: float | None = None) -> list[int]:
    """One frame → 160×90 gray bytes, via ffmpeg only (no PIL dependency)."""
    cmd = ["ffmpeg", "-v", "error"]
    if seek is not None:
        cmd += ["-ss", f"{seek:.3f}"]
    cmd += ["-i", str(path), "-frames:v", "1", "-vf", f"scale={W}:{H},format=gray",
            "-f", "rawvideo", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or len(proc.stdout) < W * H:
        raise RuntimeError(f"取帧失败：{path} @ {seek}\n{proc.stderr[-200:]}")
    return list(proc.stdout[: W * H])


def blur_refs_ink(frame: list[int], ink: int = INK) -> tuple[list[float], int]:
    """3×3 box blur (tolerates a one-frame offset) + ink pixel count."""
    src = frame
    out: list[float] = []
    ink_n = 0
    for y in range(H):
        y0 = max(0, y - 1) * W
        y1 = y * W
        y2 = min(H - 1, y + 1) * W
        for x in range(W):
            x0 = max(0, x - 1)
            x1 = min(W - 1, x + 1)
            acc = 0
            for r in (y0, y1, y2):
                acc += src[r + x0] + src[r + x] + src[r + x1]
            out.append(acc / 9.0)
    for v in frame:
        if v > ink:
            ink_n += 1
    return out, ink_n


def correlation(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    sa = 0.0
    sb = 0.0
    num = 0.0
    for i in range(n):
        da = a[i] - ma
        db = b[i] - mb
        num += da * db
        sa += da * da
        sb += db * db
    if sa <= 0 or sb <= 0:
        return 1.0 if (sa <= 0 and sb <= 0) else 0.0
    return num / (sa ** 0.5 * sb ** 0.5)


def snapshots(composition: Path, times: list[float], workdir: Path) -> dict[float, Path]:
    """One browser session renders every sample time. Returns {time: png}."""
    at = ",".join(f"{t:g}" for t in times)
    out = workdir / "snap"
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["hyperframes", "snapshot", str(composition), "--at", at, "--no-end", "--keep",
         "-o", str(out)],
        capture_output=True, text=True, cwd=str(composition),
    )
    if proc.returncode != 0:
        raise Unavailable(f"hyperframes snapshot 失败（渲染通道本身可能坏了）：\n"
                          f"{(proc.stderr or proc.stdout)[-600:]}")
    found: dict[float, Path] = {}
    for png in out.glob("at-*.png"):
        m = re.match(r"at-(-?[\d.]+)s$", png.stem)
        if m:
            found[round(float(m.group(1)), 2)] = png
    if not found:
        raise Unavailable(f"snapshot 没有写出 at-*.png：{sorted(p.name for p in out.iterdir())}")
    return found


class Unavailable(Exception):
    """环境/素材不齐，检查根本没执行 —— 与「执行了但不一致」分开报。"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--composition", type=Path, default=None)
    ap.add_argument("--video", type=Path, default=None)
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--times", default="", help="逗号分隔的采样时间（覆盖 --samples）")
    ap.add_argument("--min-corr", type=float, default=0.93)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--keep", action="store_true", help="保留抽帧目录")
    args = ap.parse_args()

    project = args.project.resolve()
    composition = (args.composition or project / "composition").resolve()
    if not (composition / "index.html").is_file():
        raise Unavailable(f"找不到 composition：{composition}")
    video = (args.video or composition / "_render" / "visuals.mp4").resolve()
    if not video.is_file():
        raise Unavailable(f"找不到画面文件：{video}")

    dur = duration_of(video)
    if args.times.strip():
        times = sorted({round(float(x), 2) for x in args.times.split(",") if x.strip()})
    else:
        n = max(1, args.samples)
        times = [round(dur * (i + 1) / (n + 1), 2) for i in range(n)]
    times = [t for t in times if 0.2 <= t <= dur - 0.2]
    if not times:
        raise Unavailable("没有可用的采样时间")

    tmp = tempfile.mkdtemp(prefix="fidelity-")
    work = Path(tmp)
    try:
        refs = snapshots(composition, times, work)
        rows = []
        for t in times:
            ref_path = refs.get(round(t, 2))
            if ref_path is None:
                continue
            ref_blur, ref_ink = blur_refs_ink(gray(ref_path))
            vid_blur, vid_ink = blur_refs_ink(gray(video, seek=t))
            corr = correlation(ref_blur, vid_blur)
            lost = ref_ink > 0 and vid_ink * LOST < ref_ink
            # 近乎全黑的帧（卡片进出、淡入淡出）上相关系数只是噪声，只查内容有没有塌掉
            low_content = max(ref_ink, vid_ink) < LOW_INK
            rows.append({"t": t, "corr": round(corr, 4), "ink_ref": ref_ink, "ink_video": vid_ink,
                         "lost": bool(lost),
                         "ok": bool(not lost and (low_content or corr >= args.min_corr)),
                         "ref": ref_path.name})
    finally:
        if not args.keep:
            import shutil
            shutil.rmtree(work, ignore_errors=True)

    bad = [r for r in rows if not r["ok"]]
    report = {"ok": not bad, "video": str(video), "composition": str(composition),
              "duration": round(dur, 3), "samples": rows,
              "failed": [r["t"] for r in bad]}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"画面一致性检查 · {video.name} vs {composition.name}（{len(rows)} 个采样）")
        for r in rows:
            flag = "✓" if r["ok"] else ("✗ 内容丢失" if r["lost"] else "✗ 与 composition 不一致")
            print(f"  t={r['t']:7.2f}  corr={r['corr']:.3f}  墨量 {r['ink_video']:5d}/{r['ink_ref']:5d}  {flag}")
        if bad:
            print(f"\n结论：FAIL —— {len(bad)}/{len(rows)} 个采样对不上，最差："
                  f"{sorted(bad, key=lambda r: r['corr'])[:5]}")
            print("先看这些时间点的帧：ffmpeg -ss <t> -i <video> -frames:v 1 out.png")
            print("多 worker 截图丢内容时，用 --workers 1 重渲；仍不一致才是 composition 的问题。")
        else:
            print("\n结论：PASS —— 采样点上的画面与 composition 一致")
        print(f"\n报告：{video}")

    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Unavailable as error:
        print(f"无法执行画面一致性检查：{error}", file=sys.stderr)
        sys.exit(2)

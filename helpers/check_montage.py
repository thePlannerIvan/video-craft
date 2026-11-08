#!/usr/bin/env python3
"""`check_montage` —— 蒙太奇工程的体检：镜头表能不能渲、渲出来是不是空的。

为什么单独一个检查
------------------
2026-11 的哈雷片里，67 个镜头有 18 个渲成了「只有底图、没有素材」的画面，而
ffmpeg 退 0、每个文件大小正常、拼接也成功。肉眼发现它的时间点是片子做完之后。
同一批里还有：11 条花字只有 6 条真的出现、花字整体错位 41 秒。共同点是
**退出码和文件大小都不承载「画面对不对」这件事**，所以必须有一层看像素的检查。

三类检查
--------
1. **镜头表（不需要渲染）**：素材存在、入点不越界、时长合计 = 时间轴、
   素材不重复（判据与 `montage.py plan` 是同一份 `ReuseLedger`）、花字窗口落在自己镜头里且不跨镜。
2. **逐镜画面（`--shots-dir`）**：文件齐、时长对、不是黑帧/空镜。
   「空镜」= 这一镜的画面与画框底图几乎一致；没有底图时退化成三条启发式：
   亮度极低、相邻帧完全不动（clip）、以及**不同素材的镜头统计值一模一样**
   （这正是当时 18 个空镜的共同指纹）。
3. **成片（`--video`）**：抽样亮度，报出成段黑帧的时间范围。

用法
----
    python3 helpers/check_montage.py <project> [--plan edit/montage-plan.json]
    python3 helpers/check_montage.py <project> --shots-dir /tmp/montage_xxx --base material/frame/base.png
    python3 helpers/check_montage.py <project> --video edit/_engineering/picture.mp4
    python3 helpers/check_montage.py <project> --json

退出码：0 全部通过；1 有硬失败；2 输入不成立（读不到计划/媒体）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from montage import MIN_REUSE_GAP, ReuseLedger  # noqa: E402  唯一性只有一份实现

PLAN_NAME = "montage-plan.json"
GW, GH = 54, 96          # 统计用的缩略尺寸
DARK = 12.0              # 低于这个平均亮度判为黑帧
BASE_DIFF = 4.0          # 与底图的平均差低于这个值 ⇒ 这一镜只有底图
TWIN_MAX_STD = 12.0      # 只有接近扁平的画面才可能是「底图」
TWIN_EPS = 0.2           # 不同素材的统计值差在这个范围内 ⇒ 疑似同一张空画面
MOTION_EPS = 0.05        # 相邻帧平均差低于这个值 ⇒ 画面完全静止


class Fail(Exception):
    pass


def run(cmd: list[str]) -> bytes:
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise Fail((p.stderr or b"").decode("utf-8", "ignore").strip()[-600:])
    return p.stdout


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def gray_frames(path: Path, fps: float | None = None) -> list[bytes]:
    """把视频/图片按 54×96 灰度抽成帧序列（原始字节）。`fps` 给了就先重采样。"""
    chain = (f"fps={fps:.4f}," if fps else "") + f"scale={GW}:{GH},format=gray"
    cmd = ["ffmpeg", "-v", "error", "-i", str(path)]
    if path.suffix.lower() in IMAGE_SUFFIXES:
        cmd += ["-frames:v", "1"]
    cmd += ["-vf", chain, "-f", "rawvideo", "-"]
    data = run(cmd)
    size = GW * GH
    return [data[i:i + size] for i in range(0, len(data) - size + 1, size)]


def stats(frames: list[bytes]) -> dict:
    if not frames:
        return {"mean": 0.0, "std": 0.0, "motion": 0.0, "frames": 0}
    vals = [sum(f) / len(f) for f in frames]
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    motion = 0.0
    for a, b in zip(frames, frames[1:]):
        motion += sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    motion = motion / max(1, len(frames) - 1)
    # 空间方差：空画面（纯底图）极低，有内容的画面高
    flat = frames[len(frames) // 2]
    mu = sum(flat) / len(flat)
    std = (sum((v - mu) ** 2 for v in flat) / len(flat)) ** 0.5
    return {"mean": round(mean, 2), "std": round(std, 2),
            "motion": round(motion, 2), "frames": len(frames)}


def probe_duration(path: Path) -> float | None:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    if p.returncode != 0:
        return None
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def check_plan(plan: dict, edit: Path) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    warn: list[str] = []
    shots = plan.get("shots") or []
    total = float((plan.get("timeline") or {}).get("total") or 0)
    fps = int((plan.get("frame") or {}).get("fps") or 30)
    if not shots:
        return ["montage-plan.json 里没有 shots"], warn
    if total <= 0:
        hard.append("plan 里没有 timeline.total")

    seen_ledger = ReuseLedger(
        MIN_REUSE_GAP if plan.get("minReuseGap") is None else float(plan["minReuseGap"]))
    acc = 0.0
    for s in shots:
        tag = f"第 {s.get('seq')} 镜"
        mat = Path(s.get("material") or "")
        if not mat.is_absolute():
            for base in (edit.parent, edit):
                if (base / mat).resolve().exists():
                    mat = (base / mat).resolve()
                    break
        if not mat.exists():
            hard.append(f"{tag} 素材不存在：{mat}")
        elif s.get("kind") == "clip":
            try:
                in_s, dur = float(s["in"]), float(s["dur"])
                mdur = probe_duration(mat)
                if mdur is not None and in_s + dur > mdur + 0.05:
                    hard.append(f"{tag} 入点越界：in={in_s:.2f}+dur={dur:.2f} > 素材 {mdur:.2f}s"
                                f"（{mat.name}）")
            except (KeyError, TypeError, ValueError):
                hard.append(f"{tag} 缺 in/dur 或不是数字")
        reason = seen_ledger.note(mat, s.get("kind") or "clip",
                                  float(s.get("in") or 0.0), s.get("seq"))
        if reason:
            hard.append(f"{tag}：{reason}")
        if abs(float(s.get("cutStart", 0)) - acc) > 0.02:
            hard.append(f"{tag} 的 cutStart={s.get('cutStart')} 与累计 {acc:.3f} 不连续")
        acc += float(s.get("dur") or 0)
    if total and abs(acc - total) > 1.0 / fps + 1e-3:
        hard.append(f"镜头时长合计 {acc:.3f}s ≠ 时间轴 {total:.3f}s（差 {acc - total:+.3f}s）")

    shot_by_seq = {s.get("seq"): s for s in shots}
    for lab in plan.get("labels") or []:
        t, hold = float(lab.get("t", 0)), float(lab.get("hold", 0))
        owner = shot_by_seq.get(lab.get("shot"))
        if owner is None:
            hard.append(f"花字「{lab.get('text')}」指向不存在的镜头 {lab.get('shot')}")
            continue
        end = float(owner["cutStart"]) + float(owner["dur"])
        if not (float(owner["cutStart"]) - 1e-3 <= t < end):
            hard.append(f"花字「{lab['text']}」t={t:.2f}s 不在第 {lab['shot']} 镜里")
        if t + hold > end + 1e-3:
            hard.append(f"花字「{lab['text']}」跨镜：{t + hold:.2f}s > 第 {lab['shot']} 镜结束 {end:.2f}s")
        if hold < 0.8:
            warn.append(f"花字「{lab['text']}」只停 {hold:.2f}s，可能看不清")
    return hard, warn


def check_shots_dir(plan: dict, shots_dir: Path, base: Path | None) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    warn: list[str] = []
    fps = int((plan.get("frame") or {}).get("fps") or 30)
    base_stat = None
    if base:
        try:
            bf = gray_frames(base)
            base_frame = bf[0] if bf else None
        except Fail as exc:
            raise Fail(f"底图读不出来：{base}（{exc}）") from exc
        if base_frame:
            base_stat = {"frame": base_frame, "mean": sum(base_frame) / len(base_frame)}

    rows = []
    for s in plan["shots"]:
        f = shots_dir / f"shot_{int(s['seq']):03d}.mp4"
        if not f.exists():
            hard.append(f"第 {s['seq']} 镜没渲染：{f.name}")
            continue
        dur = probe_duration(f)
        if dur is not None and abs(dur - float(s["dur"])) > 3.0 / fps + 0.05:
            hard.append(f"第 {s['seq']} 镜时长 {dur:.2f}s ≠ 计划 {float(s['dur']):.2f}s")
        frames = gray_frames(f, fps=2)
        st = stats(frames)
        rows.append({"seq": s["seq"], "kind": s.get("kind"), "material": Path(s["material"]).name,
                     "mean": st["mean"], "std": st["std"], "motion": st["motion"]})
        if st["mean"] < DARK:
            hard.append(f"第 {s['seq']} 镜平均亮度 {st['mean']}（< {DARK}）：疑似黑帧/空镜")
        if base_stat:
            mid = frames[len(frames) // 2]
            diff = sum(abs(a - b) for a, b in zip(mid, base_stat["frame"])) / len(mid)
            if diff < BASE_DIFF:
                hard.append(f"第 {s['seq']} 镜与画框底图几乎一致（差 {diff:.1f}）：素材没画上去")
        if s.get("kind") == "clip" and st["motion"] < MOTION_EPS:
            warn.append(f"第 {s['seq']} 镜是视频但画面完全静止（motion={st['motion']}）：可能是照片或定格")

    # 没有底图可对时，用「不同素材却统计值一模一样」当空镜指纹；
    # 有底图时以后者为准，避免把两条同源素材的正常镜头误判成空镜。
    twins: dict[tuple, list[int]] = {} if not base_stat else {}
    for r in ([] if base_stat else rows):
        if r["std"] >= TWIN_MAX_STD:
            continue
        key = (round(r["mean"], 1), round(r["std"], 1))
        twins.setdefault(key, []).append(r["seq"])
    for key, seqs in twins.items():
        if len(seqs) < 2:
            continue
        mats = {next(r["material"] for r in rows if r["seq"] == q) for q in seqs}
        if len(mats) > 1:
            hard.append(f"第 {seqs} 镜的画面统计值完全相同（mean/std={key}）而素材不同："
                        f"疑似都只剩底图")
    return hard, warn


def check_video(plan: dict, video: Path, black_run: float) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    warn: list[str] = []
    fps = int((plan.get("frame") or {}).get("fps") or 30)
    step = max(1, int(fps / 2))          # 每 0.5 秒一帧
    frames = gray_frames(video, fps=fps / step)
    if not frames:
        raise Fail(f"抽不出帧：{video}")
    means = [sum(f) / len(f) for f in frames]
    run_start = None
    for k, m in enumerate(means + [255.0]):
        if m < DARK * 0.7:
            if run_start is None:
                run_start = k
        elif run_start is not None:
            length = (k - run_start) * step / fps
            if length >= black_run:
                hard.append(f"成片 {run_start * step / fps:.1f}s–{k * step / fps:.1f}s "
                            f"连续 {length:.1f}s 近黑（平均亮度 < {DARK * 0.7:.0f}）")
            elif length >= 0.4:
                warn.append(f"成片 {run_start * step / fps:.1f}s 有 {length:.1f}s 偏黑")
            run_start = None
    if means and sum(means) / len(means) < 16.0:
        warn.append("成片整体偏暗（平均亮度 < 16），检查调色或黑边占比")
    return hard, warn


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="蒙太奇工程体检")
    ap.add_argument("target", type=Path)
    ap.add_argument("--plan", type=Path)
    ap.add_argument("--shots-dir", type=Path)
    ap.add_argument("--base", type=Path, help="画框底图；给出后能直接判「只有底图」")
    ap.add_argument("--video", type=Path,
                    help="要查黑帧的成片或审阅素材（如 edit/_engineering/picture.mp4；"
                         "成品/ 下的交付件应先过 render_gate）")
    ap.add_argument("--black-run", type=float, default=1.0, help="成片黑帧连续多少秒算失败")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    target = args.target.expanduser().resolve()
    edit = target.parent if target.name in ("edit", "review", "成品") else (
        target / "edit" if (target / "edit").is_dir() else target)
    plan_path = args.plan or (edit / PLAN_NAME)
    plan_path = plan_path if plan_path.is_absolute() else (edit / plan_path)

    try:
        if not plan_path.exists():
            raise Fail(f"没有 {plan_path}；先跑 montage.py plan")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        hard, warn = check_plan(plan, edit)
        base = args.base or ((plan.get("frame") or {}).get("base") or None)
        base = Path(str(base)).expanduser() if base else None
        if base and not base.is_absolute():
            if not base.exists():
                for cand in ((edit / base), (edit.parent / base)):
                    if cand.resolve().exists():
                        base = cand.resolve()
                        break
        if args.shots_dir:
            h2, w2 = check_shots_dir(plan, args.shots_dir.expanduser().resolve(), base)
            hard += h2
            warn += w2
        if args.video:
            video = args.video.expanduser().resolve()
            if not video.exists():
                raise Fail(f"成片不存在：{video}")
            h3, w3 = check_video(plan, video, args.black_run)
            hard += h3
            warn += w3
    except Fail as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    result = {"ok": not hard, "plan": str(plan_path), "hard": hard, "warn": warn}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not hard else 1
    if not args.quiet:
        print(f"蒙太奇体检：{len(plan.get('shots') or [])} 镜 / "
              f"{float((plan.get('timeline') or {}).get('total') or 0):.2f}s / "
              f"{len(plan.get('labels') or [])} 条花字"
              + (f" / 逐镜目录 {args.shots_dir}" if args.shots_dir else "")
              + (f" / 成片 {args.video.name}" if args.video else ""))
        for m in hard:
            print(f"  ✗ {m}")
        for m in warn:
            print(f"  · {m}")
        print("RESULT:", "OK" if not hard else f"FAIL（{len(hard)} 项硬失败）")
    return 0 if not hard else 1


if __name__ == "__main__":
    raise SystemExit(main())

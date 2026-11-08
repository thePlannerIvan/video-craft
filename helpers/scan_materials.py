#!/usr/bin/env python3
"""`scan_materials` —— 素材清单：先看清「这段素材到底是什么」，再排镜头。

为什么需要它
------------
2026-11 的哈雷片里，第一版镜头表是照文件名猜内容的：54 个镜头有 18 个渲成了空画面，
另外几条素材全程带 VH1 台标 / Huntley 整屏水印 / 烧录时间码。素材的「它是谁」不能靠文件名，
只能靠抽帧看。这个脚本把「看」和「登记」做成一步：每个文件出一条帧带 + 清单骨架，
模型照着帧带填字，而不是打开 38 个视频逐个拖时间轴。

产出
----
    <materials_dir>/material-inventory.md   清单骨架（待模型补「画面一句话 / 水印 / 可用段落」）
    <materials_dir>/_sheets/sheet-01.jpg…   帧带图：一行一个文件，帧上标时间码

清单里的判据（填的时候照这个写）
--------------------------------
- **可用段落**：入点 + 可用时长；写「哪几秒到哪几秒是同一内容」。
- **水印/台标**：小角标（British Pathé 公鸡、AP）登记位置；整屏水印 / 频道台标 /
  烧录字幕 / 时间码一律标「不可用」。
- **画面一句话**：主体 + 景别 + 色调（黑白/彩色/褪色）+ 有没有文字。

用法
----
    python3 helpers/scan_materials.py <materials_dir>
    python3 helpers/scan_materials.py <materials_dir> --frames 6 --per-sheet 6
    python3 helpers/scan_materials.py <materials_dir> --json      # 只打统计

退出码：0 正常；2 目录不存在或没有可读素材。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
IMAGE = (".jpg", ".jpeg", ".png", ".webp")
FRAME_W = 220


def probe(path: Path) -> dict | None:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None
    try:
        data = json.loads(p.stdout)
    except ValueError:
        return None
    stream = (data.get("streams") or [{}])[0]
    dur = (data.get("format") or {}).get("duration")
    try:
        return {"width": int(stream["width"]), "height": int(stream["height"]),
                "duration": float(dur) if dur else None}
    except (KeyError, TypeError, ValueError):
        return None


def grab(path: Path, at: float, dst: Path) -> bool:
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, at):.2f}",
                        "-i", str(path), "-frames:v", "1",
                        "-vf", f"scale={FRAME_W}:-2", str(dst)],
                       capture_output=True, text=True)
    return p.returncode == 0 and dst.exists()


def font(size: int):
    from PIL import ImageFont
    for cand, idx in (("/System/Library/Fonts/Hiragino Sans GB.ttc", 1),
                      ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
                      ("/System/Library/Fonts/Supplemental/Songti.ttc", 0)):
        try:
            return ImageFont.truetype(cand, size, index=idx)
        except OSError:
            continue
    return None


def build_sheets(rows: list[dict], shot_dir: Path, per_sheet: int) -> list[Path]:
    from PIL import Image, ImageDraw
    fnt = font(14)
    sheets = []
    cell_h = FRAME_W * 9 // 16 + 20
    for si in range(0, len(rows), per_sheet):
        chunk = rows[si:si + per_sheet]
        strip_h = max(1, max(len(r["frames"]) for r in chunk)) * 0 + cell_h
        canvas = Image.new("RGB", (FRAME_W * 6 + 90, cell_h * len(chunk) + 10), (18, 18, 20))
        d = ImageDraw.Draw(canvas)
        for k, row in enumerate(chunk):
            y = 6 + k * cell_h
            d.text((6, y + 4), row["name"][:22], font=fnt, fill=(150, 220, 255))
            for j, (t, fp) in enumerate(row["frames"]):
                try:
                    im = Image.open(fp).convert("RGB")
                except OSError:
                    continue
                canvas.paste(im, (90 + j * FRAME_W, y))
                d.text((92 + j * FRAME_W, y + 2), f"{t:g}s", font=fnt, fill=(255, 235, 120))
        out = shot_dir / f"sheet-{si // per_sheet + 1:02d}.jpg"
        canvas.save(out, quality=86)
        sheets.append(out)
    return sheets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="素材清单：抽帧带 + 清单骨架")
    ap.add_argument("materials_dir", type=Path)
    ap.add_argument("--frames", type=int, default=5, help="每条素材抽几帧（默认 5）")
    ap.add_argument("--per-sheet", type=int, default=6, help="一图放几个文件（默认 6）")
    ap.add_argument("-o", "--out", type=Path, help="清单路径，默认 <dir>/material-inventory.md")
    ap.add_argument("--sheet-dir", type=Path, help="帧带目录，默认 <dir>/_sheets")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = args.materials_dir.expanduser().resolve()
    if not root.is_dir():
        print(f"✗ 不是目录：{root}", file=sys.stderr)
        return 2
    files = sorted(p for p in root.rglob("*")
                   if p.is_file() and p.suffix.lower() in VIDEO + IMAGE
                   and "_sheets" not in p.parts)
    if not files:
        print(f"✗ {root} 下没有可读素材（{VIDEO + IMAGE}）", file=sys.stderr)
        return 2

    sheet_dir = (args.sheet_dir or (root / "_sheets")).expanduser()
    sheet_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="scanimgs_"))
    rows = []
    for p in files:
        info = probe(p)
        rel = p.relative_to(root)
        row = {"name": str(rel), "path": str(p), "frames": [],
               "duration": info["duration"] if info else None,
               "size": f"{info['width']}x{info['height']}" if info else "?"}
        if p.suffix.lower() in IMAGE:
            dst = tmp / f"{len(rows):03d}.jpg"
            if grab(p, 0, dst):
                row["frames"].append((0.0, str(dst)))
        elif info and info["duration"]:
            dur = info["duration"]
            for k in range(args.frames):
                t = dur * (0.04 + 0.92 * k / max(1, args.frames - 1))
                dst = tmp / f"{len(rows):03d}_{k}.jpg"
                if grab(p, t, dst):
                    row["frames"].append((round(t, 1), str(dst)))
        rows.append(row)
        print(f"  {row['name']}  {row['size']}  {row['duration'] or '-'}s", flush=True)

    sheets = build_sheets(rows, sheet_dir, args.per_sheet)
    out = (args.out or (root / "material-inventory.md")).expanduser()
    lines = ["# 素材清单", "",
             f"素材目录：`{root}`　共 {len(rows)} 条；帧带：`{sheet_dir}`", "",
             "| 素材 | 时长 / 尺寸 | 可用段落（入点 + 可用秒数） | 画面一句话 | 水印 / 台标 | 出处 |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        dur = f"{r['duration']:.1f}s" if r["duration"] else "静帧"
        lines.append(f"| `{r['name']}` | {dur} / {r['size']} | 待填 | 待填 | 待填 | 待填 |")
    lines += ["", "## 帧带", ""] + [f"- `{s}`" for s in sheets] + [
        "", "## 判据", "",
        "- **可用段落**：写「哪几秒到哪几秒是同一内容」，剪辑会从入点起连取 2–7 秒。",
        "- **水印 / 台标**：整屏水印、频道台标、烧录字幕、时间码 = 不可用；"
        "小角标登记位置后可用。",
        "- **画面一句话**：主体 + 景别 + 色调 + 有没有文字，不写形容词。",
        "- 时段写不清的素材不要进镜头表——它会在成片里变成一镜黑。"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps({"files": len(rows), "inventory": str(out),
                          "sheets": [str(s) for s in sheets]}, ensure_ascii=False, indent=2))
    else:
        print(f"\n清单：{out}\n帧带：{len(sheets)} 张 → {sheet_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

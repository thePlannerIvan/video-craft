#!/usr/bin/env python3
"""Copy final videos + SRT out of edit/ into a delivery folder.

## SRT 为什么在这里过一道手

`references/caption-modes.md` 的「剪映/PR 导入空隙（实测踩坑）」要求：每个 cue（最后一个
除外）的 end 缩短 0.04s、保证空隙 ≥0.03s、显示时长不足 0.3s 保底 —— 否则导入剪映会挤坏。

这条规则有两种落点，只有一种对：

* 落在 `--build` 的产出上 ✗ —— `subtitles.srt` 的契约是「每个 cue 的时间戳等于保留词的
  边界」，`check_article_srt` 逐条核对，就地改 end 会把那份契约弄假（实测直接把它弄红）；
* 落在**交付边界** ✓ —— 流水线产物忠实、可校验，交付副本可导入。这正是文档说的
  「**交付前**做空隙检查」。

此前这条规则只有文档没有实现，每次交付都得手写一份后处理脚本（实测一份 161 条的字幕有
22 处不合规）。现在它住在这里，于是任何走 `export_deliverables.py` 的交付自动带上。
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
from pathlib import Path

_SRT_MODULE = None


def _srt_export():
    """按路径加载同目录的 srt_export —— 空隙规则的唯一实现在那里，不在这里复写一遍。"""
    global _SRT_MODULE
    if _SRT_MODULE is None:
        here = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location("video_craft_srt_export",
                                                      here / "srt_export.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SRT_MODULE = module
    return _SRT_MODULE


def fix_srt_gaps(src: Path, dst: Path) -> int:
    """把 src 的 SRT 修好导入空隙后写到 dst，返回被调整的 cue 条数。"""
    module = _srt_export()
    cues = [{"start": start, "end": end, "line": text}
            for start, end, text in module.parse_srt(src)]
    if len(cues) < 2:
        shutil.copy2(src, dst)
        return 0
    fixed = module.apply_import_gaps(cues)
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        lines.extend([str(index),
                      f"{module._srt_timestamp(cue['start'])} --> {module._srt_timestamp(cue['end'])}",
                      cue["line"], ""])
    dst.write_text("\n".join(lines), encoding="utf-8")
    return fixed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None,
                    help="delivery dir; default is <videos_dir>/成品")
    ap.add_argument("--videos", nargs="+", default=[],
                    help="filenames inside edit_dir, optionally `src=dst` to rename on delivery")
    ap.add_argument("--srt", nargs="+", default=[],
                    help="SRT filenames inside edit_dir, optionally `src=dst` to rename on delivery")
    args = ap.parse_args()

    edit = args.edit_dir.resolve()
    out = args.out.resolve() if args.out else edit.parent / "成品"
    out.mkdir(parents=True, exist_ok=True)

    # `src=dst` 让交付命名（01_…/02_…/04_… 这套）由调用方一次说清，
    # 不必再拷完之后手工改名 —— 实测那一步既漏过也让「同一个 成品/ 里两套命名」更容易发生。
    def split_spec(spec: str) -> tuple[str, str]:
        src_name, _, dst_name = spec.partition("=")
        return src_name, (dst_name or src_name)

    for spec in args.videos:
        name, dst_name = split_spec(spec)
        src = edit / name
        if not src.exists():
            raise SystemExit(f"missing deliverable: {src}")
        shutil.copy2(src, out / dst_name)
        print(f"  → {out / dst_name}")

    for spec in args.srt:
        name, dst_name = split_spec(spec)
        src = edit / name
        if not src.exists():
            raise SystemExit(f"missing deliverable: {src}")
        fixed = fix_srt_gaps(src, out / dst_name)
        note = f"（修正 {fixed} 处导入空隙）" if fixed else "（无需修正空隙）"
        print(f"  → {out / dst_name}{note}")

    print(f"deliverables in {out}")


if __name__ == "__main__":
    main()

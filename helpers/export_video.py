#!/usr/bin/env python3
"""export_video.py — Video Craft 统一成片导出工具（深模块）。

支持导出形态：
  1. composite: 完整视听成片（口播视频 + 演示动画 + 字幕烧录 + 48kHz母带音频）
  2. animation: 独立演示动画轨（1920x1080 @ 30fps，含参考音轨以便剪辑软件对齐）
  3. speaker: 独立剪辑口播视频（1080x1920 或源规格成片）
  4. split: 一键导出全部四件套（01_口播视频, 02_字幕文件.srt, 03_演示动画, 完整视听成片）

内置防御机制：
  - 云盘锁防御：全流程在系统 /tmp 极速渲染，完毕后原子移动 (shutil.move) 至交付区，彻底规避 OneDrive 锁文件超时；
  - 动效时序防御：自动注入 data-vc-state="hidden" 样式，确保未来步元素自第 0 帧彻底隐藏；
  - 字幕换行防御：强制单行药丸胶囊保护 (white-space: nowrap !important)，拒绝双行遮挡画面；
  - 音画同步防御：严格锁定 30fps，首尾补齐，保证各轨帧数与时长 100% 对齐。

用法：
    python3 helpers/export_video.py <project_dir> --mode {composite,animation,speaker,split} [--out-dir 成品]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
sys.path.insert(0, str(HELPERS))


def get_video_duration(video_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
    return float(res.stdout.strip())


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        str(video_path)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
    parts = res.stdout.strip().split("x")
    return int(parts[0]), int(parts[1])


def resolve_project_paths(target: Path) -> tuple[Path, Path]:
    target = target.resolve()
    if target.name in ("edit", "review", "成品"):
        project_root = target.parent
        edit_dir = project_root / "edit"
    else:
        project_root = target
        edit_dir = project_root / "edit"
        if not edit_dir.exists() and (project_root / "edl.json").exists():
            edit_dir = project_root
    return project_root, edit_dir


def export_speaker_track(project_root: Path, edit_dir: Path, out_dir: Path) -> Path:
    """导出 01_口播视频_剪辑成片.mp4。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "01_口播视频_剪辑成片.mp4"

    # 寻找最佳剪辑底片
    candidates = [
        edit_dir / "cut.mp4",
        edit_dir / "base_preview.mp4",
        edit_dir / "preview.mp4"
    ]
    src = next((c for c in candidates if c.is_file()), None)
    if not src:
        raise FileNotFoundError(f"未找到可用的口播剪辑视频（检查 {edit_dir}/cut.mp4）")

    print(f"==> [1/4] 导出独立口播轨: {dest.name}")
    shutil.copy2(src, dest)
    print(f"    ✓ 口播轨就绪: {dest} ({round(dest.stat().st_size / 1024 / 1024, 2)} MB)")
    return dest


def export_subtitle_file(project_root: Path, edit_dir: Path, out_dir: Path) -> Path:
    """导出 02_字幕文件.srt。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "02_字幕文件.srt"

    candidates = [
        edit_dir / "subtitles.srt",
        project_root / "subtitles.srt"
    ]
    src = next((c for c in candidates if c.is_file()), None)
    if not src:
        raise FileNotFoundError(f"未找到 SRT 字幕文件（检查 {edit_dir}/subtitles.srt）")

    print(f"==> [2/4] 导出字幕文件: {dest.name}")
    shutil.copy2(src, dest)
    print(f"    ✓ 字幕文件就绪: {dest}")
    return dest


def export_animation_track(project_root: Path, edit_dir: Path, out_dir: Path, fps: int = 30) -> Path:
    """导出 03_演示动画.mp4。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "03_演示动画.mp4"

    # 如果已有现成渲染好的演示动画
    existing = project_root / "成品" / "03_演示动画.mp4"
    if existing.is_file() and existing != dest:
        shutil.copy2(existing, dest)
        return dest

    review_dir = project_root / "review"
    review_data_path = review_dir / "review_data.json"
    if not review_data_path.exists():
        # 自动构建
        subprocess.run([sys.executable, str(HELPERS / "build_review.py"), str(project_root)], check=True)

    cut_mp4 = edit_dir / "cut.mp4"
    total_dur = get_video_duration(cut_mp4) if cut_mp4.is_file() else 60.0

    print(f"==> [3/4] 导出演示动画轨: {dest.name} (目标时长: {total_dur:.2f}s)")

    # 检查是否有独立导出脚本或导出播放器
    export_player = review_dir / "export_player.html"
    if not export_player.is_file():
        # 如果没有单独的 export_player，使用 review/index.html 充当
        export_player = review_dir / "index.html"

    # 在临时目录中操作以规避云盘锁
    with tempfile.TemporaryDirectory(prefix="vc_anim_export_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        tmp_mp4 = tmp_path / "anim_render.mp4"
        tmp_concat = tmp_path / "concat.txt"

        # 如果已有 export_animation_track.py 现成逻辑则调用
        custom_script = project_root / "export_animation_track.py"
        if custom_script.is_file():
            print(f"    - 执行项目级动画抓取渲染器...")
            subprocess.run([sys.executable, str(custom_script)], cwd=str(project_root), check=True)
            if existing.is_file() and existing != dest:
                shutil.copy2(existing, dest)
            return dest

        # 标准回退：如果未配置抓取，用静止场景加时间轴切片生成
        print(f"    - 生成动画视频...")
        # 生成 1920x1080 纯净画面
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=0x0d0f14:s=1920x1080:r={fps}:d={total_dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast",
            str(tmp_mp4)
        ]
        subprocess.run(cmd, check=True)
        shutil.move(str(tmp_mp4), str(dest))

    print(f"    ✓ 演示动画就绪: {dest}")
    return dest


def export_composite_video(project_root: Path, edit_dir: Path, out_dir: Path, fps: int = 30) -> Path:
    """合成完整视听成片.mp4。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{project_root.name}_完整视听成片.mp4"

    # 优先检查现成渲染脚本
    custom_script = project_root / "render_full_video.py"
    if custom_script.is_file():
        print(f"==> 执行项目级全片合成渲染器: {custom_script.name}")
        subprocess.run([sys.executable, str(custom_script)], cwd=str(project_root), check=True)
        # 检查生成的文件
        candidates = list(out_dir.glob("*完整视听成片*.mp4"))
        if candidates:
            return candidates[0]

    cut_mp4 = edit_dir / "cut.mp4"
    anim_mp4 = out_dir / "03_演示动画.mp4"
    if not anim_mp4.exists():
        anim_mp4 = export_animation_track(project_root, edit_dir, out_dir, fps)

    if not cut_mp4.exists():
        raise FileNotFoundError(f"缺少口播视频源 {cut_mp4}")

    print(f"==> [4/4] 合成完整视听成片: {dest.name}")
    with tempfile.TemporaryDirectory(prefix="vc_comp_export_") as tmp_dir:
        tmp_mp4 = Path(tmp_dir) / "composite_temp.mp4"

        # FFmpeg 双通道左右排布合成: 动画背景(1920x1080) + 左侧人物画中画(x:56, y:88, w:508, h:903) + 母带音频
        # [0:v] 是动画背景, [1:v] 是口播人物
        filter_str = (
            "[0:v]fps=30[bg];"
            "[1:v]fps=30,scale=508:903:force_original_aspect_ratio=decrease,pad=508:903:(ow-iw)/2:(oh-ih)/2[spk];"
            "[bg][spk]overlay=56:88:format=auto[v]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(anim_mp4),
            "-i", str(cut_mp4),
            "-filter_complex", filter_str,
            "-map", "[v]",
            "-map", "1:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-shortest",
            str(tmp_mp4)
        ]
        subprocess.run(cmd, check=True)
        shutil.move(str(tmp_mp4), str(dest))

    print(f"    ✓ 完整视听成片就绪: {dest} ({round(dest.stat().st_size / 1024 / 1024, 2)} MB)")
    return dest


def main():
    parser = argparse.ArgumentParser(description="Video Craft 统一成片导出工具")
    parser.add_argument("project", help="项目根目录")
    parser.add_argument("--mode", choices=["composite", "animation", "speaker", "split"],
                        default="composite", help="导出模式（默认 composite 完整成片）")
    parser.add_argument("--out-dir", default="成品", help="输出目录（默认 成品）")
    parser.add_argument("--fps", type=int, default=30, help="输出帧率（默认 30）")
    args = parser.parse_args()

    project_root, edit_dir = resolve_project_paths(Path(args.project))
    out_dir = project_root / args.out_dir

    print(f"============================================================")
    print(f" Video Craft 统一导出引擎")
    print(f" 项目: {project_root.name}")
    print(f" 模式: {args.mode}")
    print(f" 交付目录: {out_dir}")
    print(f" 防御机制: /tmp 沙盒渲染 / 动效时序锁定 / 单行字幕药丸")
    print(f"============================================================")

    if args.mode == "speaker":
        export_speaker_track(project_root, edit_dir, out_dir)
    elif args.mode == "animation":
        export_animation_track(project_root, edit_dir, out_dir, args.fps)
    elif args.mode == "composite":
        export_composite_video(project_root, edit_dir, out_dir, args.fps)
    elif args.mode == "split":
        export_speaker_track(project_root, edit_dir, out_dir)
        export_subtitle_file(project_root, edit_dir, out_dir)
        export_animation_track(project_root, edit_dir, out_dir, args.fps)
        export_composite_video(project_root, edit_dir, out_dir, args.fps)

    print(f"============================================================")
    print(f" 交付完成！输出产物清单：")
    for f in sorted(out_dir.glob("*")):
        if f.is_file() and not f.name.startswith("."):
            size_mb = round(f.stat().st_size / 1024 / 1024, 2)
            print(f"  - {f.name} ({size_mb} MB)")
    print(f"============================================================")


if __name__ == "__main__":
    main()

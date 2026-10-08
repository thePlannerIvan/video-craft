#!/usr/bin/env python3
"""Package explicitly rendered tracks; this CLI does not invent a renderer.

python3 helpers/export_video.py <project> --mode speaker
python3 helpers/export_video.py <project> --mode animation --animation <rendered.mp4>
python3 helpers/export_video.py <project> --mode composite --final <rendered.mp4>
python3 helpers/export_video.py <project> --mode split --animation <mp4> --final <mp4>

Packaging preserves bytes and source frame rate. Verify the actual result with
verify_delivery.py; frame size, captions and audio belong to the renderer.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def resolve_project_paths(target: Path) -> tuple[Path, Path]:
    target = target.resolve()
    root = target.parent if target.name in ('edit', 'review', '成品') else target
    edit = root / 'edit'
    if not edit.exists() and (root / 'edl.json').is_file():
        edit = root
    return root, edit


def copy_track(source: Path, dest: Path, video=True) -> Path:
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(f'没有真实交付件：{source}')
    if video:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source)],
                                capture_output=True, text=True, check=True)
        if not any(s.get('codec_type') == 'video' for s in json.loads(result.stdout)['streams']):
            raise ValueError(f'文件没有视频流：{source}')
    if source.resolve() == dest.resolve():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, prefix='.export-', delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        shutil.copy2(source, temp_path)
        temp_path.replace(dest)
    finally:
        temp_path.unlink(missing_ok=True)
    return dest


def export_speaker_track(project_root, edit_dir, out_dir):
    return copy_track(edit_dir / 'cut.mp4', out_dir / '01_口播视频_剪辑成片.mp4')


def export_subtitle_file(project_root, edit_dir, out_dir):
    return copy_track(edit_dir / 'subtitles.srt', out_dir / '02_字幕文件.srt', video=False)


def export_animation_track(project_root, edit_dir, out_dir, fps=30, source=None):
    if source is None:
        raise ValueError('请用 --animation <实际动画文件> 指定渲染结果；参见 references/tools.md')
    return copy_track(Path(source), out_dir / '03_演示动画.mp4')


def export_composite_video(project_root, edit_dir, out_dir, fps=30, source=None):
    source = Path(source) if source else edit_dir / 'final.mp4'
    return copy_track(source, out_dir / f'{project_root.name}_完整视听成片.mp4')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('project', type=Path)
    parser.add_argument('--mode', choices=['speaker', 'animation', 'composite', 'split'], default='composite')
    parser.add_argument('--out-dir', type=Path, default=Path('成品'))
    parser.add_argument('--animation', type=Path, help='已渲染动画轨；animation/split 必填')
    parser.add_argument('--final', type=Path, help='已渲染成片；默认 edit/final.mp4')
    args = parser.parse_args()
    root, edit = resolve_project_paths(args.project)
    out = args.out_dir if args.out_dir.is_absolute() else root / args.out_dir
    sources = []
    if args.mode in ('speaker', 'split'):
        sources.append((edit / 'cut.mp4', out / '01_口播视频_剪辑成片.mp4', True))
    if args.mode == 'split':
        sources.append((edit / 'subtitles.srt', out / '02_字幕文件.srt', False))
    if args.mode in ('animation', 'split'):
        if not args.animation:
            parser.error('--animation <实际动画文件> 是必填项；本工具只包装真实渲染结果')
        sources.append((args.animation.resolve(), out / '03_演示动画.mp4', True))
    if args.mode in ('composite', 'split'):
        sources.append(((args.final or edit / 'final.mp4').resolve(), out / f'{root.name}_完整视听成片.mp4', True))
    for source, _, _ in sources:
        if not source.is_file() or not source.stat().st_size:
            parser.error(f'没有真实交付件：{source}')
    files = [str(copy_track(source, dest, video)) for source, dest, video in sources]
    print(json.dumps({'ok': True, 'files': files, 'verified_delivery': False,
                      'next': '运行 verify_delivery.py <edit> --video <成片> --deliver-dir <交付目录>'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

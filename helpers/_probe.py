#!/usr/bin/env python3
"""Shared ffprobe/ffmpeg probes for overlay verification.

Kept in its own module rather than inside render.py so that `check_overlay.py`
and `render.py` can both use one implementation without importing each other;
render.py imports check_overlay lazily at composite time (see its docstring),
and check_overlay must therefore not import render.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# A pixel format carries alpha when its name says so. ffmpeg's naming is
# consistent here: yuva*/rgba/argb/bgra/abgr all have a fourth alpha component,
# and the non-alpha siblings (yuv420p, rgb24, yuv444p12le) do not.
_ALPHA_TOKENS = ("yuva", "rgba", "argb", "bgra", "abgr", "gbrap", "ya8", "ya16", "pal8")


def pix_fmt_has_alpha(pix_fmt: str | None) -> bool:
    """True when the pixel format name declares an alpha component."""
    if not pix_fmt:
        return False
    fmt = pix_fmt.lower()
    return any(tok in fmt for tok in _ALPHA_TOKENS)


def _ffprobe_json(path: Path, entries: str, stream: str = "v:0") -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", entries, "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def probe_video(path: Path) -> dict:
    """One probe for everything the overlay contract needs.

    Returns keys: exists, has_video, pix_fmt, width, height, duration,
    avg_frame_rate, r_frame_rate, nb_frames. Missing values are None rather
    than an exception, so a caller can report a precise problem.
    """
    info: dict = {
        "exists": Path(path).exists(), "has_video": False, "pix_fmt": None,
        "width": None, "height": None, "duration": None,
        "avg_frame_rate": None, "r_frame_rate": None, "nb_frames": None,
    }
    if not info["exists"]:
        return info
    try:
        data = _ffprobe_json(
            path,
            "stream=pix_fmt,width,height,avg_frame_rate,r_frame_rate,nb_frames"
            ":format=duration",
        )
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        return info
    streams = data.get("streams") or []
    if not streams:
        return info
    st = streams[0]
    info["has_video"] = True
    info["pix_fmt"] = st.get("pix_fmt")
    info["width"] = st.get("width")
    info["height"] = st.get("height")
    info["avg_frame_rate"] = st.get("avg_frame_rate")
    info["r_frame_rate"] = st.get("r_frame_rate")
    info["nb_frames"] = st.get("nb_frames")
    fmt = data.get("format") or {}
    for key in ("duration",):
        if fmt.get(key) is not None:
            info["duration"] = float(fmt[key])
    if info["duration"] is None:
        try:
            dur = _ffprobe_json(path, "stream=duration")
            st_dur = (dur.get("streams") or [{}])[0].get("duration")
            info["duration"] = float(st_dur) if st_dur else None
        except (subprocess.CalledProcessError, json.JSONDecodeError, OSError,
                TypeError, ValueError):
            pass
    return info


def alpha_range(path: Path, frames: int = 12, size: int = 64) -> tuple[int, int] | None:
    """(min, max) of the decoded alpha channel over a few downscaled frames.

    This is the probe that catches the failure this module exists for: a VP9
    WebM rendered with alpha on an ffmpeg whose libvpx lacks alpha support
    decodes as a fully opaque frame, so compositing it replaces the base video
    with black. `pix_fmt` alone cannot see that — the container still claims
    yuva420p — but the decoded alpha values can: a live alpha plane has values
    below 255, an opaque or baked one does not.

    Downscaling to 64x64 and reading at most `frames` frames keeps a 40-second
    1080x1920 overlay under a second to check.
    """
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", f"scale={size}:{size},format=rgba",
        "-frames:v", str(frames),
        "-f", "rawvideo", "-pix_fmt", "rgba", "-bitexact", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    raw = proc.stdout
    if len(raw) < 4:
        return None
    return min(raw[3::4]), max(raw[3::4])

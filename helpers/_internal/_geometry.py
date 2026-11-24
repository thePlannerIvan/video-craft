"""素材在素材带里的落位：一个算法，渲染与预览共用。

为什么单独一个模块
------------------
2026-11 的画框工具第一次做出来时，预览用「4:3 按高铺满、裁两侧」，渲染用
`min(画布宽/素材宽, 带高/素材高)`（contain，整幅可见）。两份口径差一次裁切，
预览就不再是成片的预览——而预览的全部意义是「所见即成片」。所以落位只留这一处：
`fit_in_band()` 是唯一实现，`montage.py` 的渲染与 `frame.py` 的预览都调它。

口径（竖屏 1080×1920、素材带 320–1440 为例）
---------------------------------------------
- 16:9 素材 1080×606：按宽铺满，上下各留 257 的带面；
- 4:3 素材 1080×810：按宽铺满，上下各留 155 的带面；
- 竖图（如 1393×1800，约 4:5）866×1120：按高铺满，左右各留 107 的带面。
共同点：素材整幅可见（contain），留出来的是带面色，不是黑边。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_LANDSCAPE_CANVAS = {"w": 1920, "h": 1080, "fps": 30}
DEFAULT_LANDSCAPE_PERSON_SLOT = {"x": 0, "y": 0, "w": 620, "h": 1080}
DEFAULT_LANDSCAPE_CAPTION_SAFE = {"x": 0, "y": 885, "w": 1920, "h": 195}


def normalize_box(box: dict[str, Any] | None, fallback: dict[str, int]) -> dict[str, int]:
    """Normalize a rectangle {x,y,w,h} or circle {cx,cy,r} into integer {x,y,w,h}."""
    if not isinstance(box, dict):
        return dict(fallback)
    if all(k in box for k in ("x", "y", "w", "h")):
        try:
            return {
                "x": int(round(float(box["x"]))),
                "y": int(round(float(box["y"]))),
                "w": max(0, int(round(float(box["w"])))),
                "h": max(0, int(round(float(box["h"])))),
            }
        except (TypeError, ValueError):
            return dict(fallback)
    if all(k in box for k in ("cx", "cy", "r")):
        try:
            cx, cy, r = float(box["cx"]), float(box["cy"]), max(0.0, float(box["r"]))
            return {
                "x": int(round(cx - r)),
                "y": int(round(cy - r)),
                "w": int(round(2 * r)),
                "h": int(round(2 * r)),
            }
        except (TypeError, ValueError):
            return dict(fallback)
    return dict(fallback)


def box_intersects(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Return True iff two {x,y,w,h} boxes overlap with strictly positive area."""
    ax, ay, aw, ah = int(a["x"]), int(a["y"]), int(a["w"]), int(a["h"])
    bx, by, bw, bh = int(b["x"]), int(b["y"]), int(b["w"]), int(b["h"])
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def compute_stage_box(canvas: dict[str, int], person: dict[str, int], caption: dict[str, int]) -> dict[str, int]:
    """Compute safe main visual stage rectangle excluding personSlot and bottom captionSafe."""
    cw, ch = int(canvas["w"]), int(canvas["h"])
    stage_y = 0
    stage_bottom = min(ch, int(caption["y"])) if (int(caption["h"]) > 0 and int(caption["y"]) >= ch // 2) else ch
    stage_x, stage_w = 0, cw

    pw, ph = int(person["w"]), int(person["h"])
    px, py = int(person["x"]), int(person["y"])
    if pw > 0 and ph > 0 and pw < cw:
        if ph >= stage_bottom * 0.5:
            if px <= max(16, int(cw * 0.25)):
                stage_x = min(cw, px + pw)
                stage_w = max(0, cw - stage_x)
            elif px + pw >= cw - max(16, int(cw * 0.25)):
                stage_x = 0
                stage_w = max(0, px)
        elif py + ph <= stage_bottom * 0.45:
            stage_y = min(stage_bottom, py + ph)

    return {
        "x": int(stage_x),
        "y": int(stage_y),
        "w": max(0, int(stage_w)),
        "h": max(0, int(stage_bottom - stage_y)),
    }


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def resolve_project_frame(project: Path | str | None = None, *, frame_tokens: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve authoritative project frame geometry (Single Source of Truth).

    Precedence:
      1. Explicit `frame_tokens` dict
      2. `<project>/frame.json`
      3. `<project>/material/frame/tokens.json`
      4. `<project>/recompose.json`
      5. Canonical defaults (1920x1080@30, personSlot 0,0,620,1080, captionSafe 0,885,1920,195)
    """
    raw: dict[str, Any] | None = None
    source = "default"

    if isinstance(frame_tokens, dict):
        raw = frame_tokens
        source = "explicit"
    elif project is not None:
        proj = Path(project)
        for rel in ("frame.json", "material/frame/tokens.json", "recompose.json"):
            candidate = proj / rel
            loaded = _read_json_dict(candidate)
            if loaded is not None:
                raw = loaded
                source = rel
                break

    raw = raw or {}
    c_raw = raw.get("canvas") if isinstance(raw.get("canvas"), dict) else {}
    w = int(c_raw.get("w") or c_raw.get("width") or DEFAULT_LANDSCAPE_CANVAS["w"])
    h = int(c_raw.get("h") or c_raw.get("height") or DEFAULT_LANDSCAPE_CANVAS["h"])
    fps = int(c_raw.get("fps") or DEFAULT_LANDSCAPE_CANVAS["fps"])
    canvas = {"w": w, "h": h, "fps": fps}

    person_fallback = dict(DEFAULT_LANDSCAPE_PERSON_SLOT)
    if w != DEFAULT_LANDSCAPE_CANVAS["w"] or h != DEFAULT_LANDSCAPE_CANVAS["h"]:
        scaled_pw = min(w, max(0, int(round(w * DEFAULT_LANDSCAPE_PERSON_SLOT["w"] / DEFAULT_LANDSCAPE_CANVAS["w"]))))
        person_fallback = {"x": 0, "y": 0, "w": scaled_pw, "h": h}

    band = raw.get("band") if isinstance(raw.get("band"), dict) else {}
    if isinstance(raw.get("captionSafe"), dict) or isinstance(raw.get("caption"), dict):
        cap_fallback = {"x": 0, "y": max(0, h - int(round(h * 195 / 1080))), "w": w, "h": min(h, int(round(h * 195 / 1080)))}
    elif "bottom" in band:
        b_bottom = max(0, min(h, int(band["bottom"])))
        cap_fallback = {"x": 0, "y": b_bottom, "w": w, "h": max(0, h - b_bottom)}
    elif w == DEFAULT_LANDSCAPE_CANVAS["w"] and h == DEFAULT_LANDSCAPE_CANVAS["h"]:
        cap_fallback = dict(DEFAULT_LANDSCAPE_CAPTION_SAFE)
    else:
        cap_h = min(h, int(round(h * DEFAULT_LANDSCAPE_CAPTION_SAFE["h"] / DEFAULT_LANDSCAPE_CANVAS["h"])))
        cap_fallback = {"x": 0, "y": max(0, h - cap_h), "w": w, "h": cap_h}

    person = normalize_box(raw.get("personSlot") or raw.get("person"), person_fallback)
    caption = normalize_box(raw.get("captionSafe") or raw.get("caption"), cap_fallback)
    stage = compute_stage_box(canvas, person, caption)

    return {
        "width": w,
        "height": h,
        "fps": fps,
        "canvas": canvas,
        "person": dict(person),
        "caption": dict(caption),
        "personSlot": dict(person),
        "captionSafe": dict(caption),
        "stage": stage,
        "source": source,
    }


def fit_in_band(src_w: int, src_h: int, canvas_w: int, band_h: int) -> tuple[int, int]:
    """等比缩放到「宽不超过画布、高不超过素材带」，返回偶数化的 (宽, 高)。

    偶数化是为了 yuv420p 编码；调用方自己按 (canvas_w - fw) // 2 与
    (band_h - fh) // 2 居中。
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"素材尺寸不合法：{src_w}×{src_h}")
    if canvas_w <= 0 or band_h <= 0:
        raise ValueError(f"目标区域不合法：{canvas_w}×{band_h}")
    scale = min(canvas_w / src_w, band_h / src_h)
    fw = max(2, int(src_w * scale) // 2 * 2)
    fh = max(2, int(src_h * scale) // 2 * 2)
    return fw, fh

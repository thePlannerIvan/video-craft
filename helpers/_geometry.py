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

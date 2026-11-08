#!/usr/bin/env python3
"""`frame` —— 参考页 → token → 画框三件套（base / overlay / spec）+ 真实素材预览。

它替换掉的是一条历史路线
------------------------
2026-11 的哈雷片（1080×1920 竖屏）没有画框工具：实现方临场手写 PIL 脚本，出了
`base.png`（底色/肌理/1px 细线/三处文字/人物位空环）、`overlay.png`（素材带上下
1px 线 + 顶底 28px 暗角）和 `spec.md`（像素坐标表）。效果被作者认可，但每个项目
都要把同一套坐标和字距重写一遍，改一个数就得四处对。

所以这里只做一件事：**token 是唯一事实源，三个产物由它生成**。

    base.png   静态底。会被素材盖住 —— 底色、素材带面、细线、文字、人物位空环、颗粒
    overlay.png 叠在素材之上。不会被盖住 —— 素材带上下 1px 线、画面顶底暗角
    spec.md    像素坐标表，给人核对，也给出叠放顺序

为什么 base 与 overlay 必须分开
-------------------------------
素材带内的内容会被素材整块盖住（4:3 素材会顶到带区上下沿，连 base 上那条带区线
一起吃掉）。base 负责"素材不在的地方长什么样"，overlay 负责"素材在的地方仍然要
有的东西"。合成顺序固定为 base → 素材 → overlay → 花字；把两者合成一张会在
素材边缘丢线，或者让素材被画框的底色压暗。

两条命令
--------
    python3 helpers/frame.py build   <project> --tokens <tokens.json> [--out-dir <dir>]
    python3 helpers/frame.py preview <project> --tokens <tokens.json> \\
        --wide <16:9 素材帧> --tall <4:3 素材帧> [--out <jpg>]

`build` 写 `base.png`、`overlay.png`、`spec.md`，默认 `<project>/material/frame/`。
`preview` 把两张真实帧按**成片同一落位**合成到画框里（`_geometry.fit_in_band`，contain：
素材整幅可见，留素材带面色 —— 16:9 → 1080×606、4:3 → 1080×810、竖图 → 866×1120），
左右并排 1:1 像素出图，默认 `<project>/material/frame/preview.jpg`。这是给人挑画框与落位用的，
不是成片：它不套调色档，颜色与成片不同是正常的。

token 缺字段时用本文档的竖屏默认值补齐，并在 stderr 逐项说明补了什么（不静默）。
字体按固定顺序回退：Hiragino Sans GB → STHeiti Medium → Songti；都取不到就报错，
不退到 PIL 默认字体 —— 默认字体会让画框的观感静默变样。

退出码：0 = 成功；1 = token / 素材有问题（stderr 给一句能读的原因）；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from _geometry import fit_in_band

# 字体回退顺序：只用系统字体，且必须真的取到；退回 PIL 默认字体是静默降级。
FONT_CANDIDATES = (
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 1),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 1),
)

# 竖屏 1080×1920 实测契约，也是 token 缺字段时的默认值。
# 换项目时逐条确认再改；不要在这里加项目专属的例外。
DEFAULTS = {
    "canvas": {"width": 1080, "height": 1920, "fps": 30},
    "band": {"top": 320, "bottom": 1440, "inset": 90, "tick": 18},
    "palette": {
        "bg": "#0B0B0C",      # 四周底色
        "band": "#121214",    # 素材带面
        "line": "#000000",    # 所有线条只有这一种黑
        "text": "#F3F3F3",    # 主文字
        "muted": "#6E6E6A",   # 次级文字
    },
    "texts": [
        {"id": "title-1", "text": "WEEKEND", "size": 32, "tracking": 7.7,
         "baseline": 161, "x": 90, "align": "left", "color": "text",
         "uppercase": True, "condense": 0.8},
        {"id": "title-2", "text": "OUTLAW", "size": 32, "tracking": 7.7,
         "baseline": 201, "x": 90, "align": "left", "color": "text",
         "uppercase": True, "condense": 0.8},
        {"id": "meta-1", "text": "CASE STUDY", "size": 11, "tracking": 2.0,
         "baseline": 166, "x": 990, "align": "right", "color": "muted",
         "uppercase": True, "condense": 1.0},
        {"id": "meta-2", "text": "OUTLAW MYTHOLOGY", "size": 11, "tracking": 2.0,
         "baseline": 181, "x": 990, "align": "right", "color": "muted",
         "uppercase": True, "condense": 1.0},
        {"id": "footer", "text": "MILWAUKEE, WISCONSIN · HARLEY-DAVIDSON",
         "size": 9, "tracking": 1.8, "baseline": 1842, "x": 90, "align": "left",
         "color": "muted", "uppercase": True, "condense": 1.0},
    ],
    "personSlot": {"cx": 540, "cy": 170, "r": 128,
                   "ringOffset": 5, "ringWidth": 1, "ringAlpha": 0.10},
    "cropMarks": {"inset": 40, "length": 18, "width": 1, "color": "line"},
    "grain": {"amplitude": 2, "dither": 1},
    "vignette": {"height": 28, "maxAlpha": 26, "color": "line"},
}

# 单条文字的通用兜底（token 里给了 texts 但某条缺字段时用）
TEXT_DEFAULTS = {"id": "", "size": 32, "tracking": 0.0, "baseline": 161,
                 "x": 90, "align": "left", "color": "text",
                 "uppercase": False, "condense": 1.0}

GRAIN_SEED = 20261108
DITHER_SEED = 7331


class FrameError(Exception):
    """token / 素材层面的问题：给一句能读的原因，退出码 1。"""


# ── 通用小工具 ───────────────────────────────────────────────────────────────

def _parse_hex(value: str) -> tuple[int, int, int]:
    text = str(value).strip()
    if text.startswith("#"):
        body = text[1:]
        if len(body) == 3:
            body = "".join(ch * 2 for ch in body)
        if len(body) == 6:
            try:
                return tuple(int(body[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                pass
    raise FrameError(f"颜色不合法：{value!r}（要 #RRGGBB 或 palette 里的名字）")


def _resolve_color(value, palette: dict[str, str]) -> tuple[int, int, int]:
    if isinstance(value, str) and value in palette and not value.startswith("#"):
        return _parse_hex(palette[value])
    return _parse_hex(value)


def _resolve_palette(token: dict) -> dict[str, str]:
    raw = token["palette"]
    if not isinstance(raw, dict) or not raw:
        raise FrameError("token 的 palette 必须是对象")
    palette: dict[str, str] = {}
    for key, value in raw.items():
        _parse_hex(value)          # 提前报错，别等到画到一半
        palette[str(key)] = str(value)
    return palette


def _at(token: dict, path: str):
    """按 `a.b[0].c` 取 token 里的值；只为报错信息可读，不做容错。"""
    node = token
    for part in path.split("."):
        name, _, index = part.partition("[")
        if name:
            node = node[name]
        if index:
            node = node[int(index.rstrip("]"))]
    return node


def _int(token: dict, path: str, minimum: int | None = None,
         maximum: int | None = None) -> int:
    node = _at(token, path)
    if isinstance(node, bool) or not isinstance(node, int):
        raise FrameError(f"token 的 {path} 必须是整数，拿到 {node!r}")
    if minimum is not None and node < minimum:
        raise FrameError(f"token 的 {path} 不能小于 {minimum}（拿到 {node}）")
    if maximum is not None and node > maximum:
        raise FrameError(f"token 的 {path} 不能大于 {maximum}（拿到 {node}）")
    return node


def _num(token: dict, path: str, minimum: float | None = None,
         maximum: float | None = None) -> float:
    node = _at(token, path)
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        raise FrameError(f"token 的 {path} 必须是数字，拿到 {node!r}")
    value = float(node)
    if minimum is not None and value < minimum:
        raise FrameError(f"token 的 {path} 不能小于 {minimum}（拿到 {value}）")
    if maximum is not None and value > maximum:
        raise FrameError(f"token 的 {path} 不能大于 {maximum}（拿到 {value}）")
    return value


def _brief(value) -> str:
    if isinstance(value, list):
        return f"{len(value)} 项"
    if isinstance(value, dict):
        return "默认对象"
    return json.dumps(value, ensure_ascii=False)


def _fill_defaults(node: dict, default: dict, prefix: str, notes: list[str]) -> None:
    """把缺失字段逐层补成默认值，并登记补了哪些（供 stderr 说明）。"""
    for key, dv in default.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in node:
            node[key] = _copy(dv)
            notes.append(f"{path}={_brief(dv)}")
        elif isinstance(dv, dict) and isinstance(node[key], dict):
            _fill_defaults(node[key], dv, path, notes)
        # 数组不在这里递归：texts 的逐条兜底在 _load_tokens 里用 TEXT_DEFAULTS 做


def _copy(value):
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


def _load_tokens(path: Path) -> tuple[dict, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FrameError(f"读不到 token 文件 {path}：{exc}") from exc
    try:
        token = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FrameError(f"token 不是合法 JSON（{path} 第 {exc.lineno} 行）：{exc.msg}") from exc
    if not isinstance(token, dict):
        raise FrameError(f"token 顶层必须是对象（{path}）")
    notes: list[str] = []
    # texts 整节缺失时给的是默认五处文字，其余是标量/对象，统一走递归补
    _fill_defaults(token, DEFAULTS, "", notes)
    # 单条文字缺失字段用 TEXT_DEFAULTS 兜一层（DEFAULTS 里第一条是特定内容，不能直接套）
    for index, item in enumerate(token.get("texts") or []):
        if isinstance(item, dict):
            _fill_defaults(item, TEXT_DEFAULTS, f"texts[{index}]", notes)
    if not isinstance(token.get("texts"), list):
        raise FrameError("token 的 texts 必须是数组")
    return token, notes


def _validate(token: dict) -> None:
    width = _int(token, "canvas.width", 2, 20000)
    height = _int(token, "canvas.height", 2, 20000)
    _int(token, "canvas.fps", 1, 240)
    top = _int(token, "band.top", 0, height - 1)
    bottom = _int(token, "band.bottom", 1, height)
    if bottom - top < 2:
        raise FrameError(f"素材带太薄：band {top}–{bottom}（画布高 {height}）")
    _int(token, "band.inset", 0, width // 2)
    _int(token, "band.tick", 0, 1000)

    palette = _resolve_palette(token)
    for index, item in enumerate(token["texts"]):
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            raise FrameError(f"token 的 texts[{index}] 缺 text")
        _int(token, f"texts[{index}].size", 1, 512)
        _num(token, f"texts[{index}].tracking", -100, 200)
        _int(token, f"texts[{index}].baseline", 0, height)
        _int(token, f"texts[{index}].x", 0, width)
        if item.get("align") not in ("left", "right"):
            raise FrameError(
                f"token 的 texts[{index}].align 只能是 left / right，拿到 {item.get('align')!r}")
        _resolve_color(item.get("color"), palette)
        _num(token, f"texts[{index}].condense", 0.1, 3.0)

    cx = _int(token, "personSlot.cx", 0, width)
    cy = _int(token, "personSlot.cy", 0, height)
    radius = _int(token, "personSlot.r", 1, min(width, height) // 2)
    _int(token, "personSlot.ringOffset", 0, min(width, height) // 2)
    _int(token, "personSlot.ringWidth", 0, 20)
    _num(token, "personSlot.ringAlpha", 0.0, 1.0)

    _int(token, "cropMarks.inset", 0, min(width, height) // 2)
    _int(token, "cropMarks.length", 0, 400)
    _int(token, "cropMarks.width", 0, 20)
    _resolve_color(token["cropMarks"].get("color"), palette)

    _int(token, "grain.amplitude", 0, 32)
    _int(token, "grain.dither", 0, 32)
    _int(token, "vignette.height", 0, height // 2)
    _int(token, "vignette.maxAlpha", 0, 255)
    _resolve_color(token["vignette"].get("color"), palette)
    # 人物位圆心必须落在画布内，圆环半径不能越界
    if cx + radius > width or cy + radius > height or cx - radius < 0:
        raise FrameError(f"人物位圆越界：({cx},{cy}) r={radius} 超出画布 {width}×{height}")


# ── 字体与文字 ───────────────────────────────────────────────────────────────

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    errors = []
    for path, index in FONT_CANDIDATES:
        if not Path(path).exists():
            errors.append(f"{path} 不存在")
            continue
        try:
            font = ImageFont.truetype(path, size, index=index)
        except OSError as exc:          # pragma: no cover - 只有系统被换掉才会走到
            errors.append(f"{path}[{index}] 打不开：{exc}")
            continue
        _FONT_CACHE[size] = font
        return font
    raise FrameError("找不到可用的系统字体（" + "；".join(errors) + "）")


def _draw_texts(img: Image.Image, texts: list[dict], palette: dict[str, str]) -> Image.Image:
    """在整幅透明层上排字，再一次性合成。每字单独定位，字距是绝对像素。"""
    width, height = img.size
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for item in texts:
        size = int(item["size"])
        font = _font(size)
        text = str(item["text"])
        if item.get("uppercase"):
            text = text.upper()
        tracking = float(item["tracking"])
        condense = float(item["condense"])
        colour = (*_resolve_color(item["color"], palette), 255)
        # 每个字先按字形宽度算位置；condense 压字形不压字距（字距是版面参数）
        glyph_widths = [font.getlength(ch) * condense for ch in text]
        total = sum(glyph_widths) + tracking * max(0, len(text) - 1)
        x = float(item["x"]) - total if item["align"] == "right" else float(item["x"])
        baseline = int(item["baseline"])
        for ch, advance in zip(text, glyph_widths):
            if condense == 1.0:
                draw.text((int(round(x)), baseline), ch, font=font, fill=colour, anchor="ls")
            else:
                native = max(1, math.ceil(font.getlength(ch)))
                tile = Image.new("RGBA", (native, size * 3), (0, 0, 0, 0))
                ImageDraw.Draw(tile).text((0, size * 2), ch, font=font,
                                          fill=colour, anchor="ls")
                target = max(1, int(round(native * condense)))
                tile = tile.resize((target, size * 3), Image.Resampling.LANCZOS)
                layer.alpha_composite(tile, (int(round(x)), baseline - size * 2))
            x += advance + tracking
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


# ── 颗粒 ─────────────────────────────────────────────────────────────────────

def _noise(size: tuple[int, int], amplitude: int, seed: int) -> Image.Image:
    """整幅单色颗粒：每个像素抽一个 [-amplitude, +amplitude] 的整数偏移。

    用 bytes.translate 生成，2M 像素也在毫秒级；同 seed 出同一张图，重跑可复现。
    """
    span = 2 * amplitude + 1
    table = bytes(128 + (value % span) - amplitude for value in range(256))
    raw = random.Random(seed).randbytes(size[0] * size[1]).translate(table)
    return Image.frombytes("L", size, raw)


def _add_grain(img: Image.Image, grain: dict) -> Image.Image:
    for amplitude, seed in ((int(grain["amplitude"]), GRAIN_SEED),
                            (int(grain["dither"]), DITHER_SEED)):
        if not amplitude:
            continue
        noise = _noise(img.size, amplitude, seed)
        img = Image.merge("RGB", [ImageChops.add(channel, noise, 1.0, -128)
                                  for channel in img.split()])
    return img


# ── base / overlay ──────────────────────────────────────────────────────────

def _draw_base(token: dict, palette: dict[str, str]) -> Image.Image:
    width = int(token["canvas"]["width"])
    height = int(token["canvas"]["height"])
    top = int(token["band"]["top"])
    bottom = int(token["band"]["bottom"])
    band = token["band"]
    line_colour = _resolve_color("line", palette)

    img = Image.new("RGB", (width, height), _resolve_color("bg", palette))
    draw = ImageDraw.Draw(img)

    # 素材带面 + 2px 过渡（不是硬切：交界处读到的是两个面之间的灰度）
    transition = tuple(int(round(bg * 0.7 + face * 0.3))
                       for bg, face in zip(_resolve_color("bg", palette),
                                           _resolve_color("band", palette)))
    if bottom - top >= 3:
        draw.rectangle([0, top + 1, width - 1, bottom - 1],
                       fill=_resolve_color("band", palette))
    if top - 1 >= 0:
        draw.line([(0, top - 1), (width - 1, top - 1)], fill=transition)
    if bottom + 1 < height:
        draw.line([(0, bottom + 1), (width - 1, bottom + 1)], fill=transition)

    img = _add_grain(img, token["grain"])
    draw = ImageDraw.Draw(img)

    # 素材带上下两条 1px 线 + 两端下探/上探刻度
    inset = int(band["inset"])
    tick = int(band["tick"])
    left, right = inset, width - inset
    for y in (top, bottom):
        draw.line([(left, y), (right, y)], fill=line_colour)
    if tick:
        draw.line([(left, top), (left, top + tick)], fill=line_colour)
        draw.line([(right, top), (right, top + tick)], fill=line_colour)
        draw.line([(left, bottom), (left, bottom - tick)], fill=line_colour)
        draw.line([(right, bottom), (right, bottom - tick)], fill=line_colour)

    # 四角裁切标记：每角两条 18px 线段，沿画面内侧延伸
    marks = token["cropMarks"]
    mark_inset = int(marks["inset"])
    mark_len = int(marks["length"])
    mark_colour = _resolve_color(marks["color"], palette)
    mark_width = int(marks["width"])
    if mark_len and mark_width:
        x0, x1 = mark_inset, width - mark_inset
        y0, y1 = mark_inset, height - mark_inset
        for x, y, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1),
                             (x0, y1, 1, -1), (x1, y1, -1, -1)):
            draw.line([(x, y), (x + dx * mark_len, y)], fill=mark_colour, width=mark_width)
            draw.line([(x, y), (x, y + dy * mark_len)], fill=mark_colour, width=mark_width)

    # 人物位：空区里什么都不放；圆环在空区外，10% 不透明度，只当肌理
    slot = token["personSlot"]
    ring_alpha = int(round(float(slot["ringAlpha"]) * 255))
    if ring_alpha and int(slot["ringWidth"]):
        cx, cy = int(slot["cx"]), int(slot["cy"])
        ring_r = int(slot["r"]) + int(slot["ringOffset"])
        ring = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse(
            [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
            outline=(*line_colour, ring_alpha), width=int(slot["ringWidth"]))
        img = Image.alpha_composite(img.convert("RGBA"), ring).convert("RGB")

    return _draw_texts(img, token["texts"], palette)


def _draw_overlay(token: dict, palette: dict[str, str]) -> Image.Image:
    width = int(token["canvas"]["width"])
    height = int(token["canvas"]["height"])
    top = int(token["band"]["top"])
    bottom = int(token["band"]["bottom"])
    inset = int(token["band"]["inset"])
    line_colour = _resolve_color("line", palette)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # 素材带上下线：素材会盖住 base 上的这两条线，所以必须再压在素材之上
    for y in (top, bottom):
        draw.line([(inset, y), (width - inset, y)],
                  fill=(*line_colour, 255))
    # 画面顶底各 28px 极轻暗角：y=0 处 26 → 向内 0
    vignette = token["vignette"]
    v_height = int(vignette["height"])
    max_alpha = int(vignette["maxAlpha"])
    v_colour = _resolve_color(vignette["color"], palette)
    if v_height and max_alpha:
        for offset in range(min(v_height, height)):
            alpha = int(round(max_alpha * (v_height - offset) / v_height))
            if alpha <= 0:
                continue
            draw.line([(0, offset), (width - 1, offset)], fill=(*v_colour, alpha))
            draw.line([(0, height - 1 - offset), (width - 1, height - 1 - offset)],
                      fill=(*v_colour, alpha))
    return overlay


# ── spec.md ─────────────────────────────────────────────────────────────────

def _material_rows(token: dict) -> list[tuple[str, str, str, str, str]]:
    """素材落位表：数字由 material_box 算，避免文档与渲染各写一套。"""
    rows = []
    for label, (w, h) in (("16:9", (1920, 1080)), ("4:3", (640, 480)),
                          ("竖图 4:5", (1080, 1350))):
        x, y, fw, fh = material_box(token, w, h)
        note = "整幅可见" if fw == int(token["canvas"]["width"]) else "按高铺满，左右留带面"
        rows.append((label, f"{w}×{h}", f"{fw}×{fh}", f"({x},{y})", note))
    return rows


def _write_spec(token: dict, palette: dict[str, str], path: Path) -> None:
    width = int(token["canvas"]["width"])
    height = int(token["canvas"]["height"])
    fps = int(token["canvas"]["fps"])
    band = token["band"]
    top, bottom = int(band["top"]), int(band["bottom"])
    inset = int(band["inset"])
    slot = token["personSlot"]
    cx, cy = int(slot["cx"]), int(slot["cy"])
    radius = int(slot["r"])
    ring_r = radius + int(slot["ringOffset"])
    marks = token["cropMarks"]
    grain = token["grain"]
    vignette = token["vignette"]

    def colour(value) -> str:
        if isinstance(value, str) and value.startswith("#"):
            return value
        return str(palette.get(str(value), value))

    lines: list[str] = []
    lines.append(f"# 画框图层规格 · {width}×{height}")
    lines.append("")
    lines.append("> 由 `helpers/frame.py build` 从 token 生成，不要手改；改画框先改 token，再重跑。")
    lines.append(f"> 画布 {width}×{height} / fps {fps}。")
    lines.append("")
    lines.append("## 叠放顺序（不能改）")
    lines.append("")
    lines.append("```")
    lines.append("base.png  →  素材  →  overlay.png  →  花字 / 字幕")
    lines.append("```")
    lines.append("")
    lines.append("- base 会被素材盖住，overlay 不会：素材带上下两条线靠 overlay 压回素材之上。")
    lines.append("- 花字 / 字幕永远在最上层。")
    lines.append("")
    lines.append("## 交付物")
    lines.append("")
    lines.append("| 文件 | 尺寸 / 模式 | 说明 |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| `base.png` | {width}×{height} RGB | 底色、素材带面、细线、文字、人物位空环、颗粒 |")
    lines.append(f"| `overlay.png` | {width}×{height} RGBA | 素材带上下线 + 画面顶底暗角；其余全透明 |")
    lines.append(f"| `spec.md` | 本文件 | 像素坐标表 |")
    lines.append("")
    lines.append("## 色板")
    lines.append("")
    lines.append("| token 键 | Hex | 用途 |")
    lines.append("| --- | --- | --- |")
    for key, label in (("bg", "四周底色与字幕区"), ("band", "素材带面"),
                       ("line", "全部线条（只有这一种黑）"), ("text", "主文字"),
                       ("muted", "次级文字")):
        lines.append(f"| {key} | `{palette.get(key, '')}` | {label} |")
    lines.append("")
    lines.append("## 像素坐标表 — `base.png`")
    lines.append("")
    lines.append("### 线（`" + str(palette.get("line", "#000000")) + "`，1px）")
    lines.append("")
    lines.append("| 元素 | 坐标 |")
    lines.append("| --- | --- |")
    lines.append(f"| 素材带上线 | ({inset},{top}) → ({width - inset},{top}) |")
    lines.append(f"| 素材带下线 | ({inset},{bottom}) → ({width - inset},{bottom}) |")
    lines.append(f"| 上线两端下探刻度 | ({inset},{top}) → ({inset},{top + int(band['tick'])})；"
                 f"({width - inset},{top}) → ({width - inset},{top + int(band['tick'])}) |")
    lines.append(f"| 下线两端上探刻度 | ({inset},{bottom - int(band['tick'])}) → ({inset},{bottom})；"
                 f"({width - inset},{bottom - int(band['tick'])}) → ({width - inset},{bottom}) |")
    lines.append(f"| 四角裁切标记 ×4 | 角点 ({marks['inset']},{marks['inset']})、"
                 f"({width - int(marks['inset'])},{marks['inset']})、"
                 f"({int(marks['inset'])},{height - int(marks['inset'])})、"
                 f"({width - int(marks['inset'])},{height - int(marks['inset'])})；"
                 f"每角两条 {marks['length']}px 线段向画面内侧 |")
    lines.append("")
    lines.append("### 人物位（保持空）")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 圆心 | ({cx},{cy}) |")
    lines.append(f"| 空区半径 | {radius}px（圆内不放任何装饰与文字） |")
    lines.append(f"| 圆环 | 半径 {ring_r}px、{slot['ringWidth']}px、"
                 f"`{palette.get('line', '#000000')}`、"
                 f"{float(slot['ringAlpha']):.0%} 不透明度 |")
    lines.append("")
    lines.append(f"**人物位 ({cx},{cy}) r={radius} 保持空**：合成后圆内必须是纯底色，"
                 f"不放任何画框元素，也不放花字。")
    lines.append("")
    lines.append("### 文字")
    lines.append("")
    lines.append("| 位置 | 内容 | 字号 | 字距 | 颜色 | 基线 y | 横向 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for item in token["texts"]:
        if item["align"] == "right":
            anchor = f"右对齐 x={item['x']}"
        else:
            anchor = f"左起 x={item['x']}"
        if float(item["condense"]) != 1.0:
            anchor += f"，横向压缩 {float(item['condense']):.2f}"
        lines.append(f"| {item.get('id') or '—'} | {item['text']} | {item['size']}px | "
                     f"+{float(item['tracking']):g}px | `{colour(item['color'])}` | "
                     f"{item['baseline']} | {anchor} |")
    lines.append("")
    lines.append("### 颗粒")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 静态颗粒 | ±{grain['amplitude']} 级单色，全幅均匀，固定不抖动 |")
    lines.append(f"| 抖动 | ±{grain['dither']} 级（防渐变色带） |")
    lines.append("")
    lines.append("## `overlay.png`")
    lines.append("")
    lines.append("| 元素 | 规格 |")
    lines.append("| --- | --- |")
    lines.append(f"| 素材带上线 | ({inset},{top}) → ({width - inset},{top})，"
                 f"`{palette.get('line', '#000000')}`，alpha 255 |")
    lines.append(f"| 素材带下线 | ({inset},{bottom}) → ({width - inset},{bottom})，"
                 f"`{palette.get('line', '#000000')}`，alpha 255 |")
    lines.append(f"| 顶部暗角 | y=0 起 {vignette['height']}px，alpha {vignette['maxAlpha']} → 0 |")
    lines.append(f"| 底部暗角 | y={height - 1} 起向上 {vignette['height']}px，alpha "
                 f"{vignette['maxAlpha']} → 0 |")
    lines.append("| 其余 | 全透明（alpha=0）；素材带内的内容只来自素材本身 |")
    lines.append("")
    lines.append("## 素材落位")
    lines.append("")
    lines.append("| 画幅 | 缩放 | 目标尺寸 | 落点 / 裁切 | 说明 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for ratio, fit, size, origin, note in _material_rows(token):
        lines.append(f"| {ratio} | {fit} | {size} | {origin} | {note} |")
    lines.append("")
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        raise FrameError(f"写不了 spec.md {path}：{exc}") from exc


# ── 命令 ────────────────────────────────────────────────────────────────────

def _project_dir(text: str) -> Path:
    project = Path(text).expanduser()
    if not project.is_dir():
        raise FrameError(f"项目目录不存在：{project}")
    return project


def _token_path(text: str) -> Path:
    path = Path(text).expanduser()
    if not path.is_file():
        raise FrameError(f"token 文件不存在：{path}")
    return path


def _load(project_text: str, tokens_text: str) -> tuple[dict, dict, Path]:
    project = _project_dir(project_text)
    token, notes = _load_tokens(_token_path(tokens_text))
    _validate(token)
    palette = _resolve_palette(token)
    if notes:
        print("frame: token 缺字段，已补默认值：" + "，".join(notes), file=sys.stderr)
    return token, palette, project


def _ensure_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FrameError(f"建不了输出目录 {path}：{exc}") from exc


def _write_png(img: Image.Image, path: Path) -> None:
    _ensure_dir(path.parent)
    try:
        img.save(path)
    except OSError as exc:
        raise FrameError(f"写不了图片 {path}：{exc}") from exc


def _cmd_build(args) -> int:
    token, palette, project = _load(args.project, args.tokens)
    out_dir = Path(args.out_dir).expanduser() if args.out_dir \
        else project / "material" / "frame"
    _ensure_dir(out_dir)
    width = int(token["canvas"]["width"])
    height = int(token["canvas"]["height"])

    base = _draw_base(token, palette)
    overlay = _draw_overlay(token, palette)
    _write_png(base, out_dir / "base.png")
    _write_png(overlay, out_dir / "overlay.png")
    _write_spec(token, palette, out_dir / "spec.md")
    print(f"frame: base.png（RGB {width}×{height}）/ overlay.png（RGBA {width}×{height}）"
          f" / spec.md → {out_dir}")
    return 0


def material_box(token: dict, img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """素材在画布上的落位 (x, y, w, h)：与 montage.py 的渲染共用同一个算法。

    contain —— 素材整幅可见，留出来的是素材带面色（不是黑边）。竖屏 1080×1920 /
    素材带 320–1440 时：16:9 → 1080×606，4:3 → 1080×810，竖图（约 4:5）→ 866×1120。
    """
    width = int(token["canvas"]["width"])
    top = int(token["band"]["top"])
    band = int(token["band"]["bottom"]) - top
    fw, fh = fit_in_band(img_w, img_h, width, band)
    return (width - fw) // 2, top + (band - fh) // 2, fw, fh


def _compose_pane(token: dict, palette: dict[str, str], frame_path: Path) -> Image.Image:
    try:
        material = Image.open(frame_path).convert("RGB")
    except OSError as exc:
        raise FrameError(f"素材帧打不开：{frame_path}（{exc}）") from exc
    x, y, fw, fh = material_box(token, material.width, material.height)
    base = _draw_base(token, palette)
    base.paste(material.resize((fw, fh), Image.Resampling.LANCZOS), (x, y))
    return Image.alpha_composite(base.convert("RGBA"),
                                 _draw_overlay(token, palette)).convert("RGB")


def _cmd_preview(args) -> int:
    token, palette, project = _load(args.project, args.tokens)
    width = int(token["canvas"]["width"])
    height = int(token["canvas"]["height"])
    wide_path = Path(args.wide).expanduser()
    tall_path = Path(args.tall).expanduser()
    for path in (wide_path, tall_path):
        if not path.is_file():
            raise FrameError(f"素材帧不存在：{path}")

    left = _compose_pane(token, palette, wide_path)
    right = _compose_pane(token, palette, tall_path)
    preview = Image.new("RGB", (width * 2, height))
    preview.paste(left, (0, 0))
    preview.paste(right, (width, 0))

    out = Path(args.out).expanduser() if args.out \
        else project / "material" / "frame" / "preview.jpg"
    _ensure_dir(out.parent)
    try:
        preview.save(out, quality=92)
    except OSError as exc:
        raise FrameError(f"写不了预览图 {out}：{exc}") from exc
    print(f"frame: preview → {out}（{width * 2}×{height}，左 16:9 / 右 4:3）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="frame.py", description="参考页 → token → 画框三件套 + 真实素材预览")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="写 base.png / overlay.png / spec.md")
    build.add_argument("project", help="<project> 目录")
    build.add_argument("--tokens", required=True, help="画框 token JSON")
    build.add_argument("--out-dir", help="默认 <project>/material/frame/")
    build.set_defaults(func=_cmd_build)
    preview = sub.add_parser("preview", help="两张真实帧并排合成预览")
    preview.add_argument("project", help="<project> 目录")
    preview.add_argument("--tokens", required=True, help="画框 token JSON")
    preview.add_argument("--wide", required=True, help="16:9 素材帧（图片）")
    preview.add_argument("--tall", required=True, help="4:3 素材帧（图片）")
    preview.add_argument("--out", help="默认 <project>/material/frame/preview.jpg")
    preview.set_defaults(func=_cmd_preview)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FrameError as exc:
        print(f"frame: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

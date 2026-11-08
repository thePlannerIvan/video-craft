#!/usr/bin/env python3
"""`montage` —— 现成素材蒙太奇：镜头表 → 渲染 → 合成，一个方向有硬闸门。

它替换掉的是一条历史路线
------------------------
2026-11 的哈雷片（口播录音 + 档案影像 + 照片，1080×1920）没有片型入口：入口表六行
没有一行匹配「已录口播 + 无参考页 + 现成素材」，于是实现方**跳过了所有路线**，自己手写了
四版渲染器（build_v1→v4）和七个一次性脚本。四次返工的根因只有两个：

1. **素材入点与 EDL 源时间是两个坐标。** 渲染器把剪辑时间轴上的源时间当成素材入点去 seek，
   超出素材长度的镜头 seek 到片尾之外，得到一段只有底图的画面；ffmpeg 退 0、文件大小正常。
   全片 67 镜里有 18 镜是空的，直到最后才被肉眼发现。
2. **花字的时间坐标没人换算。** 花字用词在源片里的时间直接当剪后时间，全片错位 41 秒。

所以这个模块只做一件事，但把这两件事做成结构：**镜头表里 `in` 是素材内的秒数，
`cutStart` 是剪后时间轴上的秒数，两者不共用字段**；花字一律给「段 + 词序号」的词锚，
由这里换算成剪后时间，并钳到所在镜头结束前。

三条命令
--------
    python3 helpers/montage.py plan      <edit_dir> --shots <spec.json> [-o <plan.json>]
    python3 helpers/montage.py render    <edit_dir> [--plan <plan.json>] [--max N] [--only 1,3,5] [--concat] [--deliver]
    python3 helpers/montage.py voice-cut <edit_dir> [--master <母版>] [--audio <口播音轨>] [-o <out>]

`plan` 把「段 + 起始词」的人读镜头表展开成绝对时间，校验后写 `edit/montage-plan.json`。
它有两道准入：**素材清单**（`material-inventory.json`：每镜的素材要登记、`summary` 非空、
`usable != false`）与**唯一性**（`ReuseLedger`；`check_montage.py` import 同一份实现）。
素材不清就先回 `scan_materials.py`，别在镜头表里按文件名猜。EDL 段里有 `speed != 1` 或
`mute` 直接拒——montage 的剪后时间按原速累加，静默算下去整片会错位。

`render` 按 `montage-plan.json` 逐镜渲染（幂等缓存、可 `--max` 分块、先写 /tmp 再 move），
再可选合成与混音。**默认输出 `edit/_engineering/picture.mp4` = 审阅素材，不打闸**；
目标不在 `edit/_engineering/` 下时必须显式 `--deliver`，且先过 `render_gate.py` —— 交付件的
判据是「作者明确指令 + 人工提交覆盖当前快照」，不是命令跑完了。

`voice-cut` 按 `edit/edl.json` 从母版剪竖屏人物轨：默认无声、落
`edit/_engineering/voice_cut.mp4`；`--audio` 才混口播音轨。实测时长与
`plan.timeline.total` 差 > 0.5s 硬失败。检查在 `check_montage.py`，本模块不重复。

镜头表（人读、可手写）字段
--------------------------
    {"ranges_from": "edit/edl.json",
     "frame":  {"width": 1080, "height": 1920, "fps": 30, "band": [320, 1440],
                "labelX": 90, "labelY": 1258, "base": "material/frame/base.png",
                "overlay": "material/frame/overlay.png", "bg": "#0B0B0C"},
     "grades": {"vintage": "eq=...", "modern": "eq=..."},
     "output": "edit/_engineering/picture.mp4",
     "audio":  "edit/_engineering/voice.m4a",
     "shots":  [{"range": 1, "word": 0, "kind": "clip",
                 "material": "material/clips/g2_wwii/N2.mp4", "in": 89.0,
                 "grade": "vintage", "note": "飞车党公路疾驰"}],
     "labels": [{"range": 2, "word": 30, "text": "1941–45｜…", "hold": 3.6}]}

坐标规则（钉死，避免再混用）
----------------------------
- `in`：素材文件内的秒数。`kind=clip` 必填。
- `cutStart` / `dur`：剪后时间轴上的秒数，由 `plan` 从 EDL 段与词级时间算出来，**不要手写**。
- shot 起点 = 本段第一个词 → 段起点；否则 → 前一词结束与本词起点的中点（切在气口）。
- shot 终点 = 下一镜起点；最后一镜 → 段终点。
- label 的 `t` = 段起点在剪后时间轴上的偏移 +（词在源片里的时间 − 段在源片里的起点）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _geometry import fit_in_band

PLAN_NAME = "montage-plan.json"
INVENTORY_NAME = "material-inventory.json"
ENGINEERING = "_engineering"
MIN_REUSE_GAP = 5.0
DEFAULTS = {
    "width": 1080, "height": 1920, "fps": 30,
    "band": [320, 1440], "labelX": 90, "labelY": 1258,
    "base": None, "overlay": None, "bg": "#0B0B0C",
    "photoZoom": 0.10, "crf": 20, "preset": "veryfast",
}


class Fail(Exception):
    """输入不成立，或渲染前置条件缺失。带一句人能读的原因。"""


# ── 小工具 ────────────────────────────────────────────────────────────────
def run(cmd: list[str], what: str) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = (p.stderr or "").strip()[-900:]
        raise Fail(f"{what} 失败：\n{tail}")


def probe(path: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,duration,codec_type",
                        "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        raise Fail(f"读不了媒体：{path}")
    data = json.loads(p.stdout)
    stream = (data.get("streams") or [{}])[0]
    dur = stream.get("duration") or (data.get("format") or {}).get("duration")
    width, height = stream.get("width"), stream.get("height")
    if width is None:
        raise Fail(f"媒体没有视频流：{path}")
    return {"width": int(width), "height": int(height),
            "duration": float(dur) if dur not in (None, "N/A") else None}


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Fail(f"读不到 {path}：{exc}") from exc
    except ValueError as exc:
        raise Fail(f"{path} 不是合法 JSON：{exc}") from exc


def resolve_asset(value: str | Path, edit: Path) -> Path:
    """素材/底图/音轨路径：绝对路径直接用；相对路径先按项目根、再按 edit/ 找。"""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    for base in (edit.parent, edit):
        cand = (base / path).resolve()
        if cand.exists():
            return cand
    return (edit.parent / path).resolve()


def edit_and_root(target: Path) -> tuple[Path, Path]:
    """`edit/`、`成品/`、`review/` 都接受；返回 (项目根, 剪辑目录)。"""
    target = target.expanduser().resolve()
    if target.name in ("edit", "review", "成品"):
        return target.parent, target
    edit = target / "edit"
    return target, (edit if edit.is_dir() else target)


def words_of(transcript: Path) -> list[dict]:
    data = load_json(transcript)
    ws = [w for w in (data.get("words") or [])
          if w.get("type", "word") == "word" and str(w.get("text", "")).strip()]
    if not ws:
        raise Fail(f"{transcript} 里没有词级时间（type=word 且非空）")
    return ws


def pick_transcript(edit: Path, edl: dict) -> Path:
    cands = sorted((edit / "transcripts").glob("*.json")) if (edit / "transcripts").is_dir() else []
    cands = [p for p in cands if not p.name.endswith((".raw.json", "asr-raw.json"))]
    sources = list((edl.get("sources") or {}))
    if sources:
        named = [p for p in cands if p.stem in sources]
        if named:
            return named[0]
    if len(cands) == 1:
        return cands[0]
    raise Fail(f"找不到对应 EDL 源的逐字稿；候选：{[str(p) for p in cands]}")


# ── 素材唯一性（唯一实现；check_montage.py import 它） ────────────────────
class ReuseLedger:
    """同一素材被用了两次没有？唯一的判据实现，`plan` 与 `check_montage` 共用。

    2026-11 的哈雷片里，同一条素材换了个入点又被排进来，观众看到的是同一段画面两次。
    分桶（`in // 10`）漏掉「相隔 9 秒」这种近似重复，所以改按入点距离判：

    - `clip`：同一文件的两个入点相差 < `min_gap`（默认 5s）判重；
    - `photo`：同一文件第二次出现即判重——照片没有「入点」，换个数字还是同一张；
    - 说明里带文件名与上一次的镜号，才指得出该换哪一镜。
    """

    def __init__(self, min_gap: float = MIN_REUSE_GAP) -> None:
        self.min_gap = float(min_gap)
        self._seen: dict[str, list[tuple[str, float, int]]] = {}

    def note(self, path: Path | str, kind: str, in_point: float, seq: int) -> str | None:
        """登记一镜，返回与更早镜头的冲突说明（None = 不重复）。冲突也登记。"""
        name = Path(str(path)).name
        key = str(Path(str(path)).resolve())
        prev = self._seen.setdefault(key, [])
        reason = None
        for prev_kind, prev_in, prev_seq in prev:
            if kind == "photo" or prev_kind == "photo":
                reason = (f"素材重复：{name} 是照片，第 {prev_seq} 镜已用过同一文件；"
                          f"照片换个入点也还是同一张，一条素材只用一次")
                break
            gap = abs(float(in_point) - prev_in)
            if gap < self.min_gap:
                reason = (f"素材重复：{name} 与第 {prev_seq} 镜是同一文件上相隔 {gap:.1f}s 的两段"
                          f"（入点差 < {self.min_gap:g}s）；换素材，或把入点拉开")
                break
        prev.append((kind, float(in_point), seq))
        return reason


# ── 素材清单门（scan_materials.py 写，plan 读） ───────────────────────────
def inventory_files(mat: Path, edit: Path) -> list[Path]:
    """管这条素材的清单：从素材目录往上找，找到项目根为止。

    清单是 `scan_materials.py` 写在**被扫的素材目录**里的，素材通常就在它下面或更深处，
    所以最近的那份就是管它的那份。项目外的素材只看它自己那一层，不翻到项目的邻居目录。
    """
    root = edit.parent.resolve()
    cur = mat.parent.resolve()
    chain = [cur]
    while cur != cur.parent:
        cur = cur.parent
        chain.append(cur)
    if root in chain:
        chain = chain[:chain.index(root) + 1]
    else:
        chain = [mat.parent.resolve()]
    return [d / INVENTORY_NAME for d in chain if (d / INVENTORY_NAME).is_file()]


def same_material(row: dict, inv_dir: Path, mat: Path) -> bool:
    target = mat.resolve()
    raw = row.get("path")
    if raw:
        cand = Path(str(raw)).expanduser()
        try:
            if (cand if cand.is_absolute() else inv_dir / cand).resolve() == target:
                return True
        except OSError:
            pass
    name = str(row.get("name") or "")
    if name:
        try:
            if (inv_dir / name).resolve() == target:
                return True
        except OSError:
            pass
    return False


def inventory_row(mat: Path, edit: Path, cache: dict) -> tuple[Path, dict, int] | None:
    """这条素材在清单里的 (清单路径, 行, 第几行) —— 没登记返回 None。"""
    for inv in inventory_files(mat, edit):
        doc = cache.get(inv)
        if doc is None:
            try:
                doc = json.loads(inv.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise Fail(f"素材清单读不出来：{inv}（{exc}）") from exc
            cache[inv] = doc
        rows = doc.get("rows") if isinstance(doc, dict) else None
        for line, row in enumerate(rows or [], 1):
            if isinstance(row, dict) and same_material(row, inv.parent, mat):
                return inv, row, line
    return None


def require_inventory(mat: Path, edit: Path, cache: dict, shot_i: int) -> None:
    """每镜素材都要在清单里、summary 非空、usable != false；否则退 1 并指出哪一镜哪一行。"""
    found = inventory_row(mat, edit, cache)
    if found is None:
        raise Fail(
            f"第 {shot_i} 镜的素材没有登记进素材清单：{mat}\n"
            f"先跑 scan_materials.py <素材目录> 生成 {INVENTORY_NAME} 并填「画面一句话」；"
            f"清单不存在或没登记时不放行（不静默跳过）")
    inv, row, line = found
    if not str(row.get("summary") or "").strip():
        raise Fail(f"第 {shot_i} 镜的素材清单行没填 summary（{inv.name} 第 {line} 行，{mat.name}）："
                   f"补「主体 + 景别 + 色调 + 有没有文字」再 plan")
    if row.get("usable") is False:
        raise Fail(f"第 {shot_i} 镜的素材在清单里标了 usable=false（{inv.name} 第 {line} 行，"
                   f"{mat.name}）：换成可用素材；清单说不可用的不进镜头表")


# ── EDL 变速/静音：明确拒绝 ───────────────────────────────────────────────
def reject_variable_speed(ranges: list[dict]) -> None:
    """montage 不支持变速段：剪后时间按原速累加，静默算下去整片错位。"""
    for i, r in enumerate(ranges, 1):
        speed = r.get("speed")
        try:
            plain = speed is None or float(speed) == 1.0
        except (TypeError, ValueError):
            plain = False
        if not plain:
            raise Fail(f"第 {i} 段 speed={speed}：montage 的剪后时间按原速累加，"
                       f"变速段请回 recompose 或改 EDL（不在这里静默算）")
        if r.get("mute"):
            raise Fail(f"第 {i} 段 mute=true：montage 的剪后时间按原速累加、不做静音段，"
                       f"请回 recompose 或改 EDL")


# ── plan ─────────────────────────────────────────────────────────────────
def build_plan(edit: Path, spec: dict) -> dict:
    edl_path = (edit / "edl.json")
    edl = load_json(edl_path)
    ranges = edl.get("ranges") or []
    if not ranges:
        raise Fail(f"{edl_path} 没有 ranges")
    reject_variable_speed(ranges)
    transcript = pick_transcript(edit, edl)
    words = words_of(transcript)

    frame = dict(DEFAULTS)
    frame.update(spec.get("frame") or {})
    width, height = int(frame["width"]), int(frame["height"])
    top, bottom = (int(x) for x in frame["band"])
    if not (0 <= top < bottom <= height):
        raise Fail(f"band 不合法：{frame['band']}（画布 {width}×{height}）")
    fps = int(frame["fps"])

    # 每段的词表 + 剪后偏移
    offsets, per_range, acc = {}, {}, 0.0
    for i, r in enumerate(ranges, 1):
        ws = [x for x in words if x["start"] >= r["start"] - 0.25 and x["end"] <= r["end"] + 0.25]
        if not ws:
            raise Fail(f"第 {i} 段（{r['start']:.2f}-{r['end']:.2f}）里没有词，逐字稿与 EDL 不匹配")
        per_range[i] = ws
        offsets[i] = acc
        acc += r["end"] - r["start"]
    total = round(acc, 3)

    shots_spec = spec.get("shots") or []
    if not shots_spec:
        raise Fail("镜头表里没有 shots")
    # 按段分组，组内按词序号排序
    grouped: dict[int, list[dict]] = {}
    for k, s in enumerate(shots_spec, 1):
        try:
            rng, word = int(s["range"]), int(s["word"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Fail(f"第 {k} 镜缺 range/word，或不是整数：{s}") from exc
        if rng not in per_range:
            raise Fail(f"第 {k} 镜的 range={rng} 超出 1..{len(ranges)}")
        if not (0 <= word < len(per_range[rng])):
            raise Fail(f"第 {k} 镜的 word={word} 超出第 {rng} 段的词数 {len(per_range[rng])}")
        grouped.setdefault(rng, []).append(dict(s, _i=k))

    missing_range = [r for r in per_range if r not in grouped]
    if missing_range:
        raise Fail(f"这些段没有素材：{missing_range}")

    grades = spec.get("grades") or {}
    min_gap = spec.get("minReuseGap")
    min_gap = MIN_REUSE_GAP if min_gap is None else float(min_gap)
    ledger = ReuseLedger(min_gap)
    inventory_cache: dict = {}
    shots: list[dict] = []
    for i, (rng, items) in enumerate(sorted(grouped.items()), 0):
        items.sort(key=lambda x: int(x["word"]))
        ws = per_range[rng]
        r = ranges[rng - 1]
        src_start, src_end = float(r["start"]), float(r["end"])
        for idx, item in enumerate(items):
            w0 = int(item["word"])
            start = src_start if w0 == 0 else (ws[w0 - 1]["end"] + ws[w0]["start"]) / 2
            if idx + 1 < len(items):
                w1 = int(items[idx + 1]["word"])
                end = (ws[w1 - 1]["end"] + ws[w1]["start"]) / 2
            else:
                end = src_end
            dur = round(end - start, 3)
            if dur <= 0:
                raise Fail(f"第 {item['_i']} 镜时长为 {dur}：起始词与下一镜的词序重叠")

            material = item.get("material")
            if not material:
                raise Fail(f"第 {item['_i']} 镜没有 material")
            mat = resolve_asset(material, edit)
            if not mat.exists():
                raise Fail(f"素材不存在：{mat}（第 {item['_i']} 镜）")
            require_inventory(mat, edit, inventory_cache, item["_i"])
            kind = item.get("kind") or ("photo" if mat.suffix.lower() in
                                        (".jpg", ".jpeg", ".png", ".webp") else "clip")
            info = probe(mat)
            if kind == "clip":
                in_s = item.get("in")
                if in_s is None:
                    raise Fail(f"第 {item['_i']} 镜是 clip，但没有 in（素材内入点）")
                in_s = float(in_s)
                if in_s < 0:
                    raise Fail(f"第 {item['_i']} 镜 in={in_s} 为负")
                if info["duration"] and in_s + dur > info["duration"] + 0.05:
                    raise Fail(
                        f"第 {item['_i']} 镜入点越界：in={in_s:.2f}s + dur={dur:.2f}s "
                        f"> 素材时长 {info['duration']:.2f}s（{mat.name}）；"
                        f"这是「素材入点」不是「EDL 源时间」")
            reason = ledger.note(mat, kind, float(item.get("in") or 0.0), item["_i"])
            if reason:
                raise Fail(f"第 {item['_i']} 镜：{reason}")

            shots.append({
                "i": item["_i"], "range": rng, "word": w0, "kind": kind,
                "material": str(mat), "in": float(item.get("in") or 0.0),
                "grade": item.get("grade") or next(iter(grades), None),
                "cropBottom": float(item.get("cropBottom") or 0.0),
                "note": item.get("note") or "",
                "sourceStart": round(start, 3), "sourceEnd": round(end, 3),
                "cutStart": round(offsets[rng] + (start - src_start), 3),
                "dur": dur,
            })
    shots.sort(key=lambda s: (s["range"], s["word"]))
    for n, s in enumerate(shots, 1):
        s["seq"] = n

    # 花字：词锚 → 剪后时间
    labels: list[dict] = []
    for k, lab in enumerate(spec.get("labels") or [], 1):
        try:
            rng, w0 = int(lab["range"]), int(lab["word"])
            text = str(lab["text"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Fail(f"第 {k} 条花字缺 range/word/text：{lab}") from exc
        ws = per_range[rng]
        if not (0 <= w0 < len(ws)):
            raise Fail(f"第 {k} 条花字的 word={w0} 超出第 {rng} 段")
        r = ranges[rng - 1]
        t = round(offsets[rng] + (ws[w0]["start"] - float(r["start"])), 3)
        own = [s for s in shots if s["range"] == rng and s["cutStart"] <= t < s["cutStart"] + s["dur"]]
        if not own:
            raise Fail(f"第 {k} 条花字 t={t:.2f}s 不在它所在段的任何镜头里")
        sh = own[0]
        hold = float(lab.get("hold") or 3.0)
        # 词锚贴着镜头尾巴时，硬塞到尾巴里只会闪一下：推到下一镜的开头
        if sh["cutStart"] + sh["dur"] - t < 0.8 + 0.15:
            nxt = [x for x in shots if x["cutStart"] >= sh["cutStart"] + sh["dur"] - 1e-3]
            if nxt:
                sh, t = nxt[0], round(nxt[0]["cutStart"], 3)
            else:
                t = round(sh["cutStart"] + sh["dur"] - 0.95, 3)
        hold = round(max(0.8, min(hold, sh["cutStart"] + sh["dur"] - t - 0.15)), 3)
        labels.append({"text": text, "t": t, "hold": hold, "range": rng,
                       "word": w0, "shot": sh["seq"]})

    total_shot = round(sum(s["dur"] for s in shots), 3)
    if abs(total_shot - total) > 1.0 / fps + 1e-6:
        raise Fail(f"镜头时长合计 {total_shot:.3f}s 与时间轴 {total:.3f}s 不一致"
                   f"（差 {total_shot - total:+.3f}s）；检查末镜是否缺、或段端点被改过")

    return {"version": "montage-plan/1",
            "timeline": {"total": total, "edl": str(edl_path), "transcript": str(transcript)},
            "frame": frame, "grades": grades,
            "minReuseGap": min_gap,
            "inventory": sorted(str(p) for p in inventory_cache),
            "output": spec.get("output"), "audio": spec.get("audio"),
            "shots": shots, "labels": labels}


# ── render ───────────────────────────────────────────────────────────────
def label_png(text: str, dst: Path, scale: float = 1.0) -> None:
    """花字：近白中黑体、加字距、左侧 1px 竖线 + 一条轻底衬。没有 drawtext 也能画。"""
    from PIL import Image, ImageDraw, ImageFont
    size, track, pad_x, pad_y = int(40 * scale), int(3 * scale), int(22 * scale), int(16 * scale)
    font = None
    for path, idx in (("/System/Library/Fonts/Hiragino Sans GB.ttc", 1),
                      ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
                      ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
                      ("/System/Library/Fonts/Supplemental/Songti.ttc", 1)):
        try:
            font = ImageFont.truetype(path, size, index=idx)
            break
        except OSError:
            continue
    if font is None:
        raise Fail("找不到中文字体（Hiragino Sans GB / STHeiti / Songti 都没有）")
    widths = [font.getlength(ch) for ch in text]
    tw = int(sum(widths) + track * (len(text) - 1))
    asc, desc = font.getmetrics()
    W_ = tw + pad_x * 2 + 8
    H_ = asc + desc + pad_y * 2
    layer = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    grad = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(H_):
        edge = min(y, H_ - 1 - y)
        alpha = 186 if edge >= 10 * scale else int(186 * (edge / max(1, 10 * scale)) ** 0.7)
        gd.line([(0, y), (W_, y)], fill=(8, 9, 11, alpha))
    layer = Image.alpha_composite(layer, grad)
    d = ImageDraw.Draw(layer)
    d.rectangle((0, pad_y // 2, max(1, int(2 * scale)), H_ - pad_y // 2),
                fill=(243, 243, 243, 220))
    x = 8 + pad_x
    for ch, w in zip(text, widths):
        d.text((x, pad_y), ch, font=font, fill=(243, 243, 243, 255))
        x += w + track
    layer.save(dst)


def render_shot(shot: dict, plan: dict, work: Path, dirty: bool) -> Path:
    frame = plan["frame"]
    W, H = int(frame["width"]), int(frame["height"])
    top, bottom = (int(x) for x in frame["band"])
    band = bottom - top
    fps = int(frame["fps"])
    crf = int(frame.get("crf") or DEFAULTS["crf"])
    preset = frame.get("preset") or DEFAULTS["preset"]
    grade = (plan.get("grades") or {}).get(shot.get("grade")) or "null"
    dur = float(shot["dur"])
    dst = work / f"shot_{shot['seq']:03d}.mp4"
    if dst.exists() and dst.stat().st_size > 1000 and not dirty:
        return dst

    mat = Path(shot["material"])
    info = probe(mat)
    cropb = float(shot.get("cropBottom") or 0.0)
    src_h = int(info["height"] * (1 - cropb)) if cropb else info["height"]
    # 落位只有一处实现（_geometry.fit_in_band）：画框预览调同一个函数，预览才等于成片。
    fw, fh = fit_in_band(info["width"], src_h, W, band)
    y = top + (band - fh) // 2

    base = frame.get("base")
    overlay = frame.get("overlay")
    grain = "noise=alls=3:allf=t"
    inputs: list[str] = []
    if base and resolve_asset(str(base), Path(plan["_edit"])).exists():
        base_path = resolve_asset(str(base), Path(plan["_edit"]))
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(base_path)]
        have_base = True
    else:
        have_base = False
    lab = shot.get("_label")
    lab_png = None
    if lab:
        lab_png = work / f"label_{shot['seq']:03d}.png"
        label_png(lab["text"], lab_png)

    if shot["kind"] == "clip":
        pre = f"crop=iw:{max(2, int(info['height'] * (1 - cropb)))}:0:0," if cropb else ""
        if have_base:
            fc = (f"[0:v]{grain}[bg];[1:v]{pre}fps={fps},setsar=1,scale={fw}:{fh},{grade}[fg];"
                  f"[bg][fg]overlay=(W-w)/2:{y}:shortest=1[mid]")
        else:
            fc = (f"color=c={frame.get('bg', '#0B0B0C')}:s={W}x{H}:r={fps}[bg];"
                  f"[0:v]{pre}fps={fps},setsar=1,scale={fw}:{fh},{grade}[fg];"
                  f"[bg][fg]overlay=(W-w)/2:{y}:shortest=1[mid]")
        inputs += ["-ss", f"{float(shot['in']):.3f}", "-t", f"{dur + 0.4:.3f}", "-i", str(mat)]
    else:
        frames = max(2, int(round(dur * fps)))
        zoom = float(frame.get("photoZoom") or DEFAULTS["photoZoom"])
        if have_base:
            fc = (f"[0:v]{grain}[bg];"
                  f"[1:v]scale={fw * 2}:{fh * 2}:force_original_aspect_ratio=increase,"
                  f"crop={fw * 2}:{fh * 2},"
                  f"zoompan=z='min(1.0+{zoom}*on/{frames},{1 + zoom})':d=1:"
                  f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={fw}x{fh}:fps={fps},{grade}[fg];"
                  f"[bg][fg]overlay=(W-w)/2:{y}:shortest=1[mid]")
        else:
            fc = (f"color=c={frame.get('bg', '#0B0B0C')}:s={W}x{H}:r={fps}[bg];"
                  f"[0:v]scale={fw * 2}:{fh * 2}:force_original_aspect_ratio=increase,"
                  f"crop={fw * 2}:{fh * 2},"
                  f"zoompan=z='min(1.0+{zoom}*on/{frames},{1 + zoom})':d=1:"
                  f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={fw}x{fh}:fps={fps},{grade}[fg];"
                  f"[bg][fg]overlay=(W-w)/2:{y}:shortest=1[mid]")
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(mat)]

    nxt = 1 if not have_base else 2
    if overlay and resolve_asset(str(overlay), Path(plan["_edit"])).exists():
        inputs += ["-loop", "1", "-framerate", str(fps), "-i",
                   str(resolve_asset(str(overlay), Path(plan["_edit"])))]
        fc += f";[mid][{nxt}:v]overlay=0:0[with_overlay]"
        mid = "with_overlay"
        nxt += 1
    else:
        mid = "mid"
    if lab_png is not None:
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(lab_png)]
        off, hold = float(lab["off"]), float(lab["hold"])
        fc += (f";[{mid}][{nxt}:v]overlay={int(frame.get('labelX', 90))}:"
               f"{int(frame.get('labelY', 1258))}:"
               f"enable='between(t,{off:.3f},{off + hold:.3f})'[out]")
        out_label = "out"
    elif mid == "mid":
        fc += ";[mid]null[out]"
        out_label = "out"
    else:
        out_label = mid

    tmp = work / f"shot_{shot['seq']:03d}_raw.mp4"
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc,
         "-map", f"[{out_label}]", "-an", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-r", str(fps), "-g", str(fps * 2), str(tmp)],
        f"第 {shot['seq']} 镜（{shot.get('note') or mat.name}）")
    tmp.replace(dst)
    return dst


# ── 交付闸门（判据只有 render_gate.py 一处） ──────────────────────────────
def is_engineering_output(out: Path, edit: Path) -> bool:
    try:
        out.resolve().relative_to((edit / ENGINEERING).resolve())
        return True
    except ValueError:
        return False


def require_delivery_gate(root: Path, out: Path) -> dict:
    """交付件先过 render_gate：import 它，不另写一套判据（I3）。"""
    helpers = str(Path(__file__).resolve().parent)
    if helpers not in sys.path:
        sys.path.insert(0, helpers)
    import render_gate
    report = render_gate.evaluate(root, out, False)
    if not report.get("ok"):
        reasons = "；".join(str(r) for r in (report.get("reasons") or [])) or "闸门拒绝"
        raise Fail(f"交付闸门拒绝写入 {out}：{reasons}\n"
                   f"默认终点是侧边栏审阅页：交付需作者明确指令 + 人工提交覆盖当前快照。")
    return report


def render(root: Path, edit: Path, plan_path: Path, args) -> int:
    plan = load_json(plan_path)
    plan["_edit"] = str(edit)
    shots = plan["shots"]
    for s in shots:
        s["_label"] = None
    for lab in plan.get("labels") or []:
        for s in shots:
            if s["seq"] == lab["shot"]:
                s["_label"] = {"text": lab["text"],
                               "off": round(lab["t"] - s["cutStart"], 3),
                               "hold": lab["hold"]}
                break

    # 输出落在哪一级，先判清楚：闸门不通过就不渲染（别让人等完渲染才被拒）。
    engineering = True
    out: Path | None = None
    if args.concat:
        out = Path(args.out or plan.get("output") or (edit / ENGINEERING / "picture.mp4"))
        if not out.is_absolute():
            out = (edit / out).resolve()
        engineering = is_engineering_output(out, edit)
        if args.deliver and engineering:
            raise Fail(f"--deliver 指向 {out}：{ENGINEERING}/ 只放审阅素材，"
                       f"交付件请指 {edit.parent / '成品'} 下的路径")
        if not engineering:
            if not args.deliver:
                raise Fail(
                    f"{out} 不在 {ENGINEERING}/ 下。默认终点是侧边栏审阅页："
                    f"交付需作者明确指令 + 人工提交覆盖当前快照。\n"
                    f"要审阅素材就用默认输出（{edit / ENGINEERING / 'picture.mp4'}）；"
                    f"确要交付加 --deliver（先过 render_gate.py）")
            gate = require_delivery_gate(root, out)
            print(f"渲染闸门放行：{gate.get('covering')} 条人工提交覆盖快照 "
                  f"{gate.get('snapshot')}")

    if args.work:
        work = Path(args.work).expanduser()
    else:
        # 稳定命名：Python 的 str hash 每个进程不同，用它会让缓存永远不命中
        digest = hashlib.sha1(str(edit).encode("utf-8")).hexdigest()[:8]
        work = Path(tempfile.gettempdir()) / f"montage_{digest}"
    work.mkdir(parents=True, exist_ok=True)
    only = {int(x) for x in args.only.split(",") if x.strip()} if args.only else None
    done = 0
    for s in shots:
        if only and s["seq"] not in only:
            continue
        if args.max is not None and done >= args.max:
            print(f"… 已渲染 {done} 个，按 --max 停下")
            break
        existed = (work / f"shot_{s['seq']:03d}.mp4").exists()
        render_shot(s, plan, work, dirty=args.force)
        if not existed:
            done += 1
        print(f"  {s['seq']:02d}/{len(shots)}  {s['dur']:5.2f}s  {s['note'] or Path(s['material']).name}",
              flush=True)
    files = [work / f"shot_{s['seq']:03d}.mp4" for s in shots]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        print(f"还差 {len(missing)} 个镜头（例如 {missing[:3]}）；跑完再 --concat")
        return 0
    if not args.concat or out is None:
        return 0
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{f}'\n" for f in files), encoding="utf-8")
    merged = work / "merged.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(merged)], "拼接")
    total = float(plan["timeline"]["total"])
    audio = Path(args.audio or plan.get("audio") or "").expanduser()
    if args.audio or plan.get("audio"):
        if not audio.is_absolute():
            audio = (edit / audio).resolve()
        if not audio.exists():
            raise Fail(f"音轨不存在：{audio}")
        staged = work / "final.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(merged), "-i", str(audio),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-t", f"{total:.3f}", "-movflags", "+faststart", str(staged)], "混音")
    else:
        staged = merged
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged, out)          # 先落 /tmp 再搬进目标目录（云同步目录不能长写）
    print(f"{'审阅素材' if engineering else '交付件'}：{out}（{total:.2f}s，{len(shots)} 镜）")
    return 0


# ── voice-cut ────────────────────────────────────────────────────────────
def edl_source_list(edl: dict) -> list[str]:
    src = edl.get("sources")
    if isinstance(src, dict):
        return [str(v) for v in src.values() if v]
    if isinstance(src, list):
        return [str(v) for v in src if v]
    return []


def looks_like_proxy(path: Path) -> bool:
    return "proxy" in str(path).lower() or "低码" in str(path)


def voice_cut(edit: Path, args) -> int:
    """从母版按 EDL 剪竖屏人物轨（默认无声）；实测时长与计划差 > 0.5s 硬失败。"""
    edl_path = edit / "edl.json"
    edl = load_json(edl_path)
    ranges = edl.get("ranges") or []
    if not ranges:
        raise Fail(f"{edl_path} 没有 ranges")
    reject_variable_speed(ranges)

    if args.master:
        master = resolve_asset(args.master, edit)
    else:
        sources = edl_source_list(edl)
        if not sources:
            raise Fail(f"{edl_path} 没有 sources：用 --master 指母版")
        if len(sources) > 1:
            raise Fail("edl.json 有多个 sources，不知道哪个是母版；用 --master 指："
                       + "、".join(str(s) for s in sources))
        master = resolve_asset(sources[0], edit)
    if not master.exists():
        raise Fail(f"母版不存在：{master}")
    if looks_like_proxy(master):
        print(f"· {master.name} 看着是 proxy：交付用母版不用 proxy（--master 指母版）")

    plan_path = edit / PLAN_NAME
    plan = load_json(plan_path) if plan_path.is_file() else None
    frame = dict(DEFAULTS)
    if plan:
        frame.update(plan.get("frame") or {})
    W, H, fps = int(frame["width"]), int(frame["height"]), int(frame["fps"])
    if plan and (plan.get("timeline") or {}).get("total"):
        total = float(plan["timeline"]["total"])
    else:
        total = round(sum(float(r["end"]) - float(r["start"]) for r in ranges), 3)
        print(f"· 没有 {PLAN_NAME}：计划时长按 EDL 段长合计 {total:.2f}s")

    n = len(ranges)
    chain = [f"[0:v]split={n}" + "".join(f"[s{i}]" for i in range(n))]
    for i, r in enumerate(ranges):
        s, e = float(r["start"]), float(r["end"])
        chain.append(f"[s{i}]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS,"
                     f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                     f"fps={fps},setsar=1[v{i}]")
    chain.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv]")

    tmpdir = Path(tempfile.mkdtemp(prefix="voicecut_"))
    staged = tmpdir / "silent.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(master),
         "-filter_complex", ";".join(chain), "-map", "[outv]", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", str(fps), str(staged)], "剪口播轨")
    mode = "无声"
    if args.audio:
        audio = resolve_asset(args.audio, edit)
        if not audio.exists():
            raise Fail(f"口播音轨不存在：{audio}")
        muxed = tmpdir / "voice_cut.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(staged), "-i", str(audio),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
             "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(muxed)],
            "混入口播音轨")
        staged = muxed
        mode = f"口播 {Path(audio).name}"

    out = Path(args.out) if args.out else (edit / ENGINEERING / "voice_cut.mp4")
    if not out.is_absolute():
        out = (edit / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged, out)
    measured = probe(out)["duration"]
    if measured is None:
        raise Fail(f"读不出口播轨时长：{out}")
    diff = measured - total
    if abs(diff) > 0.5:
        raise Fail(f"口播轨实测 {measured:.2f}s 与计划 {total:.2f}s 差 {diff:+.2f}s（> 0.5s）："
                   f"母版与 EDL 可能不是同一版，先核对母版再交付")
    print(f"口播轨：{out}（{n} 段 · {W}×{H}@{fps} · {mode}）")
    print(f"实测 {measured:.2f}s / 计划 {total:.2f}s（差 {diff:+.2f}s）")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="现成素材蒙太奇：镜头表 → 渲染 → 合成")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="展开镜头表并校验，写 montage-plan.json")
    p_plan.add_argument("target", type=Path)
    p_plan.add_argument("--shots", type=Path, required=True, help="人读镜头表（JSON）")
    p_plan.add_argument("-o", "--out", type=Path, help="默认 <edit>/montage-plan.json")

    p_render = sub.add_parser("render", help="逐镜渲染（幂等、可 --max 分块）")
    p_render.add_argument("target", type=Path)
    p_render.add_argument("--plan", type=Path)
    p_render.add_argument("--work", help="中间文件目录，默认 /tmp/montage_<hash>")
    p_render.add_argument("--max", type=int, help="本轮最多渲染几个新镜头")
    p_render.add_argument("--only", help="只渲这些序号，逗号分隔")
    p_render.add_argument("--concat", action="store_true", help="全部渲染完后拼接")
    p_render.add_argument("--out",
                          help="拼接输出路径。默认 <edit>/_engineering/picture.mp4（审阅素材）；"
                               "不在 edit/_engineering/ 下时必须 --deliver（先过 render_gate）")
    p_render.add_argument("--audio", help="音轨路径（默认 plan.audio）")
    p_render.add_argument("--deliver", action="store_true",
                          help="声明这是交付件：目标不在 edit/_engineering/ 下时必给，"
                               "且要求至少一条人工提交覆盖当前审阅快照")
    p_render.add_argument("--force", action="store_true", help="忽略缓存重渲")

    p_voice = sub.add_parser("voice-cut", help="按 EDL 从母版剪竖屏人物轨（默认无声）")
    p_voice.add_argument("target", type=Path)
    p_voice.add_argument("--master", help="母版（默认 edl.json 的 sources；proxy 不能当交付母版）")
    p_voice.add_argument("--audio", help="口播音轨；不给就输出无声人物轨")
    p_voice.add_argument("-o", "--out", type=Path,
                         help="默认 <edit>/_engineering/voice_cut.mp4")

    args = ap.parse_args(argv)
    try:
        root, edit = edit_and_root(args.target)
        if args.cmd == "plan":
            spec = load_json(args.shots)
            plan = build_plan(edit, spec)
            out = (args.out or (edit / PLAN_NAME))
            out = out if out.is_absolute() else (edit / out)
            out.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"镜头表展开完成：{len(plan['shots'])} 镜 / {plan['timeline']['total']:.2f}s / "
                  f"{len(plan['labels'])} 条花字 → {out}")
            return 0
        if args.cmd == "voice-cut":
            return voice_cut(edit, args)
        plan_path = args.plan or (edit / PLAN_NAME)
        plan_path = plan_path if plan_path.is_absolute() else (edit / plan_path)
        if not plan_path.exists():
            raise Fail(f"没有 {plan_path}；先跑 montage.py plan")
        return render(root, edit, plan_path, args)
    except Fail as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

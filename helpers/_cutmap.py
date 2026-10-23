#!/usr/bin/env python3
"""成片二次剪的声明与核验（`edit/cut-map.json`）。

Skill 的时间轴规则是「剪点只由 EDL 表达、一次渲染」。2026-10-22 的 XHS 系列
（v1/v2/v3）为了省一次重渲，在成片渲染后又剪掉了若干段停顿（v2 是 16 刀、
−20.03s），剪点只存在项目自己的 `cut-plan.json` 里。字幕按同一批剪点重对时写错了：
它边遍历边把已经平移过的时间再去和后面剪点的**原始坐标**比较，于是每条跨过剪点的
字幕都少扣一次刀长，v2 累积偏到 3.2s；而 Skill 的交付核验只看字幕末条与总时长，
没有任何一条能发现「字幕对得上母版、对不上交付成片」。

这个模块只做两件事：

1. 读/校验 `edit/cut-map.json` —— 唯一被 Skill 认账的「第二条时间轴」。
2. 把剪前 SRT 用**单调分段映射**重算，与交付的剪后 SRT 逐条比对。

它**不剪片、不生成剪点**。没有 cut-map 的二次剪成片一律拒绝交付（见
`verify_delivery.py`）；项目要二次剪，剪片脚本自己写，但必须把剪点声明出来，
并且字幕必须能被这里逐条复算出来。

Schema（`edit/cut-map.json`，路径相对项目根或绝对）：

    {
      "version": 1,
      "masterDuration": 354.1,          # 剪前母版被使用的时长（秒），必填
      "cuts": [[11.5, 12.54], ...],      # 母版时间轴上的剪切窗口，秒，升序、不重叠
      "master": "composition/assets/person.mp4",   # 可选：母版媒体，给人看的来源说明
      "srt": {
        "source": "edit/subtitles.srt",  # 剪前字幕（母版时间轴）
        "film": "成品/v2_字幕.srt"        # 剪后字幕（成片时间轴）
      }
    }

判据（全部由 `validate()` 与 `verify_srt_pair()` 实现，不是 prose）：

- 时间映射是单调不减的分段函数：`t' = t - 已剪时长(t)`；剪切窗口内部的时间压成
  同一点（窗口是静音，字幕不应整条落在里面）。
- `masterDuration` 之后的部分不算进成片；跨越末端的窗口只算落在母版内的部分。
- 剪后 SRT 必须与剪前 SRT **条数相同、文字相同、每条起止时间误差 ≤ 20ms**。
- 成片时长必须等于 `masterDuration - 被剪时长`（容差 0.5s，见 `DURATION_TOLERANCE_S`）。
"""
from __future__ import annotations

import json
from pathlib import Path

from _timecode import parse_srt_file

CUT_MAP_NAME = "cut-map.json"
SCHEMA_VERSION = 1
CUE_TOLERANCE_MS = 20          # 剪后字幕与重算结果允许的误差
DURATION_TOLERANCE_S = 0.5     # 成片时长与 cut-map 推算值的允许误差


def path_for(edit_dir: Path) -> Path:
    return Path(edit_dir) / CUT_MAP_NAME


def load(edit_dir: Path) -> tuple[dict | None, list[str]]:
    """读 `edit/cut-map.json`。文件不存在返回 `(None, [])`——那不是错误。"""
    path = path_for(edit_dir)
    if not path.exists():
        return None, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"{CUT_MAP_NAME} 无法解析：{exc}"]
    if not isinstance(payload, dict):
        return None, [f"{CUT_MAP_NAME} 必须是 JSON 对象"]
    return payload, []


def _resolve(project_root: Path, value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (Path(project_root) / path)


def cuts_ms(payload: dict) -> list[tuple[int, int]]:
    """剪点窗口，按起点升序（毫秒）。调用前应先过 `validate()`。"""
    raw = payload.get("cuts")
    items = raw if isinstance(raw, list) else []
    out: list[tuple[int, int]] = []
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        out.append((int(round(float(item[0]) * 1000)),
                    int(round(float(item[1]) * 1000))))
    return sorted(out)


def limit_ms(payload: dict) -> int | None:
    value = payload.get("masterDuration")
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return int(round(seconds * 1000)) if seconds > 0 else None


def expected_film_duration_s(payload: dict) -> float | None:
    """母版被使用的时长减掉落在其中的剪点 → 成片应有的时长。"""
    limit = limit_ms(payload)
    if limit is None:
        return None
    removed = 0
    for start, end in cuts_ms(payload):
        start = max(0, min(start, limit))
        end = max(0, min(end, limit))
        if end > start:
            removed += end - start
    return round((limit - removed) / 1000, 6)


def removed_before_ms(t: int, cuts: list[tuple[int, int]]) -> int:
    """母版时间轴上的 `t` 之前已经被剪掉的毫秒数（窗口内部只算到 t）。"""
    removed = 0
    for start, end in cuts:
        if end <= t:
            removed += end - start
        elif start < t:
            removed += t - start
            break
        else:
            break
    return removed


def remap_ms(t: int, cuts: list[tuple[int, int]]) -> int:
    """母版时间轴 → 剪后时间轴。单调不减；落在剪切窗口里的时间压到窗口起点。"""
    return max(0, t - removed_before_ms(t, cuts))


def film_limit_ms(payload: dict) -> int | None:
    """剪后时间轴的上限（成片应有的时长，毫秒）；字幕不得越过它。"""
    expected = expected_film_duration_s(payload)
    return int(round(expected * 1000)) if expected is not None else None


def remap_cue(start_ms: int, end_ms: int, cuts: list[tuple[int, int]],
              film_limit: int | None = None) -> tuple[int, int]:
    """把一条 cue 映射到剪后时间轴；用 `film_limit`（成片时长）封顶。"""
    start = remap_ms(start_ms, cuts)
    end = remap_ms(end_ms, cuts)
    if film_limit is not None:
        start = min(start, film_limit)
        end = min(end, film_limit)
    if end < start:
        end = start
    return start, end


def validate(payload: dict, project_root: Path, *, check_files: bool = True) -> list[str]:
    """校验 schema 与引用；返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    version = payload.get("version")
    if version != SCHEMA_VERSION:
        problems.append(f"{CUT_MAP_NAME} version 必须是 {SCHEMA_VERSION}，现在是 {version!r}")

    limit = limit_ms(payload)
    if limit is None:
        problems.append(f"{CUT_MAP_NAME} 缺少可用的 masterDuration（剪前母版的时长，秒）")

    raw_cuts = payload.get("cuts")
    if not isinstance(raw_cuts, list) or not raw_cuts:
        problems.append(f"{CUT_MAP_NAME} 的 cuts 必须是非空数组（二次剪成片至少要有一刀）")
        return problems

    parsed: list[tuple[float, float]] = []
    for index, item in enumerate(raw_cuts):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            problems.append(f"{CUT_MAP_NAME} cuts[{index}] 必须是 [start, end]")
            continue
        try:
            start, end = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            problems.append(f"{CUT_MAP_NAME} cuts[{index}] 不是数字：{item!r}")
            continue
        if not (end > start):
            problems.append(f"{CUT_MAP_NAME} cuts[{index}] end({end}) 必须大于 start({start})")
        elif start < 0:
            problems.append(f"{CUT_MAP_NAME} cuts[{index}] start({start}) 不能是负数")
        elif limit is not None and start >= limit / 1000:
            problems.append(f"{CUT_MAP_NAME} cuts[{index}] start({start}) 超出母版时长 {limit / 1000:.3f}s")
        parsed.append((start, end))

    for index in range(1, len(parsed)):
        if parsed[index][0] < parsed[index - 1][1] - 1e-6:
            problems.append(f"{CUT_MAP_NAME} cuts[{index}] 与前一个窗口重叠（必须升序且不重叠）")

    expected = expected_film_duration_s(payload)
    if expected is not None and expected <= 0:
        problems.append(f"{CUT_MAP_NAME} 剪完成片时长为 {expected:.3f}s——剪点把片子剪没了")

    srt = payload.get("srt")
    if not isinstance(srt, dict) or not srt.get("source") or not srt.get("film"):
        problems.append(f"{CUT_MAP_NAME} 缺少 srt.source / srt.film（剪前与剪后字幕的路径）")
    elif check_files:
        for key, label in (("source", "剪前字幕"), ("film", "剪后字幕")):
            path = _resolve(project_root, srt.get(key))
            if not path.is_file():
                problems.append(f"{CUT_MAP_NAME} srt.{key} 指向的{label}不存在：{path}")

    master = payload.get("master")
    if master and check_files:
        path = _resolve(project_root, master)
        if not path.is_file():
            problems.append(f"{CUT_MAP_NAME} master 指向的母版不存在：{path}")
    return problems


def paths(payload: dict, project_root: Path) -> dict[str, Path]:
    """解析 cut-map 里的路径（调用前应先过 `validate()`）。"""
    srt = payload.get("srt") or {}
    result = {
        "srt_source": _resolve(project_root, srt.get("source", "")),
        "srt_film": _resolve(project_root, srt.get("film", "")),
    }
    if payload.get("master"):
        result["master"] = _resolve(project_root, payload["master"])
    return result


def _cue_text(cue: dict) -> str:
    return "\n".join(cue.get("lines") or []).strip()


def verify_srt_pair(source: Path, film: Path, payload: dict,
                    tolerance_ms: int = CUE_TOLERANCE_MS,
                    film_duration_s: float | None = None) -> list[str]:
    """剪后 SRT 能不能被「剪前 SRT + cut-map」逐条复算出来。

    这是这次事故的唯一判据：字幕对得上母版（旧 `check_edl` 只验这个）不代表对得上
    交付成片。文字必须原样保留，时间必须等于 `remap_cue()` 的结果。
    """
    problems: list[str] = []
    try:
        source_cues = parse_srt_file(Path(source))
    except Exception as exc:  # noqa: BLE001 - 解析失败要报，不能中断整个核验
        return [f"剪前字幕读不了：{source}: {exc}"]
    try:
        film_cues = parse_srt_file(Path(film))
    except Exception as exc:  # noqa: BLE001
        return [f"剪后字幕读不了：{film}: {exc}"]

    if len(source_cues) != len(film_cues):
        problems.append(f"字幕条数不一致：剪前 {len(source_cues)} 条、剪后 {len(film_cues)} 条"
                        "——剪后字幕必须只重算时间，不增删条目")
        return problems

    cuts = cuts_ms(payload)
    # 用实际成片时长封顶：母版时长是整数表，编码后成片会差几十毫秒，
    # 交付字幕是按真实成片裁的（否则最后一条会被判成 47ms 的假不一致）。
    limit = (int(round(film_duration_s * 1000)) if film_duration_s is not None
             else film_limit_ms(payload))
    for index, (before, after) in enumerate(zip(source_cues, film_cues), start=1):
        if _cue_text(before) != _cue_text(after):
            problems.append(f"第 {index} 条文字被改过：剪前「{_cue_text(before)[:18]}」/"
                            f"剪后「{_cue_text(after)[:18]}」——二次剪只重算时间")
            continue
        want_start, want_end = remap_cue(before["startMs"], before["endMs"], cuts, limit)
        if abs(after["startMs"] - want_start) > tolerance_ms or abs(after["endMs"] - want_end) > tolerance_ms:
            problems.append(
                f"第 {index} 条时间对不上 cut-map：剪后 "
                f"{after['startMs'] / 1000:.3f}-{after['endMs'] / 1000:.3f}s，"
                f"按剪点重算应为 {want_start / 1000:.3f}-{want_end / 1000:.3f}s"
                "——字幕不是从这份剪点重算出来的")
        if len(problems) >= 8:
            problems.append("……（其余不一致省略）")
            break
    return problems


def compare_srt(left: Path, right: Path,
                tolerance_ms: int = CUE_TOLERANCE_MS) -> list[str]:
    """两份 SRT 是否同一条时间轴（条数、文字、起止时间都在容差内）。

    用于「没有 cut-map 的项目」：交付的 SRT 必须就是流水线那份，不能被换成
    另一个时间轴上的版本。
    """
    problems: list[str] = []
    try:
        left_cues = parse_srt_file(Path(left))
        right_cues = parse_srt_file(Path(right))
    except Exception as exc:  # noqa: BLE001 - 解析失败要报，不能中断核验
        return [f"字幕读不了：{exc}"]
    if len(left_cues) != len(right_cues):
        return [f"字幕条数不一致：{Path(left).name} {len(left_cues)} 条、"
                f"{Path(right).name} {len(right_cues)} 条——交付的必须是同一条时间轴"]
    for index, (a, b) in enumerate(zip(left_cues, right_cues), start=1):
        if _cue_text(a) != _cue_text(b):
            problems.append(f"字幕第 {index} 条文字不一致：{Path(left).name}「{_cue_text(a)[:18]}」/"
                            f"{Path(right).name}「{_cue_text(b)[:18]}」")
        elif (abs(a["startMs"] - b["startMs"]) > tolerance_ms
              or abs(a["endMs"] - b["endMs"]) > tolerance_ms):
            problems.append(f"字幕第 {index} 条时间不一致：{Path(left).name} "
                            f"{a['startMs'] / 1000:.3f}-{a['endMs'] / 1000:.3f}s / "
                            f"{Path(right).name} {b['startMs'] / 1000:.3f}-{b['endMs'] / 1000:.3f}s")
        if len(problems) >= 5:
            problems.append("……（其余不一致省略）")
            break
    return problems


def describe(payload: dict) -> str:
    """一句话摘要，写进核验报告。"""
    cuts = cuts_ms(payload)
    limit = limit_ms(payload)
    expected = expected_film_duration_s(payload)
    pieces = [f"剪 {len(cuts)} 刀"]
    if limit is not None and expected is not None:
        pieces.append(f"−{limit / 1000 - expected:.3f}s")
    if limit is not None:
        pieces.append(f"母版 {limit / 1000:.3f}s")
    if expected is not None:
        pieces.append(f"成片 {expected:.3f}s")
    return "，".join(pieces)

"""时间码与 SRT 解析的统一入口（合并地图 M1/M2 的第一步）。

现状：字幕/时间码在五个脚本里各解析一遍，格式接受度不一致（有的只认逗号、
有的要求两位小时、有的接受 BOM/CRLF）。这里先建立**唯一的解析与格式化实现**，
暂不迁移任何调用方——先用老项目做等价性验证，再逐个替换。

契约：

- `parse_time("00:01:02,500") -> 62500`（毫秒）。逗号、点、BOM、CRLF、1–3 位小时都接受。
- `format_time(62500) -> "00:01:02,500"`；`sep="."` 可输出点号形式。
- `parse_srt_text(text) -> [{"index", "startMs", "endMs", "lines"}]`；块按空行切，
  没有序号行的块按出现顺序编号（老项目里有这种）。
- `parse_srt_file(path)` 处理 BOM 与 CRLF。
- `flatten(cue)` / `flatten(cue, " ")` 供不同消费者按需拼行。

不做判断：不排序、不去重、不修错字——那些属于各自的业务流程。
"""
from __future__ import annotations

import re
from pathlib import Path

# HH:MM:SS[,.]mmm，小时 1–3 位、毫秒 1–3 位；前后允许空白
_TIME = r"(\d{1,3}):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
_ARROW_RE = re.compile(rf"^\s*{_TIME}\s*-->\s*{_TIME}\s*$")
_INDEX_RE = re.compile(r"^\s*\d+\s*$")


class TimecodeError(ValueError):
    """时间码或字幕块无法解析。"""


def _to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    millis = millis.ljust(3, "0")[:3]
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def parse_time(value: str) -> int:
    """`00:01:02,500` / `00:01:02.500` → 62500（毫秒）。"""
    parts = re.fullmatch(_TIME, value.strip())
    if not parts:
        raise TimecodeError(f"不认识的时间码：{value!r}（要 HH:MM:SS,mmm）")
    return _to_ms(*parts.groups())


def format_time(ms: int, *, sep: str = ",") -> str:
    """毫秒 → `HH:MM:SS,mmm`（`sep="."` 时输出 `HH:MM:SS.mmm`）。"""
    if ms < 0:
        raise TimecodeError(f"时间不能为负：{ms}")
    millis = ms % 1000
    total = ms // 1000
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}{sep}{millis:03d}"


def parse_srt_text(text: str) -> list[dict]:
    """解析 SRT 文本为 cue 列表；容忍 BOM、CRLF、点号毫秒、缺序号行。"""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[dict] = []
    auto = 0
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_at = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_at is None:
            continue
        match = _ARROW_RE.match(lines[time_at])
        if not match:
            raise TimecodeError(f"时间码行不认识：{lines[time_at]!r}")
        start = _to_ms(*match.groups()[:4])
        end = _to_ms(*match.groups()[4:])
        if end < start:
            raise TimecodeError(f"结束早于开始：{lines[time_at]!r}")
        index: int | None = None
        if time_at > 0 and _INDEX_RE.match(lines[time_at - 1]):
            index = int(lines[time_at - 1])
        if index is None:
            auto += 1
            index = auto
        cues.append({"index": index, "startMs": start, "endMs": end,
                     "lines": lines[time_at + 1:]})
    return cues


def parse_srt_file(path: Path) -> list[dict]:
    return parse_srt_text(Path(path).read_text(encoding="utf-8-sig", errors="replace"))


_LOOSE_TIME = r"(\d{1,3}):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
_LOOSE_RE = re.compile(rf"{_LOOSE_TIME}\s*-->\s*{_LOOSE_TIME}", re.MULTILINE)


def parse_srt_file_loose(path: Path) -> list[dict]:
    """只抓时间码行的宽松读取，保留旧调用方的跳过语义。

    `check_edl` / `verify_delivery` 原来直接用 finditer 抓每一对时间码，
    不看块结构（字幕块之间缺空行也能读）；迁移到统一实现时保留这个行为，
    避免把"读得到"变成"读不到"。
    """
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    cues = []
    for match in _LOOSE_RE.finditer(text):
        groups = match.groups()
        start = _to_ms(*groups[:4])
        end = _to_ms(*groups[4:])
        if end >= start:
            cues.append({"index": len(cues) + 1, "startMs": start,
                         "endMs": end, "lines": []})
    return cues


def flatten(cue: dict, sep: str = "\n") -> str:
    """cue 的文本行拼成一条；不同消费者用不同分隔（`" "` 或 `""`）。"""
    return sep.join(cue["lines"]).strip()

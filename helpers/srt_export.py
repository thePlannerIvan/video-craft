"""Build an output-timeline SRT from a locked article and line plan.

The normal subtitle path is deliberately article-first:

    srt_export.py EDIT --prepare
    # review/edit captions_article.txt, then write semantic_lines.txt
    srt_export.py EDIT --lock
    srt_export.py EDIT --build --check

``--prepare`` extracts the final kept word sequence from the EDL and writes
one complete article plus a machine-readable word timeline. ``--lock`` proves
that the article still contains exactly that sequence (ignoring punctuation,
spacing and case). ``--build`` then matches each semantic line to contiguous
kept words once and emits the SRT. It refuses stale EDL/transcript inputs,
missing lines, omissions, duplicates, cross-segment cues and word splits.

The old transcript-to-SRT path remains available only through the explicit
``--legacy-sentence`` or ``--cue-len`` switches. It is not a safe default for
semantic Chinese captions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _edl  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _words import content_len as _content_len  # noqa: E402
from _words import normalize as _normalize_shared  # noqa: E402


ARTICLE_NAME = "captions_article.txt"
WORDS_NAME = "caption_words.json"
CORRECTIONS_NAME = "caption_corrections.json"
LOCK_NAME = "caption_lock.json"
LINES_NAME = "semantic_lines.txt"
CAPTIONS_NAME = "captions.json"
SRT_NAME = "subtitles.srt"

# 剪映/PR 导入空隙（references/caption-modes.md 的硬规则，2026-10-16 才落地成代码）：
# cue 首尾相接（前句 end == 后句 start）导入剪映会挤坏。导出时给每个 cue（最后一个除外）
# 的 end 缩短 0.04s，保证空隙 ≥0.03s；显示时长不足 0.30s 的保留保底。
# 这条规则此前**只有文档没有实现**，每次交付都得手写一份后处理脚本（实测一份 SRT 有
# 22 处不合规）。落在导出器里，于是每条交付路径自动带上。
SRT_GAP_TRIM_S = 0.04
SRT_MIN_GAP_S = 0.03
SRT_MIN_CUE_S = 0.30
CONTRACT_VERSION = 2
MAX_CONTENT_CHARS = 20

# Normalization is imported from _words, NOT redefined here. This module used to
# carry its own copy of the punctuation regex, so the "single source of truth"
# claim in _words.py was false and the caption contract could silently disagree
# with the EDL contracts about what "the same text" means. One definition, one
# behaviour; WordHelperTests pins the agreement.


def _fail(message: str) -> None:
    raise SystemExit(f"caption contract error: {message}")


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _clean_text(text: str) -> str:
    text = " ".join(text.split())
    text = re.sub(
        r"(?<=[\u4e00-\u9fff\u3000-\u303f])\s+(?=[\u4e00-\u9fff\u3000-\u303f])",
        "",
        text,
    )
    text = re.sub(r"([，。！？、；：])\s+", r"\1", text)
    text = re.sub(r"\s+([，。！？、；：])", r"\1", text)
    return text.strip()


def _join_tokens(tokens: list[str]) -> str:
    """Join CJK tokens without spaces while keeping Latin words readable."""
    result = ""
    previous = ""
    for raw in tokens:
        text = _clean_text(raw)
        if not text:
            continue
        if not result:
            result = text
        elif re.search(r"[A-Za-z0-9]", text) or re.search(r"[A-Za-z0-9]", previous):
            if re.fullmatch(r"[A-Za-z0-9~～]+", previous) and re.fullmatch(r"[\u4e00-\u9fff]+", text):
                result += text
            elif previous in {"C", "端"} or text in {"端"}:
                result += text
            else:
                result += " " + text
        else:
            result += text
        previous = text
    return _clean_text(result)


def _match_text(text: str) -> str:
    """Normalize only syntax, never silently rewrite semantic words.

    Kept as a named wrapper so the call sites read as before; the behaviour
    lives in `_words.normalize`, the one definition both contracts share.
    """
    return _normalize_shared(text)


def _words_in_range(transcript: dict, t_start: float, t_end: float) -> list[dict]:
    words = []
    for index, word in enumerate(transcript.get("words", [])):
        if word.get("type") != "word":
            continue
        start = word.get("start")
        end = word.get("end")
        if start is None or end is None or end <= t_start or start >= t_end:
            continue
        visible = min(end, t_end) - max(start, t_start)
        if visible < 0.8 * (end - start):
            continue
        text = _clean_text(str(word.get("text") or ""))
        if not text:
            continue
        words.append({
            "transcript_index": index,
            "text": text,
            "source_start": float(start),
            "source_end": float(end),
        })
    return words


def _load_corrections(edit_dir: Path, corrections_path: Path | None = None) -> tuple[dict[tuple[str, int], dict], str]:
    path = (corrections_path or (edit_dir / CORRECTIONS_NAME)).resolve()
    if not path.exists():
        return {}, "none"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"invalid {path.name}: {exc}")
    if not isinstance(raw, list):
        _fail(f"{path.name} must be a JSON array")
    corrections: dict[tuple[str, int], dict] = {}
    for item in raw:
        if not isinstance(item, dict) or not item.get("source") or item.get("transcript_index") is None:
            _fail(f"each {CORRECTIONS_NAME} entry needs source and transcript_index")
        key = (str(item["source"]), int(item["transcript_index"]))
        if key in corrections:
            _fail(f"duplicate correction for {key[0]} word {key[1]}")
        action = item.get("action")
        if action not in {"drop", "replace"}:
            _fail(f"correction {key[0]}:{key[1]} action must be drop or replace")
        if action == "replace" and not _clean_text(str(item.get("text") or "")):
            _fail(f"replacement correction {key[0]}:{key[1]} needs non-empty text")
        if not item.get("reason"):
            _fail(f"correction {key[0]}:{key[1]} needs a reason")
        corrections[key] = item
    return corrections, _sha256(path)


def _edl_paths(edit_dir: Path, edl_path: Path | None = None) -> tuple[Path, dict]:
    path = (edl_path or (edit_dir / "edl.json")).resolve()
    if not path.exists():
        _fail(f"no EDL at {path}")
    try:
        edl = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"invalid EDL JSON: {exc}")
    if not isinstance(edl.get("ranges"), list) or not edl["ranges"]:
        _fail("EDL must contain a non-empty ranges array")
    return path, edl


def _measured_durations(edit_dir: Path, edl_file: Path, count: int,
                        strict: bool) -> tuple[list[float] | None, str | None]:
    """Per-segment durations the last render actually produced.

    The policy lives in `_edl.duration_record` — one answer shared with the
    delivery gates. Before, this function kept its own loop and took the FIRST
    matching record while delivery took the LAST: two records with the same EDL
    digest produced different caption timelines (audit evidence:
    caption [1.1, 0.9] vs delivery [1.0, 1.0], same EDL, same total).
    """
    path = edit_dir / "segment_durations.json"
    if not path.exists():
        print("  · 还没有渲染结果，也没有解析预演，字幕按 EDL 标称时间轴生成"
              "（可先跑 helpers/duration_plan.py 得到预演时间轴）")
        return None, None
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("  · segment_durations.json 无法解析，按标称时间轴生成")
        return None, None
    durations, source, tag, problem = _edl.duration_record(edit_dir, count, edl_path=edl_file)
    if durations is not None:
        total = sum(durations)
        if source == "measured":
            print(f"  · 字幕时间轴取自实测段时长（{tag}，共 {total:.3f}s）")
        else:
            print(f"  ！字幕时间轴取自解析预演（{tag}，共 {total:.3f}s）——"
                  "可在渲染前用于审阅；交付前必须真实渲染并重建字幕")
        return durations, source
    if problem:
        if strict:
            _fail(f"没有找到与当前 EDL 匹配的段时长记录（{problem}）——"
                  "先跑 helpers/duration_plan.py 得到预演时间轴，或重新渲染后再生成字幕")
        print(f"  ! 没有找到与当前 EDL 匹配的段时长记录（{problem}）——"
              "本次按标称时间轴生成，不能作为交付版本")
        return None, None
    print("  · segment_durations.json 是旧格式，按标称时间轴生成")
    return None, None


def _load_timeline_words(edit_dir: Path, edl_path: Path | None = None,
                         corrections_path: Path | None = None,
                         strict_render: bool = False) -> tuple[dict, list[dict]]:
    edl_file, edl = _edl_paths(edit_dir, edl_path)
    measured, timeline_source = _measured_durations(
        edit_dir, edl_file, len(edl["ranges"]), strict_render)
    corrections, corrections_sha256 = _load_corrections(edit_dir, corrections_path)
    transcripts_dir = edit_dir / "transcripts"
    if not transcripts_dir.is_dir():
        _fail(f"no transcripts directory at {transcripts_dir}")

    transcript_hashes: dict[str, str] = {}
    transcript_cache: dict[str, dict] = {}
    for source_name in edl["sources"]:
        transcript_path = transcripts_dir / f"{source_name}.json"
        if not transcript_path.exists():
            _fail(f"no transcript for source {source_name}: {transcript_path}")
        transcript_hashes[source_name] = _sha256(transcript_path)
        try:
            transcript_cache[source_name] = json.loads(transcript_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _fail(f"invalid transcript JSON for {source_name}: {exc}")

    words: list[dict] = []
    segments: list[dict] = []
    output_offset = 0.0
    for segment_index, item in enumerate(edl["ranges"]):
        source_name = item["source"]
        start = float(item["start"])
        end = float(item["end"])
        speed = float(item.get("speed", 1.0))
        if end <= start:
            _fail(f"EDL range {segment_index} has end <= start")
        if speed <= 0:
            _fail(f"EDL range {segment_index} has non-positive speed")
        duration = measured[segment_index] if measured else (end - start) / speed
        segment_words = _words_in_range(transcript_cache[source_name], start, end)
        corrected_words = []
        for word in segment_words:
            correction = corrections.get((source_name, int(word["transcript_index"])))
            if correction and correction.get("action") == "drop":
                continue
            if correction and correction.get("action") == "replace":
                word = dict(word)
                word["text"] = _clean_text(str(correction["text"]))
                word["correction"] = correction["reason"]
            corrected_words.append(word)
        segment_words = corrected_words
        segment_record = {
            "index": segment_index,
            "source": source_name,
            "source_start": start,
            "source_end": end,
            "speed": speed,
            "output_start": round(output_offset, 6),
            "output_end": round(output_offset + duration, 6),
            "word_count": len(segment_words),
        }
        segments.append(segment_record)
        for word_index, word in enumerate(segment_words):
            word_start = max(start, word["source_start"])
            word_end = min(end, word["source_end"])
            words.append({
                "segment": segment_index,
                "segment_word": word_index,
                "transcript_index": word["transcript_index"],
                "text": word["text"],
                "source_start": word["source_start"],
                "source_end": word["source_end"],
                "out_start": round(output_offset + max(0.0, (word_start - start) / speed), 6),
                "out_end": round(output_offset + max(0.0, (word_end - start) / speed), 6),
            })
            if "correction" in word:
                words[-1]["correction"] = word["correction"]
        output_offset += duration

    contract = {
        "version": CONTRACT_VERSION,
        "edl_sha256": _sha256(edl_file),
        "transcript_sha256": transcript_hashes,
        "corrections_sha256": corrections_sha256,
        "segments": segments,
        "total_duration": round(output_offset, 6),
        # Which timeline the cue times were derived from. "measured" is the
        # render's own per-segment durations; "projected" is the frame-quantised
        # analytic plan (good enough to review, NOT a delivery artefact);
        # "nominal" means neither existed and the SRT must not ship.
        "timeline_source": timeline_source or "nominal",
    }
    return contract, words


def _words_contract_path(edit_dir: Path, override: Path | None = None) -> Path:
    return (override or (edit_dir / WORDS_NAME)).resolve()


def _load_words_contract(edit_dir: Path, edl_path: Path | None = None,
                         words_path: Path | None = None,
                         corrections_path: Path | None = None,
                         strict_render: bool = False) -> tuple[dict, list[dict]]:
    contract, current_words = _load_timeline_words(edit_dir, edl_path, corrections_path,
                                                   strict_render=strict_render)
    path = _words_contract_path(edit_dir, words_path)
    if not path.exists():
        _fail(f"no {WORDS_NAME}; run --prepare before locking or building")
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"invalid {path.name}: {exc}")
    for key in ("version", "edl_sha256", "transcript_sha256", "corrections_sha256", "segments", "words"):
        if key not in stored:
            _fail(f"{path.name} is missing required field {key}")
    if stored["version"] != CONTRACT_VERSION:
        _fail(f"{path.name} version {stored['version']} is not supported")
    if stored["edl_sha256"] != contract["edl_sha256"]:
        _fail(f"{path.name} was made from a different EDL; run --prepare again")
    if stored["transcript_sha256"] != contract["transcript_sha256"]:
        _fail(f"{path.name} was made from a different transcript; run --prepare again")
    if stored["corrections_sha256"] != contract["corrections_sha256"]:
        _fail(f"{path.name} was made from a different correction map; run --prepare again")
    if _json_sha256(stored["segments"]) != _json_sha256(contract["segments"]):
        _fail(f"{path.name} segment map is stale; run --prepare again")
    if len(stored["words"]) != len(current_words):
        _fail(f"{path.name} word count is stale; run --prepare again")
    if _json_sha256(stored["words"]) != _json_sha256(current_words):
        _fail(f"{path.name} word timeline was edited; run --prepare again")
    return stored, stored["words"]


def _article_from_words(words: list[dict], segments: list[dict]) -> str:
    by_segment: dict[int, list[str]] = {}
    for word in words:
        by_segment.setdefault(int(word["segment"]), []).append(word["text"])
    paragraphs = [_join_tokens(by_segment.get(int(segment["index"]), [])) for segment in segments]
    return "\n\n".join(paragraphs).strip() + "\n"


def prepare_article(edit_dir: Path, edl_path: Path | None = None,
                    article_path: Path | None = None,
                    words_path: Path | None = None,
                    corrections_path: Path | None = None,
                    force: bool = False) -> None:
    contract, words = _load_timeline_words(edit_dir, edl_path, corrections_path)
    article_file = (article_path or (edit_dir / ARTICLE_NAME)).resolve()
    words_file = _words_contract_path(edit_dir, words_path)
    if not force and (article_file.exists() or words_file.exists()):
        _fail(
            f"{article_file.name} or {words_file.name} already exists; "
            "use --force-prepare only after confirming the EDL/transcript changed"
        )
    article_file.write_text(_article_from_words(words, contract["segments"]), encoding="utf-8")
    payload = dict(contract)
    payload["words"] = words
    words_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # The lock, the generated cues and the SRT are invalidated by any change in
    # the word timeline. The LINE PLAN is deliberately kept: re-preparing after
    # a render re-binds the timeline to the measured durations, and the reviewed
    # line plan is still valid as long as the article text is unchanged —
    # --build re-checks it against the locked article and refuses a stale plan.
    for stale in (edit_dir / LOCK_NAME, edit_dir / CAPTIONS_NAME, edit_dir / SRT_NAME):
        if stale.exists():
            stale.unlink()
    print(f"prepared {article_file.name} and {words_file.name} ({len(words)} kept words)")
    print("Next: review the full article, write semantic_lines.txt, then run --lock and --build.")
    print("      (语义行方案已保留；若正文改了，--build 会拒绝并要求重新切分)")


def _load_article(edit_dir: Path, article_path: Path | None = None) -> tuple[Path, str]:
    path = (article_path or (edit_dir / ARTICLE_NAME)).resolve()
    if not path.exists():
        _fail(f"no {ARTICLE_NAME}; run --prepare first")
    text = path.read_text(encoding="utf-8").strip()
    if not _match_text(text):
        _fail(f"{path.name} is empty")
    return path, text + "\n"


def _article_sequence(words: list[dict], segments: list[dict]) -> str:
    return _match_text(_article_from_words(words, segments))


def lock_article(edit_dir: Path, edl_path: Path | None = None,
                 article_path: Path | None = None,
                 words_path: Path | None = None,
                 corrections_path: Path | None = None) -> None:
    stored, words = _load_words_contract(edit_dir, edl_path, words_path, corrections_path)
    article_file, article = _load_article(edit_dir, article_path)
    expected = _article_sequence(words, stored["segments"])
    actual = _match_text(article)
    if actual != expected:
        common = 0
        for left, right in zip(actual, expected):
            if left != right:
                break
            common += 1
        context = max(0, common - 18)
        raise SystemExit(
            "caption contract error: article does not cover the kept word sequence "
            f"at normalized character {common}; article={actual[context:common + 24]!r}, "
            f"transcript={expected[context:common + 24]!r}. "
            "Fix the EDL or record an explicit word correction; do not patch the SRT."
        )
    lock = {
        "version": CONTRACT_VERSION,
        "article": article_file.name,
        "article_sha256": _sha256(article_file),
        "words_sha256": _sha256(_words_contract_path(edit_dir, words_path)),
        "edl_sha256": stored["edl_sha256"],
        "transcript_sha256": stored["transcript_sha256"],
        "normalized_characters": len(actual),
    }
    (edit_dir / LOCK_NAME).write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"locked {article_file.name} ({len(actual)} normalized characters)")


def _parse_line_blocks(path: Path, segment_count: int) -> list[list[str]]:
    if not path.exists():
        _fail(f"no {path.name}; split the locked article before building SRT")
    raw_blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    blocks = [[line.strip() for line in block.splitlines() if line.strip()] for block in raw_blocks]
    blocks = [block for block in blocks if block]
    if len(blocks) != segment_count:
        _fail(f"{path.name} has {len(blocks)} segment blocks but the EDL has {segment_count}")
    return blocks


def _match_lines(words: list[dict], segments: list[dict], line_blocks: list[list[str]]) -> list[dict]:
    words_by_segment: dict[int, list[dict]] = {}
    for word in words:
        words_by_segment.setdefault(int(word["segment"]), []).append(word)
    cues: list[dict] = []
    for segment in segments:
        segment_index = int(segment["index"])
        segment_words = words_by_segment.get(segment_index, [])
        position = 0
        for line_index, line in enumerate(line_blocks[segment_index]):
            if _content_len(line) > MAX_CONTENT_CHARS:
                _fail(
                    f"semantic line {segment_index + 1}.{line_index + 1} has "
                    f"{_content_len(line)} content characters; maximum is {MAX_CONTENT_CHARS}"
                )
            target = _match_text(line)
            if not target:
                _fail(f"empty semantic line {segment_index + 1}.{line_index + 1}")
            start_position = position
            accumulated = ""
            while position < len(segment_words) and len(accumulated) < len(target):
                token = _match_text(segment_words[position]["text"])
                accumulated += token
                position += 1
                if not target.startswith(accumulated):
                    _fail(
                        f"line {segment_index + 1}.{line_index + 1} does not match kept words; "
                        f"line={line!r}, matched={accumulated!r}"
                    )
            if accumulated != target:
                _fail(
                    f"line {segment_index + 1}.{line_index + 1} ends inside a word or omits text; "
                    f"line={line!r}, matched={accumulated!r}"
                )
            last_content = position - 1
            # A punctuation token carries no content, so the loop above can never
            # reach it — `len(accumulated) < len(target)` is already false. Left
            # stranded, it tripped "semantic lines leave kept words unmatched in
            # segment 1: '。'" on every segment that ends on a 。or ，. It belongs to
            # the line before it, so absorb it here for the position bookkeeping.
            while (position < len(segment_words)
                   and not _match_text(segment_words[position]["text"])):
                position += 1
            first = segment_words[start_position]
            # keep the cue's end on the last CONTENT word: punctuation tokens can
            # span a following pause, which would stretch the cue into silence
            last = segment_words[last_content]
            cues.append({
                "segment": segment_index,
                "line": line,
                "start": first["out_start"],
                "end": last["out_end"],
                "source_start": first["source_start"],
                "source_end": last["source_end"],
            })
        if position != len(segment_words):
            remainder = _join_tokens([word["text"] for word in segment_words[position:]])
            _fail(f"semantic lines leave kept words unmatched in segment {segment_index + 1}: {remainder!r}")
    return cues


def _assert_lock(edit_dir: Path, stored: dict, article_path: Path,
                 words_path: Path) -> None:
    lock_path = edit_dir / LOCK_NAME
    if not lock_path.exists():
        _fail(f"no {LOCK_NAME}; run --lock after reviewing the full article")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"invalid {LOCK_NAME}: {exc}")
    checks = {
        "article_sha256": _sha256(article_path),
        "words_sha256": _sha256(words_path),
        "edl_sha256": stored["edl_sha256"],
        "transcript_sha256": stored["transcript_sha256"],
    }
    for key, expected in checks.items():
        if lock.get(key) != expected:
            _fail(f"{LOCK_NAME} is stale at {key}; re-lock the article before building")



def apply_import_gaps(cues: list[dict]) -> int:
    """把 cue 之间的导入空隙修到剪映能接受的程度，返回被调整的条数。

    **在交付边界调用**（`export_deliverables.py` 写 `成品/*.srt` 时），不在 `--build`
    的产出上调用：`subtitles.srt` 的契约是「每个 cue 的时间戳等于保留词的边界」，
    `check_article_srt` 会逐条核对，就地改 end 会把那份契约弄假。
    换句话说：流水线产物忠实，交付副本可导入，两者各有各的判据。

    规则（references/caption-modes.md「剪映/PR 导入空隙」）：
      ① 每个 cue（最后一个除外）的 end 先减 `SRT_GAP_TRIM_S`；
      ② 仍与下一 cue 相距 < `SRT_MIN_GAP_S` 时，压到 `下一 cue.start - SRT_MIN_GAP_S`；
      ③ 显示时长不足 `SRT_MIN_CUE_S` 的保留保底，但不越过 ② 的上限。
    文本、条数、顺序与主时间轴起点一律不动 —— 只动 end。
    """
    fixed = 0
    for i, cue in enumerate(cues[:-1]):
        nxt = cues[i + 1]["start"]
        original = cue["end"]
        end = cue["end"] - SRT_GAP_TRIM_S
        if nxt - end < SRT_MIN_GAP_S:
            end = nxt - SRT_MIN_GAP_S
        end = max(end, min(cue["start"] + SRT_MIN_CUE_S, nxt - SRT_MIN_GAP_S))
        if end <= cue["start"]:
            end = cue["start"] + 0.01
        if abs(end - original) > 1e-9:
            cue["end"] = end
            fixed += 1
    return fixed


def build_article_srt(edit_dir: Path, edl_path: Path | None = None,
                      article_path: Path | None = None,
                      lines_path: Path | None = None,
                      words_path: Path | None = None,
                      out_path: Path | None = None,
                      corrections_path: Path | None = None) -> int:
    # Delivery path: refuse to emit cues when the render no longer matches this
    # EDL, because they would be timed against a timeline that does not exist.
    stored, words = _load_words_contract(edit_dir, edl_path, words_path, corrections_path,
                                         strict_render=True)
    article_file, article = _load_article(edit_dir, article_path)
    words_file = _words_contract_path(edit_dir, words_path)
    _assert_lock(edit_dir, stored, article_file, words_file)
    lines_file = (lines_path or (edit_dir / LINES_NAME)).resolve()
    line_blocks = _parse_line_blocks(lines_file, len(stored["segments"]))
    if _match_text("\n".join(line for block in line_blocks for line in block)) != _match_text(article):
        _fail(f"{lines_file.name} does not cover the locked article exactly; re-split from the article")
    cues = _match_lines(words, stored["segments"], line_blocks)
    out_file = (out_path or (edit_dir / SRT_NAME)).resolve()
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        lines.extend([str(index), f"{_srt_timestamp(cue['start'])} --> {_srt_timestamp(cue['end'])}", cue["line"], ""])
    out_file.write_text("\n".join(lines), encoding="utf-8")
    (edit_dir / CAPTIONS_NAME).write_text(json.dumps(cues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"article-first SRT -> {out_file.name} ({len(cues)} cues)")
    return len(cues)


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    timestamp_re = re.compile(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)")

    def seconds(parts: tuple[str, ...]) -> float:
        h, m, s, ms = (int(value) for value in parts)
        return h * 3600 + m * 60 + s + ms / 1000

    cues: list[tuple[float, float, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip().isdigit() and index + 1 < len(lines):
            match = timestamp_re.fullmatch(lines[index + 1].strip())
            if match:
                start = seconds(match.groups()[:4])
                end = seconds(match.groups()[4:])
                text_lines: list[str] = []
                cursor = index + 2
                while cursor < len(lines) and lines[cursor].strip():
                    text_lines.append(lines[cursor].strip())
                    cursor += 1
                cues.append((start, end, "\n".join(text_lines)))
                index = cursor
                continue
        index += 1
    return cues


def check_article_srt(edit_dir: Path, edl_path: Path | None = None,
                      article_path: Path | None = None,
                      lines_path: Path | None = None,
                      words_path: Path | None = None,
                      out_path: Path | None = None,
                      corrections_path: Path | None = None) -> None:
    stored, words = _load_words_contract(edit_dir, edl_path, words_path, corrections_path,
                                         strict_render=True)
    article_file, article = _load_article(edit_dir, article_path)
    words_file = _words_contract_path(edit_dir, words_path)
    _assert_lock(edit_dir, stored, article_file, words_file)
    lines_file = (lines_path or (edit_dir / LINES_NAME)).resolve()
    blocks = _parse_line_blocks(lines_file, len(stored["segments"]))
    expected_cues = _match_lines(words, stored["segments"], blocks)
    expected_text = [_clean_text(cue["line"]) for cue in expected_cues]
    output_file = (out_path or (edit_dir / SRT_NAME)).resolve()
    if not output_file.exists():
        _fail(f"no {output_file.name}; run --build first")
    actual_cues = parse_srt(output_file)
    if len(actual_cues) != len(expected_cues):
        _fail(f"SRT has {len(actual_cues)} cues but the locked line plan has {len(expected_cues)}")
    previous_end = -1.0
    for index, ((actual_start, actual_end, actual_text), expected) in enumerate(zip(actual_cues, expected_cues), start=1):
        if actual_start < previous_end:
            _fail(f"SRT cue {index} overlaps the previous cue")
        if actual_end <= actual_start:
            _fail(f"SRT cue {index} has non-positive duration")
        if _clean_text(actual_text) != expected_text[index - 1]:
            _fail(f"SRT cue {index} text differs from semantic_lines.txt; rebuild instead of patching")
        if abs(actual_start - expected["start"]) > 0.002 or abs(actual_end - expected["end"]) > 0.002:
            _fail(f"SRT cue {index} timestamp differs from kept word boundaries; rebuild instead of patching")
        previous_end = actual_end
    total = float(stored["total_duration"])
    if actual_cues and actual_cues[-1][1] > total + 0.05:
        _fail(f"SRT ends at {actual_cues[-1][1]:.3f}s beyond EDL duration {total:.3f}s")
    if actual_cues and actual_cues[-1][1] < total - 0.5:
        print(f"warning: final subtitle ends {total - actual_cues[-1][1]:.3f}s before EDL end (tail may be silence)")
    lengths = [_content_len(text) for _, _, text in actual_cues]
    print(
        f"caption check OK: {len(actual_cues)} cues | content length "
        f"min={min(lengths)} max={max(lengths)} | timeline={total:.3f}s"
    )


# Explicit legacy path retained for short-form or non-semantic captions.
SENTENCE_ENDS = set(".!?。！？…")
MAX_WORDS_PER_LINE = 30


def group_sentences(words: list[dict]) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        current.append(word)
        if len(current) >= MAX_WORDS_PER_LINE or text[-1] in SENTENCE_ENDS:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def rechunk_cues(words: list[dict], minimum: int, maximum: int) -> list[tuple[float, float, str]]:
    groups: list[tuple[int, int]] = []
    index = 0
    while index < len(words):
        cursor = index
        total = 0
        last_break = None
        while cursor < len(words) and total + len(words[cursor]["text"]) <= maximum:
            total += len(words[cursor]["text"])
            if total >= minimum:
                last_break = cursor + 1
            cursor += 1
        cut = last_break if last_break is not None else max(index + 1, cursor)
        groups.append((index, cut))
        index = cut
    cues: list[tuple[float, float, str]] = []
    for start, end in groups:
        text = _clean_text(" ".join(words[index]["text"] for index in range(start, end)))
        cues.append((words[start]["out_start"], words[end - 1]["out_end"], text))
    return cues


def legacy_srt(edit_dir: Path, edl_path: Path | None, out_path: Path,
               cue_len: tuple[int, int] | None,
               corrections_path: Path | None = None) -> int:
    _, words = _load_timeline_words(edit_dir, edl_path, corrections_path)
    if cue_len:
        entries = rechunk_cues(words, *cue_len)
    else:
        entries = []
        by_segment: dict[int, list[dict]] = {}
        for word in words:
            by_segment.setdefault(int(word["segment"]), []).append(word)
        for segment_words in by_segment.values():
            for chunk in group_sentences(segment_words):
                entries.append((chunk[0]["out_start"], chunk[-1]["out_end"], _clean_text(" ".join(w["text"] for w in chunk))))
    entries.sort(key=lambda entry: entry[0])
    lines: list[str] = []
    for index, (start, end, text) in enumerate(entries, start=1):
        lines.extend([str(index), f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}", text, ""])
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"WARNING: explicit legacy SRT -> {out_path.name} ({len(entries)} cues)")
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description="Article-first SRT builder for video-use")
    parser.add_argument("edit_dir", type=Path, help="edit directory containing edl.json and transcripts/")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true", help="extract caption_words.json and one complete captions_article.txt")
    modes.add_argument("--lock", action="store_true", help="verify and lock the reviewed article")
    modes.add_argument("--build", action="store_true", help="match semantic_lines.txt once and emit subtitles.srt")
    modes.add_argument("--legacy-sentence", action="store_true", help="explicit legacy sentence grouping")
    parser.add_argument("--edl", type=Path, default=None, help="EDL path override")
    parser.add_argument("--article", type=Path, default=None, help=f"article path (default: {ARTICLE_NAME})")
    parser.add_argument("--lines", type=Path, default=None, help=f"semantic line plan (default: {LINES_NAME})")
    parser.add_argument("--words", type=Path, default=None, help=f"word contract (default: {WORDS_NAME})")
    parser.add_argument("--corrections", type=Path, default=None, help=f"explicit ASR/filler corrections (default: {CORRECTIONS_NAME} if present)")
    parser.add_argument("--force-prepare", action="store_true", help="allow --prepare to replace an existing article/word contract")
    parser.add_argument("-o", "--output", type=Path, default=None, help=f"SRT output path (default: {SRT_NAME})")
    parser.add_argument("--check", action="store_true", help="validate the generated article-first SRT; may follow --build")
    parser.add_argument("--cue-len", type=str, default=None, help="legacy only: MIN-MAX content characters")
    args = parser.parse_args()
    edit_dir = args.edit_dir.resolve()
    edl_path = args.edl.resolve() if args.edl else None

    if args.prepare:
        prepare_article(edit_dir, edl_path, args.article, args.words, args.corrections, args.force_prepare)
        return
    if args.lock:
        lock_article(edit_dir, edl_path, args.article, args.words, args.corrections)
        return
    if args.build:
        build_article_srt(edit_dir, edl_path, args.article, args.lines, args.words, args.output, args.corrections)
        if args.check:
            check_article_srt(edit_dir, edl_path, args.article, args.lines, args.words, args.output, args.corrections)
        return
    if args.check:
        check_article_srt(edit_dir, edl_path, args.article, args.lines, args.words, args.output, args.corrections)
        return
    if args.legacy_sentence or args.cue_len:
        cue_len = None
        if args.cue_len:
            try:
                minimum, maximum = (int(value) for value in args.cue_len.split("-"))
            except ValueError:
                _fail("--cue-len must be MIN-MAX")
            if minimum < 1 or maximum < minimum:
                _fail("--cue-len needs 1 <= MIN <= MAX")
            cue_len = (minimum, maximum)
        legacy_srt(edit_dir, edl_path, (args.output or (edit_dir / SRT_NAME)).resolve(), cue_len, args.corrections)
        return
    parser.error("choose --prepare, --lock, --build, --check, or an explicit legacy mode; implicit SRT generation is disabled")


if __name__ == "__main__":
    main()
